"""V23.4 — Communication Center, Interview & Deadline Reminders API.

Routes exactly as spec section 20, under /api/v1 like every other
router. Every route resolves the acting user from ``current_user``
(verified JWT) and every aggregator/reminder call is scoped by that
user's own id — see app.communication.aggregator and
app.communication.reminders' own module docstrings for the ownership/
idempotency guarantees underneath.

``POST /communication/reminders/run`` is the one exception (spec
section 20: "Only expose manual reminder-run endpoint if it is safely
restricted... Do not allow candidates to trigger unlimited expensive
processing") — it reuses the exact same shared-admin-key/admin-JWT
``guard`` dependency every other manual-run endpoint in this codebase
already requires (app.api.admin.guard, also used by
POST /admin/automation/run/{job_id}), rather than inventing a second
admin-auth mechanism or exposing it to ordinary candidates at all.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.admin import guard
from app.communication import aggregator, reminders
from app.core.security import current_user
from app.db.session import get_db
from app.models.domain import NotificationReminder

router = APIRouter(prefix="/communication", tags=["V23.4 Communication Center"])


@router.get("/summary")
def get_summary(u=Depends(current_user), db: Session = Depends(get_db)):
    return aggregator.get_summary(db, u.id)


@router.get("/actions")
def get_actions(
    limit: int = Query(default=aggregator.ACTIONS_LIMIT, ge=1, le=100),
    u=Depends(current_user), db: Session = Depends(get_db),
):
    return {"actions": aggregator.get_action_required(db, u.id, limit=limit)}


@router.get("/upcoming")
def get_upcoming(
    days: int = Query(default=aggregator.UPCOMING_HORIZON_DAYS, ge=1, le=60),
    u=Depends(current_user), db: Session = Depends(get_db),
):
    return aggregator.get_upcoming(db, u.id, days=days)


@router.get("/reminders")
def list_reminders(
    status: str | None = Query(default=None, description="PENDING / DELAYED / SENT / FAILED / SKIPPED"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    u=Depends(current_user), db: Session = Depends(get_db),
):
    """A candidate's own reminder history — read-only, ownership-scoped
    by the verified JWT (never a caller-supplied user_id — spec
    section 26 IDOR protection)."""
    stmt = select(NotificationReminder).where(NotificationReminder.user_id == u.id)
    if status:
        stmt = stmt.where(NotificationReminder.status == status.upper())
    stmt = stmt.order_by(NotificationReminder.scheduled_for.desc()).limit(limit).offset(offset)
    rows = db.scalars(stmt).all()
    return {
        "items": [
            {
                "id": r.id, "source_type": r.source_type, "source_id": r.source_id,
                "reminder_type": r.reminder_type, "scheduled_for": r.scheduled_for.isoformat(),
                "status": r.status, "priority": r.priority,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            }
            for r in rows
        ],
    }


@router.post("/reminders/run", dependencies=[Depends(guard)])
def run_reminders_now():
    """Admin-only manual run (see module docstring) — the same
    reminder scan the scheduler calls on its own interval
    (app/scheduler.py's careeros_communication_reminders job), reused
    verbatim so a manual run behaves identically to a scheduled one."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        return reminders.run_due_reminders(db)
    finally:
        db.close()
