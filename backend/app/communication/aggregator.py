"""V23.4 — Communication Center read-side aggregation.

Every function here is read-only and reads directly from tables that
already exist (Application/ApplicationInterview/ApplicationTask — V22;
Notification — V23.1; JobAlertDelivery — V23.3). Nothing here creates
or stores a second copy of any of that data (spec section 3/10/11:
"Do NOT create duplicate storage systems").

Performance (spec section 27): every query below is scoped by
``user_id`` first (indexed on every table involved) and bounded by a
date horizon or ``limit`` — never "every application"/"every
interview" unbounded. See each function's own note.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications import service as application_service
from app.applications.ai.signals import compute_signals
from app.applications.status import TERMINAL_STATUSES
from app.communication import priority as priority_engine
from app.models.domain import (
    Application, ApplicationInterview, ApplicationTask, JobAlertDelivery,
)
from app.notifications import service as notification_service

# How far ahead "upcoming" looks, and how recent a job match counts as
# "new" — named constants so the horizon is documented in one place
# rather than a scattered magic number per query.
UPCOMING_HORIZON_DAYS = 14
ACTION_HORIZON_DAYS = 7
NEW_MATCH_WINDOW_DAYS = 7
ACTIONS_LIMIT = 50


@dataclass
class ActionItem:
    title: str
    reason: str
    priority: str
    due_date: str | None
    source: str  # INTERVIEW / DEADLINE / TASK / APPLICATION / JOB
    action_url: str
    kind: str  # a stable machine key, e.g. "prepare_for_interview"

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "reason": self.reason,
            "priority": self.priority,
            "due_date": self.due_date,
            "source": self.source,
            "action_url": self.action_url,
            "kind": self.kind,
        }


def _active_applications(db: Session, user_id: int) -> list[Application]:
    """Non-terminal applications for this user — the base population
    every action-required/health check below draws from. Bounded to
    non-terminal only (spec's own "actionable" framing; a closed
    application never needs a follow-up/interview-prep nudge)."""
    return db.scalars(
        select(Application).where(Application.user_id == user_id, Application.status.not_in(TERMINAL_STATUSES))
    ).all()


def _upcoming_interviews(db: Session, user_id: int, *, horizon_days: int) -> list[tuple[ApplicationInterview, Application]]:
    now = datetime.utcnow()
    horizon = now + timedelta(days=horizon_days)
    rows = db.execute(
        select(ApplicationInterview, Application)
        .join(Application, Application.id == ApplicationInterview.application_id)
        .where(
            Application.user_id == user_id,
            ApplicationInterview.result == "SCHEDULED",
            ApplicationInterview.scheduled_at.is_not(None),
            ApplicationInterview.scheduled_at >= now,
            ApplicationInterview.scheduled_at <= horizon,
        )
        .order_by(ApplicationInterview.scheduled_at.asc())
    ).all()
    return [(iv, app) for iv, app in rows]


def _overdue_tasks(db: Session, user_id: int) -> list[tuple[ApplicationTask, Application]]:
    now = datetime.utcnow()
    rows = db.execute(
        select(ApplicationTask, Application)
        .join(Application, Application.id == ApplicationTask.application_id)
        .where(
            Application.user_id == user_id,
            ApplicationTask.completed.is_(False),
            ApplicationTask.due_at.is_not(None),
            ApplicationTask.due_at < now,
        )
        .order_by(ApplicationTask.due_at.asc())
    ).all()
    return [(t, app) for t, app in rows]


def _upcoming_tasks(db: Session, user_id: int, *, horizon_days: int) -> list[tuple[ApplicationTask, Application]]:
    now = datetime.utcnow()
    horizon = now + timedelta(days=horizon_days)
    rows = db.execute(
        select(ApplicationTask, Application)
        .join(Application, Application.id == ApplicationTask.application_id)
        .where(
            Application.user_id == user_id,
            ApplicationTask.completed.is_(False),
            ApplicationTask.due_at.is_not(None),
            ApplicationTask.due_at >= now,
            ApplicationTask.due_at <= horizon,
        )
        .order_by(ApplicationTask.due_at.asc())
    ).all()
    return [(t, app) for t, app in rows]


def _recent_job_matches(db: Session, user_id: int, *, window_days: int) -> list[JobAlertDelivery]:
    since = datetime.utcnow() - timedelta(days=window_days)
    return db.scalars(
        select(JobAlertDelivery)
        .where(
            JobAlertDelivery.user_id == user_id,
            JobAlertDelivery.channel == "IN_APP",
            JobAlertDelivery.delivered_at >= since,
        )
        .order_by(JobAlertDelivery.delivered_at.desc())
    ).all()


def get_summary(db: Session, user_id: int) -> dict:
    """GET /communication/summary — spec section 3. Every number is a
    real, bounded query against existing tables; nothing here is a
    placeholder/demo value."""
    unread_notifications = notification_service.get_unread_count(db, user_id)
    upcoming_interviews = len(_upcoming_interviews(db, user_id, horizon_days=UPCOMING_HORIZON_DAYS))
    deadlines = application_service.get_upcoming_deadlines(db, user_id, days=UPCOMING_HORIZON_DAYS)
    upcoming_deadlines = len([d for d in deadlines if d["urgency"] != "overdue"])
    overdue_deadlines = len([d for d in deadlines if d["urgency"] == "overdue"])
    overdue_tasks = len(_overdue_tasks(db, user_id))

    needing_attention = 0
    for application in _active_applications(db, user_id):
        signals = compute_signals(db, application)
        if signals.priority in ("High", "Critical") or signals.follow_up_timing in ("Follow up today", "Follow up urgently"):
            needing_attention += 1

    new_job_matches = len({d.job_id for d in _recent_job_matches(db, user_id, window_days=NEW_MATCH_WINDOW_DAYS)})

    return {
        "unread_notifications": unread_notifications,
        "upcoming_interviews": upcoming_interviews,
        "upcoming_deadlines": upcoming_deadlines,
        "overdue_deadlines": overdue_deadlines,
        "overdue_tasks": overdue_tasks,
        "applications_needing_attention": needing_attention,
        "new_job_matches": new_job_matches,
    }


def get_action_required(db: Session, user_id: int, *, limit: int = ACTIONS_LIMIT) -> list[dict]:
    """GET /communication/actions — spec section 4. Every action below
    traces back to a real row the user owns; nothing is fabricated."""
    actions: list[ActionItem] = []
    today = date.today()

    # Overdue tasks.
    for task, app in _overdue_tasks(db, user_id):
        days_over = (today - task.due_at.date()).days
        result = priority_engine.score_by_days_until(-days_over)
        actions.append(ActionItem(
            title=f'Complete overdue task: "{task.title}"',
            reason=f"This task was due {days_over} day(s) ago on your application to {app.company}.",
            priority=result.level,
            due_date=task.due_at.date().isoformat(),
            source="TASK",
            action_url=f"/applications/{app.id}",
            kind="complete_overdue_task",
        ))

    # Tasks due soon (within ACTION_HORIZON_DAYS) — distinct from overdue above.
    for task, app in _upcoming_tasks(db, user_id, horizon_days=ACTION_HORIZON_DAYS):
        days_until = (task.due_at.date() - today).days
        result = priority_engine.score_by_days_until(days_until)
        if result.level == "LOW":
            continue
        actions.append(ActionItem(
            title=f'Upcoming task: "{task.title}"',
            reason=f"Due in {days_until} day(s) on your application to {app.company}.",
            priority=result.level,
            due_date=task.due_at.date().isoformat(),
            source="TASK",
            action_url=f"/applications/{app.id}",
            kind="upcoming_task",
        ))

    # Upcoming interviews.
    for interview, app in _upcoming_interviews(db, user_id, horizon_days=ACTION_HORIZON_DAYS):
        days_until = (interview.scheduled_at.date() - today).days
        result = priority_engine.score_by_days_until(days_until)
        label = interview.round_name or f"{interview.interview_type.title()} interview"
        actions.append(ActionItem(
            title=f"Prepare for interview: {label}",
            reason=f"Scheduled {interview.scheduled_at.strftime('%b %d, %Y %H:%M UTC')} for {app.company}.",
            priority=result.level,
            due_date=interview.scheduled_at.date().isoformat(),
            source="INTERVIEW",
            action_url=f"/applications/{app.id}",
            kind="prepare_for_interview",
        ))

    # Approaching / overdue application deadlines, and application-level
    # signals (assessment/follow-up) from the existing V22.4 engine.
    for application in _active_applications(db, user_id):
        if application.deadline is not None:
            days_until = (application.deadline - today).days
            result = priority_engine.score_by_days_until(days_until)
            if result.level != "LOW":
                verb = "Submit application" if application.status in ("SAVED", "PLANNING_TO_APPLY") else "Review approaching deadline"
                actions.append(ActionItem(
                    title=f"{verb}: {application.job_title or application.role} at {application.company}",
                    reason=result.reason,
                    priority=result.level,
                    due_date=application.deadline.isoformat(),
                    source="APPLICATION",
                    action_url=f"/applications/{application.id}",
                    kind="review_deadline",
                ))

        signals = compute_signals(db, application)
        if signals.next_action.action == "Complete assessment":
            actions.append(ActionItem(
                title=f"Complete assessment: {application.job_title or application.role}",
                reason=signals.next_action.reason,
                priority=priority_engine.from_application_priority(signals.priority).level,
                due_date=None,
                source="APPLICATION",
                action_url=f"/applications/{application.id}",
                kind="complete_assessment",
            ))
        elif signals.follow_up_timing in ("Follow up today", "Follow up urgently"):
            actions.append(ActionItem(
                title=f"Follow up with recruiter: {application.company}",
                reason=signals.follow_up_reason,
                priority="URGENT" if signals.follow_up_timing == "Follow up urgently" else "HIGH",
                due_date=None,
                source="APPLICATION",
                action_url=f"/applications/{application.id}",
                kind="follow_up_with_recruiter",
            ))

    # High-relevance recent job matches.
    for delivery in _recent_job_matches(db, user_id, window_days=NEW_MATCH_WINDOW_DAYS):
        if delivery.relevance_score is not None and delivery.relevance_score >= 80:
            actions.append(ActionItem(
                title="Review high-priority job match",
                reason=f"A new job scored {delivery.relevance_score}/100 relevance against your alert.",
                priority="HIGH",
                due_date=None,
                source="JOB",
                action_url=f"/jobs/{delivery.job_id}",
                kind="review_job_match",
            ))

    order = {"URGENT": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
    actions.sort(key=lambda a: (order.get(a.priority, 9), a.due_date or "9999-99-99"))
    return [a.as_dict() for a in actions[:limit]]


def get_upcoming(db: Session, user_id: int, *, days: int = UPCOMING_HORIZON_DAYS) -> dict:
    """GET /communication/upcoming — spec section 19: a unified
    TODAY/TOMORROW/THIS_WEEK/LATER timeline built from real dates."""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    week_end = today + timedelta(days=7)

    items: list[dict] = []
    for interview, app in _upcoming_interviews(db, user_id, horizon_days=days):
        items.append({
            "type": "INTERVIEW",
            "title": f"Interview — {app.job_title or app.role}",
            "date": interview.scheduled_at.date().isoformat(),
            "time": interview.scheduled_at.strftime("%H:%M UTC"),
            "action_url": f"/applications/{app.id}",
        })
    for task, app in _upcoming_tasks(db, user_id, horizon_days=days):
        items.append({
            "type": "TASK",
            "title": f"Task — {task.title}",
            "date": task.due_at.date().isoformat(),
            "time": None,
            "action_url": f"/applications/{app.id}",
        })
    for d in application_service.get_upcoming_deadlines(db, user_id, days=days):
        if d["urgency"] == "overdue":
            continue
        items.append({
            "type": "DEADLINE",
            "title": f"Application deadline — {d['job_title']}",
            "date": d["deadline"],
            "time": None,
            "action_url": f"/applications/{d['application_id']}",
        })

    buckets: dict[str, list[dict]] = {"TODAY": [], "TOMORROW": [], "THIS_WEEK": [], "LATER": []}
    for item in items:
        item_date = date.fromisoformat(item["date"])
        if item_date == today:
            buckets["TODAY"].append(item)
        elif item_date == tomorrow:
            buckets["TOMORROW"].append(item)
        elif item_date <= week_end:
            buckets["THIS_WEEK"].append(item)
        else:
            buckets["LATER"].append(item)

    for bucket in buckets.values():
        bucket.sort(key=lambda i: (i["date"], i["time"] or ""))

    return buckets
