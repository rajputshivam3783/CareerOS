"""V17.2 — OTP hardening beyond what already existed.

Hashing (``code_hash``), expiration (``expires_at``), single-use
(``consumed``), and constant-time comparison were already in place
before this pass (see app/api/auth.py's ``_hash``/``_issue``, unchanged
here). What's new:

- **Max attempts** — a code accepts a bounded number of wrong guesses
  (``EmailVerification.attempts``) before it's invalidated, independent
  of the per-IP ``verify-email`` rate limit (which an attacker
  distributing guesses across IPs wouldn't trip).
- **Resend cooldown** — a minimum gap between resend requests for the
  same purpose, so "resend" can't be used to spam a mailbox or as a
  side-channel to keep re-arming attempts.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.domain import EmailVerification


def is_attempts_exhausted(row: EmailVerification) -> bool:
    return row.attempts >= settings.otp_max_attempts


def record_wrong_attempt(db: Session, row: EmailVerification) -> None:
    row.attempts += 1
    if is_attempts_exhausted(row):
        # Invalidate outright rather than leaving it merely "used up" —
        # a subsequent /resend-otp is required to try again at all.
        row.consumed = True


def resend_cooldown_remaining_seconds(
    db: Session, user_id: int, purpose: str, cooldown_seconds: int | None = None
) -> int:
    """0 if a resend is allowed right now, otherwise how many seconds
    the caller still has to wait. ``cooldown_seconds`` (V25.6) lets a caller use a
    different budget than the email-verification default."""
    from sqlalchemy import select

    latest = db.scalar(
        select(EmailVerification)
        .where(EmailVerification.user_id == user_id, EmailVerification.purpose == purpose)
        .order_by(EmailVerification.id.desc())
    )
    if not latest:
        return 0
    elapsed = (datetime.utcnow() - latest.created_at).total_seconds()
    remaining = (cooldown_seconds if cooldown_seconds is not None else settings.otp_resend_cooldown_seconds) - elapsed
    return max(0, int(remaining))
