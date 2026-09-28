"""V25.4 — Daily/weekly Career Brief (spec section 22).

Purely deterministic composition of already-computed CareerOS data —
no AI call, matching spec section 25's "do not call an LLM for
deterministic operations." If nothing meaningful changed, the brief
says so explicitly rather than manufacturing content to fill the
space (spec section 22: "If nothing important changed: say so instead
of generating noise").
"""

from __future__ import annotations


from sqlalchemy import select

from app.applications.service import get_upcoming_deadlines
from app.career_copilot import context_engine
from app.models.domain import Application, ApplicationTask, User
from app.notifications.service import list_notifications
from app.recommendations import service as recommendation_service


def build_brief(db, user: User) -> dict:
    context = context_engine.build(db, user.id)

    recs = recommendation_service.get_recommendations(db, user, limit=5)
    new_jobs = [
        {"job_id": item.job_id, "title": item.title, "organization": item.organization}
        for item in recs.items
        if not item.already_saved and not item.already_applied
    ][:5]

    deadlines = get_upcoming_deadlines(db, user.id, days=14, limit=5)

    pending_tasks = db.scalars(
        select(ApplicationTask)
        .join(Application, Application.id == ApplicationTask.application_id)
        .where(Application.user_id == user.id, ApplicationTask.completed.is_(False))
        .order_by(ApplicationTask.due_at.asc().nulls_last())
        .limit(5)
    ).all()

    notifications, _ = list_notifications(db, user.id, unread_only=True, limit=5)

    sections = {
        "new_relevant_jobs": new_jobs,
        "upcoming_deadlines": deadlines,
        "pending_tasks": [
            {"id": t.id, "title": t.title, "due_at": t.due_at.isoformat() if t.due_at else None}
            for t in pending_tasks
        ],
        "unread_notifications": [{"id": n.id, "title": n.title} for n in notifications],
        "skill_progress": context.skill_intelligence,
    }

    has_content = any(bool(v) for k, v in sections.items() if k != "skill_progress")
    return {
        "has_meaningful_update": has_content,
        "summary": "Here's what's new." if has_content else "Nothing new to report today — you're all caught up.",
        **sections,
    }
