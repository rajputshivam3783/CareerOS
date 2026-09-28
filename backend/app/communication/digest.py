"""V23.4 — the optional daily communication digest email.

Spec section 12: one email per user per day, only when (a) the user
has opted in (``UserNotificationPreference.digest_enabled``) and (b)
there is meaningful content — never an empty digest. Built entirely
from ``app.communication.aggregator`` (no separate query path, so the
digest can never disagree with what the Communication Center itself
shows) and delivered through the existing V23.2 EmailService/
DAILY_CAREER_DIGEST template (see app.email.templates).

ONE-PER-DAY (spec section 25 — "prevent duplicate daily digests"):
``queue_email``'s existing ``dedupe_key`` mechanism is reused exactly
as V23.3's job-alert digests already do — the key includes today's
UTC date, so re-running this on the same day is a guaranteed no-op at
the database layer (EmailMessage's UNIQUE(user_id, dedupe_key)), not
just an application-level check. Run on a schedule
(app/scheduler.py's ``careeros_daily_digest`` job), never inside a
request.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.communication import aggregator
from app.email import service as email_service
from app.email.templates import DIGEST_TOP_N
from app.models.domain import EmailMessage, User, UserNotificationPreference

logger = logging.getLogger("careeros.communication.digest")


def _digest_items(db: Session, user_id: int) -> list[dict]:
    """Reuses the exact same action list the Action Required section
    shows (app.communication.aggregator.get_action_required) — the
    digest is a restatement of that list by email, never a second
    opinion about what matters."""
    actions = aggregator.get_action_required(db, user_id, limit=DIGEST_TOP_N * 3)
    items = []
    for action in actions:
        items.append({"label": action["source"], "title": action["title"], "detail": action["reason"]})
    return items


def send_digest_for_user(db: Session, user_id: int, *, today: date | None = None) -> bool:
    """Queues one digest email for this user if, and only if, they've
    opted in and there's something worth sending. Returns whether an
    email was actually queued (False is a normal, expected outcome —
    not an error)."""
    today = today or date.today()
    pref = db.get(UserNotificationPreference, user_id)
    if pref is None or not pref.digest_enabled or not pref.email_enabled:
        return False

    user = db.get(User, user_id)
    if user is None or not user.email:
        return False

    dedupe_key = f"daily_digest:{user_id}:{today.isoformat()}"
    # queue_email's own dedupe_key handling returns the *existing* row
    # (not None) for a repeat call with the same key (see
    # app.email.service.queue_email's docstring) — that's correct for
    # "never actually double-send," but this function's own return
    # value is "did I just queue a *new* one," so the check happens
    # here, before calling it, rather than relying on that return value.
    already_queued_today = db.scalar(select(EmailMessage.id).where(EmailMessage.user_id == user_id, EmailMessage.dedupe_key == dedupe_key))
    if already_queued_today is not None:
        return False

    items = _digest_items(db, user_id)
    if not items:
        return False  # spec section 12: "Do NOT send empty emails."

    top = items[:DIGEST_TOP_N]
    remaining = len(items) - len(top)

    variables: dict = {
        "user_name": user.full_name,
        "item_count": str(len(items)),
        "action_url": "/communication",
    }
    for i in range(1, DIGEST_TOP_N + 1):
        item = top[i - 1] if i <= len(top) else None
        variables[f"item_{i}_label"] = item["label"] if item else ""
        variables[f"item_{i}_title"] = item["title"] if item else ""
        variables[f"item_{i}_detail"] = item["detail"] if item else ""
    variables["more_count_text"] = f"and {remaining} more item(s) — open the Communication Center to see everything." if remaining > 0 else ""

    email = email_service.queue_email(
        db, user_id=user_id, recipient=user.email, template_key="DAILY_CAREER_DIGEST",
        variables=variables, category="DIGEST", dedupe_key=dedupe_key,
    )
    return email is not None


def run_daily_digest(db: Session) -> dict:
    """Scheduled entry point: every user with digest_enabled gets
    evaluated once. A failure for one user is logged and skipped
    rather than aborting the whole run (spec section 24)."""
    user_ids = db.scalars(
        select(UserNotificationPreference.user_id).where(UserNotificationPreference.digest_enabled.is_(True))
    ).all()
    sent = skipped = failed = 0
    for user_id in user_ids:
        try:
            if send_digest_for_user(db, user_id):
                sent += 1
            else:
                skipped += 1
        except Exception:  # noqa: BLE001 — one user's failure must not abort the run
            logger.error("Daily digest failed for user_id=%s", user_id, exc_info=True)
            failed += 1
    return {"eligible_users": len(user_ids), "sent": sent, "skipped_no_content_or_optout": skipped, "failed": failed}
