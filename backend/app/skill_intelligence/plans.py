"""Learning plan lifecycle: create from a generated path, then
pause/resume/complete-module/skip-module/reorder/set-target-date/
set-weekly-goal, plus a progress summary.

Status transitions are validated here (same "never set status
directly elsewhere" convention as MockInterviewSession's
state_machine): active <-> paused, active -> completed/cancelled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import LearningPlan, LearningPlanModule
from app.skill_intelligence.learning_path import LearningPathDraft

_VALID_TRANSITIONS = {
    "active": {"paused", "completed", "cancelled"},
    "paused": {"active", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def create_from_draft(
    db: Session,
    user_id: int,
    draft: LearningPathDraft,
    title: str,
    target_job_id: int | None = None,
    target_date: date | None = None,
    weekly_goal_hours: float | None = None,
) -> LearningPlan:
    if not draft.steps:
        raise HTTPException(400, "Nothing to build a plan from — no skill gap found for this candidate/job")

    plan = LearningPlan(
        user_id=user_id,
        title=title,
        target_skill_id=draft.steps[-1].skill.id if draft.steps else None,
        target_job_id=target_job_id,
        status="active",
        target_date=target_date,
        weekly_goal_hours=weekly_goal_hours,
    )
    db.add(plan)
    db.flush()

    for i, step in enumerate(draft.steps):
        db.add(
            LearningPlanModule(
                plan_id=plan.id,
                skill_id=step.skill.id,
                resource_id=step.resource.id if step.resource else None,
                order_index=i,
                status="not_started",
            )
        )
    db.commit()
    db.refresh(plan)
    return plan


def _own_plan_or_404(db: Session, plan_id: int, user_id: int) -> LearningPlan:
    plan = db.get(LearningPlan, plan_id)
    if not plan or plan.user_id != user_id:
        raise HTTPException(404, "Learning plan not found")
    return plan


def set_status(db: Session, plan_id: int, user_id: int, new_status: str) -> LearningPlan:
    plan = _own_plan_or_404(db, plan_id, user_id)
    if new_status not in _VALID_TRANSITIONS.get(plan.status, set()):
        raise HTTPException(400, f"Cannot move plan from '{plan.status}' to '{new_status}'")
    plan.status = new_status
    db.commit()
    db.refresh(plan)
    return plan


def set_target_date(db: Session, plan_id: int, user_id: int, target_date: date | None) -> LearningPlan:
    plan = _own_plan_or_404(db, plan_id, user_id)
    plan.target_date = target_date
    db.commit()
    db.refresh(plan)
    return plan


def set_weekly_goal(db: Session, plan_id: int, user_id: int, weekly_goal_hours: float | None) -> LearningPlan:
    plan = _own_plan_or_404(db, plan_id, user_id)
    plan.weekly_goal_hours = weekly_goal_hours
    db.commit()
    db.refresh(plan)
    return plan


def _own_module_or_404(db: Session, plan_id: int, module_id: int, user_id: int) -> LearningPlanModule:
    _own_plan_or_404(db, plan_id, user_id)
    module = db.get(LearningPlanModule, module_id)
    if not module or module.plan_id != plan_id:
        raise HTTPException(404, "Module not found on this plan")
    return module


def complete_module(db: Session, plan_id: int, module_id: int, user_id: int, time_spent_minutes: int = 0) -> LearningPlanModule:
    module = _own_module_or_404(db, plan_id, module_id, user_id)
    module.status = "completed"
    module.time_spent_minutes += max(0, time_spent_minutes)
    module.completed_at = datetime.utcnow()
    if module.started_at is None:
        module.started_at = module.completed_at
    _record_activity(db, module.plan_id)
    db.commit()
    db.refresh(module)
    return module


def _record_activity(db: Session, plan_id: int) -> None:
    """Update the plan's learning streak for "today". Consecutive
    calendar days with any logged activity (start/log-time/complete)
    extend the streak; a gap of more than one day resets it to 1;
    multiple activities on the same day don't double-count."""

    plan = db.get(LearningPlan, plan_id)
    if not plan:
        return
    today = date.today()
    if plan.last_activity_date == today:
        return  # already counted today
    if plan.last_activity_date is not None and (today - plan.last_activity_date).days == 1:
        plan.current_streak_days += 1
    else:
        plan.current_streak_days = 1
    plan.longest_streak_days = max(plan.longest_streak_days, plan.current_streak_days)
    plan.last_activity_date = today


def start_module(db: Session, plan_id: int, module_id: int, user_id: int) -> LearningPlanModule:
    module = _own_module_or_404(db, plan_id, module_id, user_id)
    if module.status == "not_started":
        module.status = "in_progress"
        module.started_at = datetime.utcnow()
        _record_activity(db, module.plan_id)
    db.commit()
    db.refresh(module)
    return module


def skip_module(db: Session, plan_id: int, module_id: int, user_id: int) -> LearningPlanModule:
    module = _own_module_or_404(db, plan_id, module_id, user_id)
    module.status = "skipped"
    db.commit()
    db.refresh(module)
    return module


def log_time(db: Session, plan_id: int, module_id: int, user_id: int, minutes: int) -> LearningPlanModule:
    module = _own_module_or_404(db, plan_id, module_id, user_id)
    module.time_spent_minutes += max(0, minutes)
    if module.status == "not_started":
        module.status = "in_progress"
        module.started_at = datetime.utcnow()
    _record_activity(db, module.plan_id)
    db.commit()
    db.refresh(module)
    return module


def reorder(db: Session, plan_id: int, user_id: int, ordered_module_ids: list[int]) -> list[LearningPlanModule]:
    _own_plan_or_404(db, plan_id, user_id)
    modules = {m.id: m for m in db.scalars(select(LearningPlanModule).where(LearningPlanModule.plan_id == plan_id))}
    if set(ordered_module_ids) != set(modules.keys()):
        raise HTTPException(400, "ordered_module_ids must include every module on this plan exactly once")
    # Two-pass update avoids the (plan_id, order_index) unique constraint
    # colliding on an intermediate state.
    for m in modules.values():
        m.order_index += len(modules)
    db.flush()
    for i, mid in enumerate(ordered_module_ids):
        modules[mid].order_index = i
    db.commit()
    return sorted(modules.values(), key=lambda m: m.order_index)


@dataclass
class PlanProgress:
    plan_id: int
    total_modules: int
    completed: int
    in_progress: int
    skipped: int
    not_started: int
    completion_percentage: float
    total_time_spent_minutes: int
    current_streak_days: int
    longest_streak_days: int


def progress(db: Session, plan_id: int, user_id: int) -> PlanProgress:
    plan = _own_plan_or_404(db, plan_id, user_id)
    modules = list(db.scalars(select(LearningPlanModule).where(LearningPlanModule.plan_id == plan_id)))
    total = len(modules)
    completed = sum(1 for m in modules if m.status == "completed")
    in_progress = sum(1 for m in modules if m.status == "in_progress")
    skipped = sum(1 for m in modules if m.status == "skipped")
    not_started = sum(1 for m in modules if m.status == "not_started")
    pct = round(100 * completed / total, 1) if total else 0.0
    time_spent = sum(m.time_spent_minutes for m in modules)
    return PlanProgress(
        plan_id=plan_id,
        total_modules=total,
        completed=completed,
        in_progress=in_progress,
        skipped=skipped,
        not_started=not_started,
        completion_percentage=pct,
        total_time_spent_minutes=time_spent,
        current_streak_days=plan.current_streak_days,
        longest_streak_days=plan.longest_streak_days,
    )
