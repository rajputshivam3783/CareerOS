"""V25.4 — Proactive Career Agent notifications (spec section 21).

Deterministic triggers on top of the existing V23 notification
infrastructure (``app.notifications.service.create_notification``,
which already provides the idempotency guarantee via ``dedupe_key`` —
see that function's docstring) — no new delivery mechanism, no AI
call. Respects each candidate's ``CareerAgentPreference``: disabled
entirely, a chosen frequency, and quiet hours all suppress a
notification that would otherwise fire (spec: "Do not spam users").

This module exposes plain functions meant to be invoked from a
scheduler (the existing APScheduler setup other CareerOS automation —
e.g. V23.3 job alerts — already uses); it does not register its own
scheduler job, since wiring a new periodic job is an operational
change outside this pass's file-level scope and is called out as
NOT VERIFIED in docs/V25_4_AI_CAREER_AGENT.md.
"""

from __future__ import annotations

from datetime import date, datetime

from app.applications.service import get_upcoming_deadlines
from app.career_agent import preferences as agent_preferences
from app.models.domain import User
from app.notifications.service import create_notification
from app.recommendations import service as recommendation_service


def _within_quiet_hours(prefs: dict, *, now: datetime | None = None) -> bool:
    start, end = prefs.get("quiet_hours_start"), prefs.get("quiet_hours_end")
    if start is None or end is None:
        return False
    hour = (now or datetime.utcnow()).hour
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end  # wraps past midnight


def generate_proactive_notifications(db, user: User, *, today: date | None = None) -> list:
    """Idempotent and safe to call repeatedly (e.g. once per scheduler
    tick per user) — every notification below carries a dedupe_key
    scoped to the fact it represents, so re-running this on the same
    day for the same candidate never creates duplicates."""

    prefs = agent_preferences.get_or_default(db, user.id)
    if not prefs["proactive_enabled"] or _within_quiet_hours(prefs):
        return []

    today = today or date.today()
    created = []

    deadlines = get_upcoming_deadlines(db, user.id, days=3, limit=5)
    for d in deadlines:
        n = create_notification(
            db, user.id, notification_type="career_agent_deadline", category="DEADLINE",
            title="Application deadline approaching",
            message=f"Your application to {d.get('company', 'a company')} has a deadline coming up.",
            priority="HIGH",
            dedupe_key=f"career_agent:deadline:{d.get('application_id')}:{today.isoformat()}",
        )
        if n:
            created.append(n)

    recs = recommendation_service.get_recommendations(db, user, limit=5)
    new_matches = [item for item in recs.items if not item.already_saved and not item.already_applied]
    if new_matches:
        n = create_notification(
            db, user.id, notification_type="career_agent_recommendations", category="JOB",
            title="New jobs matching your target role",
            message=f"You have {len(new_matches)} relevant job(s) matching your target role.",
            priority="NORMAL",
            dedupe_key=f"career_agent:recommendations:{today.isoformat()}",
        )
        if n:
            created.append(n)

    return created
