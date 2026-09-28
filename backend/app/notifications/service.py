"""V23.1 — NotificationService.

The one place that reads/writes the ``Notification`` table for the
new event-driven system (V7/V19.4's own notification_center/read/
read-all/delete endpoints in app.api.notification_engine keep working
unmodified and keep writing the same table directly for their own,
narrower use case — see that module's and Notification's docstrings
for why both exist side by side rather than one replacing the other).

Every function here takes ``user_id`` from the caller (which, at the
API layer, is always the verified JWT — see app/api/notifications.py)
and never trusts a caller-supplied id for anything it doesn't
independently re-check against that ``user_id``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.domain import Notification

logger = logging.getLogger("careeros.notifications")

CATEGORIES: tuple[str, ...] = ("JOB", "APPLICATION", "INTERVIEW", "DEADLINE", "RECRUITER", "AI", "SYSTEM")
PRIORITIES: tuple[str, ...] = ("LOW", "NORMAL", "HIGH", "URGENT")

# Deep links are always built by this codebase, never taken from a
# caller — but every action_url is still checked against this allowlist
# of known-safe internal route prefixes before being stored, as
# defense in depth (spec: "Do NOT allow arbitrary unsafe redirect
# URLs. Prefer validated internal routes.").
_SAFE_ACTION_URL_PREFIXES = (
    "/applications/", "/jobs/", "/notifications", "/interview/", "/recruiter/",
    # V23.5: no current call site actually needs these yet (every
    # existing create_notification(...) call from V23.3/V23.4 uses
    # /jobs/{id} or /applications/{id} — see
    # app.job_alerts.execution/app.communication.reminders), but
    # /job-alerts and /communication are real, current-generation
    # internal routes this exact codebase serves, so a future
    # notification that deep-links into either (e.g. a "3 new alert
    # matches" summary) shouldn't be blocked by an allowlist that
    # simply hasn't caught up. Purely additive — widens what's
    # permitted, never what's already allowed.
    "/job-alerts", "/communication",
)


class NotificationError(Exception):
    pass


def _validate_action_url(action_url: str | None) -> str | None:
    if action_url is None:
        return None
    if not action_url.startswith("/") or action_url.startswith("//"):
        raise NotificationError(f"Unsafe action_url (must be an internal path): {action_url!r}")
    if "://" in action_url:
        raise NotificationError(f"Unsafe action_url (must not contain a scheme): {action_url!r}")
    if not any(action_url.startswith(p) for p in _SAFE_ACTION_URL_PREFIXES):
        raise NotificationError(f"action_url is not under a known-safe route prefix: {action_url!r}")
    return action_url[:300]


def create_notification(
    db: Session,
    user_id: int,
    *,
    notification_type: str,
    title: str,
    message: str,
    category: str | None = None,
    priority: str = "NORMAL",
    action_url: str | None = None,
    metadata: dict | None = None,
    job_id: int | None = None,
    dedupe_key: str | None = None,
) -> Notification | None:
    """Creates one notification, enforcing the idempotency contract:
    if ``dedupe_key`` is given and a notification with that exact
    (user_id, dedupe_key) pair already exists, this is a no-op and
    returns None rather than a duplicate row — callers that care can
    check the return value; event handlers (events.py) don't need to,
    since "already notified" and "just notified" both mean the
    candidate has exactly one notification for that event either way.

    A pre-check keeps the common case cheap (no failed-transaction
    round trip); the UNIQUE(user_id, dedupe_key) constraint at the DB
    layer is the actual guarantee under concurrent/retried calls — the
    pre-check alone would have a race window without it.
    """
    if category is not None and category not in CATEGORIES:
        raise NotificationError(f"category must be one of {CATEGORIES}")
    if priority not in PRIORITIES:
        raise NotificationError(f"priority must be one of {PRIORITIES}")
    validated_url = _validate_action_url(action_url)

    if dedupe_key:
        existing = db.scalar(
            select(Notification.id).where(Notification.user_id == user_id, Notification.dedupe_key == dedupe_key)
        )
        if existing is not None:
            return None

    now = datetime.utcnow()
    record = Notification(
        user_id=user_id,
        job_id=job_id,
        notification_type=notification_type,
        category=category,
        priority=priority,
        title=title[:220],
        message=message,
        action_url=validated_url,
        metadata_json=json.dumps(metadata) if metadata else None,
        dedupe_key=dedupe_key,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race with a concurrent/retried call using the same
        # dedupe_key — the other call's row is the notification that
        # exists now; this one is correctly not created.
        db.rollback()
        return None
    db.refresh(record)
    return record


def create_bulk_notifications(db: Session, user_ids: list[int], **kwargs) -> list[Notification]:
    """Same contract as create_notification, for a batch of
    recipients sharing one event (e.g. a job-match alert). Each
    recipient's dedupe_key, if given as a template via
    ``kwargs["dedupe_key"]``, is used as-is — callers that need a
    per-user key should call create_notification in a loop instead."""
    created = []
    for uid in user_ids:
        record = create_notification(db, uid, **kwargs)
        if record is not None:
            created.append(record)
    return created


def list_notifications(
    db: Session,
    user_id: int,
    *,
    unread_only: bool = False,
    category: str | None = None,
    priority: str | None = None,
    include_archived: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Notification], int]:
    stmt = select(Notification).where(Notification.user_id == user_id)
    count_stmt = select(func.count()).select_from(Notification).where(Notification.user_id == user_id)

    if not include_archived:
        stmt = stmt.where(Notification.archived.is_(False))
        count_stmt = count_stmt.where(Notification.archived.is_(False))
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
        count_stmt = count_stmt.where(Notification.read.is_(False))
    if category:
        stmt = stmt.where(Notification.category == category)
        count_stmt = count_stmt.where(Notification.category == category)
    if priority:
        stmt = stmt.where(Notification.priority == priority)
        count_stmt = count_stmt.where(Notification.priority == priority)

    total = db.scalar(count_stmt) or 0
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).offset(offset)
    items = db.scalars(stmt).all()
    return items, total


def get_unread_count(db: Session, user_id: int) -> int:
    """A single indexed COUNT query (ix_notifications_user_id_read) —
    never loads notification rows just to count them (spec: "Do not
    load the entire notification history to calculate unread count")."""
    return db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id, Notification.read.is_(False), Notification.archived.is_(False)
        )
    ) or 0


def _get_owned(db: Session, user_id: int, notification_id: int) -> Notification:
    record = db.get(Notification, notification_id)
    if record is None or record.user_id != user_id:
        raise NotificationError(f"Notification {notification_id} not found")
    return record


def mark_read(db: Session, user_id: int, notification_id: int) -> Notification:
    record = _get_owned(db, user_id, notification_id)
    if not record.read:
        record.read = True
        record.read_at = datetime.utcnow()
        record.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(record)
    return record


def mark_unread(db: Session, user_id: int, notification_id: int) -> Notification:
    record = _get_owned(db, user_id, notification_id)
    if record.read:
        record.read = False
        record.read_at = None
        record.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(record)
    return record


def mark_all_read(db: Session, user_id: int) -> int:
    now = datetime.utcnow()
    rows = db.scalars(select(Notification).where(Notification.user_id == user_id, Notification.read.is_(False))).all()
    for record in rows:
        record.read = True
        record.read_at = now
        record.updated_at = now
    db.commit()
    return len(rows)


def delete_notification(db: Session, user_id: int, notification_id: int) -> None:
    record = _get_owned(db, user_id, notification_id)
    db.delete(record)
    db.commit()
