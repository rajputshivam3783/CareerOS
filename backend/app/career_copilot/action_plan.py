"""Deterministic, persisted action plan: Today / This Week / This
Month / Next 3 Months, prioritized by deadline proximity, skill gaps,
applications, and stated career goals. No AI call.

Persisted as ``CareerActionItem`` rows (not recomputed fresh on every
request) specifically so a candidate marking an item done/dismissed
keeps that status across regenerations — ``generate_and_persist``
upserts by a stable ``dedupe_key`` and never resets an existing item's
``status``.
"""

from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.career_copilot import context_engine, roadmap
from app.models.domain import CareerActionItem


def _dedupe_key(bucket: str, title: str, related_job_id: int | None) -> str:
    raw = f"{bucket}\u241f{title}\u241f{related_job_id or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _generate_items(db: Session, user_id: int) -> list[dict]:
    context = context_engine.build(db, user_id)
    items: list[dict] = []
    today = date.today()

    for app_ in context.applications:
        if not app_["next_deadline"]:
            continue
        deadline = date.fromisoformat(app_["next_deadline"])
        days_left = (deadline - today).days
        if days_left < 0:
            continue
        if days_left <= 1:
            bucket, priority = "today", "high"
        elif days_left <= 7:
            bucket, priority = "this_week", "high" if days_left <= 3 else "medium"
        elif days_left <= 30:
            bucket, priority = "this_month", "medium"
        else:
            continue
        items.append({
            "bucket": bucket, "priority": priority, "source": "deadline",
            "title": f"Follow up on your application to {app_['role']} at {app_['company']}",
            "reason": f"Deadline on {app_['next_deadline']} ({days_left} day(s) away), status: {app_['status']}",
            "related_job_id": app_["job_id"],
        })

    if not context.resume_summary:
        items.append({
            "bucket": "today", "priority": "high", "source": "recommendation",
            "title": "Upload your resume",
            "reason": "No resume on file — Resume Intelligence, job matching, and skill-gap analysis all need one to give you specific guidance.",
            "related_job_id": None,
        })
    elif context.resume_summary.get("overall_score") is not None and context.resume_summary["overall_score"] < 50:
        items.append({
            "bucket": "this_week", "priority": "medium", "source": "recommendation",
            "title": "Improve your resume score",
            "reason": f"Current resume quality score is {context.resume_summary['overall_score']}/100 — see GET /resume-ai/recommendations for specific fixes.",
            "related_job_id": None,
        })

    try:
        plan = roadmap.build(db, user_id)
        for skill_task in plan.get("learning_priorities", [])[:3]:
            if skill_task.startswith("Learn "):
                items.append({
                    "bucket": "this_month", "priority": "medium", "source": "skill_gap",
                    "title": skill_task,
                    "reason": f"Identified as a gap toward {plan.get('target_role', 'your target role')}.",
                    "related_job_id": plan.get("grounded_in", {}).get("used_target_job_id"),
                })
        for project_task in plan.get("projects", [])[:1]:
            items.append({
                "bucket": "next_3_months", "priority": "low", "source": "skill_gap",
                "title": project_task,
                "reason": "Strengthens your profile for the skill gaps identified in your roadmap.",
                "related_job_id": None,
            })
    except Exception:
        pass  # roadmap needs at least a profile/resume; skip this section if nothing to ground it in

    if not context.applications and context.saved_jobs:
        items.append({
            "bucket": "this_week", "priority": "medium", "source": "recommendation",
            "title": f"Consider applying to a saved job: {context.saved_jobs[0]['title']}",
            "reason": "You've saved jobs but haven't tracked any applications yet.",
            "related_job_id": context.saved_jobs[0]["id"],
        })

    if context.preferences and context.preferences.get("career_goal"):
        items.append({
            "bucket": "next_3_months", "priority": "low", "source": "career_goal",
            "title": "Review progress toward your stated career goal",
            "reason": f"You stated: {context.preferences['career_goal']}",
            "related_job_id": None,
        })

    return items


def generate_and_persist(db: Session, user_id: int) -> list[CareerActionItem]:
    generated = _generate_items(db, user_id)
    existing = {row.dedupe_key: row for row in db.execute(select(CareerActionItem).where(CareerActionItem.user_id == user_id)).scalars()}

    result = []
    for item in generated:
        key = _dedupe_key(item["bucket"], item["title"], item["related_job_id"])
        row = existing.get(key)
        if row:
            row.reason = item["reason"]
            row.priority = item["priority"]
            import datetime as _dt

            row.regenerated_at = _dt.datetime.utcnow()
        else:
            row = CareerActionItem(user_id=user_id, dedupe_key=key, **item)
            db.add(row)
        result.append(row)

    db.commit()
    for row in result:
        db.refresh(row)
    return result


def list_items(db: Session, user_id: int, *, status: str | None = None) -> list[CareerActionItem]:
    query = select(CareerActionItem).where(CareerActionItem.user_id == user_id)
    if status:
        query = query.where(CareerActionItem.status == status)
    return list(db.execute(query.order_by(CareerActionItem.bucket, CareerActionItem.priority)).scalars())


def set_status(db: Session, item: CareerActionItem, status: str) -> CareerActionItem:
    item.status = status
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
