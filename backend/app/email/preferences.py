"""V23.2 — email preference check.

The ONE function that decides "should this category's email actually
go out for this user." Security-critical transactional email
(verification, password reset) NEVER calls this — see
app.email.service.send_transactional_email, which sends
unconditionally, matching spec section 11's "must not be disabled
through ordinary notification preferences."
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.domain import UserNotificationPreference

_CATEGORY_COLUMN = {
    "JOB": "email_job",
    "APPLICATION": "email_application",
    "INTERVIEW": "email_interview",
    "DEADLINE": "email_deadline",
    "RECRUITER": "email_recruiter",
    "AI": "email_ai",
    "SYSTEM": "email_system",
    # V23.4 — daily communication digest. Deliberately its own column
    # (digest_enabled, default False) rather than reusing SYSTEM/email_system
    # — see UserNotificationPreference.digest_enabled's docstring for why
    # this one flag defaults off while every other one here defaults on.
    "DIGEST": "digest_enabled",
}


def should_send_email(db: Session, user_id: int, category: str | None) -> bool:
    """True unless the user has explicitly turned off email in
    general, or this specific category, in their preferences. A user
    who has never visited the preferences page (no row yet) always
    gets True — same "unchanged default behavior" guarantee every
    other flag on UserNotificationPreference already gives."""
    pref = db.get(UserNotificationPreference, user_id)
    if pref is None:
        return True
    if not pref.email_enabled:
        return False
    if category is None:
        return True
    column = _CATEGORY_COLUMN.get(category)
    if column is None:
        return True  # unknown/future category — default to sending rather than silently dropping
    return bool(getattr(pref, column))
