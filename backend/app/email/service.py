"""V23.2 — EmailService.

Two ways in:

  queue_email()              — fire-and-forget. Inserts a QUEUED
                                EmailMessage and returns immediately —
                                no SMTP call happens in this function
                                at all (spec section 20: "avoid
                                sending email synchronously inside
                                critical request paths"). Actual
                                delivery happens later via
                                process_queue(), run on a schedule by
                                app.scheduler (careeros_email_queue
                                job) — the same background-job
                                architecture V7/V19.4 already use for
                                notification scans and automation,
                                reused rather than inventing a new one.
                                Used by app.notifications.events for
                                every non-security-critical,
                                preference-gated email.

  send_transactional_email() — synchronous. Used only for the
                                latency-sensitive, security-critical
                                flows (email verification, password
                                reset) where the user is actively
                                waiting on the same page for a code.
                                Never checks preferences (spec: these
                                "must not be disabled through ordinary
                                notification preferences"). Never
                                raises — a failure is recorded and
                                logged, never surfaced as an exception
                                to its caller (app/api/auth.py), so a
                                transport failure can never turn a
                                successful registration/reset-request
                                into a 500.

Both are the ONLY functions that create an EmailMessage row —
app.notifications.events and app/api/auth.py never touch that model
directly, matching every other "one service owns one table" pattern
in this codebase.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.email import preferences as email_preferences
from app.email import templates as email_templates
from app.email.provider import OutgoingEmail, get_provider
from app.models.domain import EmailDeliveryAttempt, EmailMessage

logger = logging.getLogger("careeros.email.service")

STATUSES: tuple[str, ...] = ("QUEUED", "PROCESSING", "SENT", "FAILED", "RETRYING", "CANCELLED")


def queue_email(
    db: Session,
    *,
    user_id: int,
    recipient: str,
    template_key: str,
    variables: dict,
    category: str | None = None,
    dedupe_key: str | None = None,
    max_attempts: int | None = None,
) -> EmailMessage | None:
    """Returns the created (or, for a duplicate dedupe_key, existing)
    row, or None if the user's preferences say not to send this
    category, the template is invalid, or anything else goes wrong —
    every failure mode here is a safe no-op, never an exception
    reaching the caller (see module docstring)."""
    try:
        if category is not None and not email_preferences.should_send_email(db, user_id, category):
            return None

        template = email_templates.get_or_seed_template(db, template_key)
        # Validate now so a bad call fails loudly in logs at queue time,
        # not silently at send time when nobody's watching this request.
        email_templates.validate_variables(template, variables)
        subject = email_templates.render(template, variables)[0]

        if dedupe_key:
            existing = db.scalar(
                select(EmailMessage).where(EmailMessage.user_id == user_id, EmailMessage.dedupe_key == dedupe_key)
            )
            if existing is not None:
                return existing

        now = datetime.utcnow()
        record = EmailMessage(
            user_id=user_id,
            template_key=template_key,
            recipient=recipient,
            subject=subject,
            variables_json=json.dumps(variables),
            status="QUEUED",
            max_attempts=max_attempts or 4,
            scheduled_at=now,
            dedupe_key=dedupe_key,
            created_at=now,
            updated_at=now,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record
    except Exception:
        db.rollback()
        logger.error("queue_email failed for user_id=%s template_key=%s", user_id, template_key, exc_info=True)
        return None


def _record_attempt(db: Session, message: EmailMessage, *, status: str, provider_name: str, error: str | None) -> None:
    db.add(EmailDeliveryAttempt(
        email_message_id=message.id, attempt_number=message.attempts, status=status, provider=provider_name, error=error,
    ))


def _deliver(db: Session, message: EmailMessage) -> bool:
    """Renders + sends one EmailMessage, updates its status in place.
    Returns True on success. Never raises — provider failures are
    caught here and turned into a retry/failed status."""
    provider = get_provider()
    message.attempts += 1
    message.status = "PROCESSING"

    try:
        template = email_templates.get_or_seed_template(db, message.template_key)
        variables = json.loads(message.variables_json) if message.variables_json else {}
        subject, html_body, text_body = email_templates.render(template, variables)
        provider.send(OutgoingEmail(to=message.recipient, subject=subject, text_body=text_body, html_body=html_body))
    except Exception as exc:  # noqa: BLE001 — must never raise to process_queue's caller
        error_summary = str(exc)[:500]
        message.last_error = error_summary
        _record_attempt(db, message, status="FAILED", provider_name=provider.name, error=error_summary)
        if message.attempts >= message.max_attempts:
            message.status = "FAILED"
            message.failed_at = datetime.utcnow()
        else:
            # Exponential backoff: base * 2^(attempts-1) — attempt 1
            # retries after `base` seconds, attempt 2 after 2x, etc.
            backoff = _backoff_seconds(message.attempts)
            message.status = "RETRYING"
            message.scheduled_at = datetime.utcnow() + timedelta(seconds=backoff)
        message.updated_at = datetime.utcnow()
        db.commit()
        return False

    message.status = "SENT"
    message.sent_at = datetime.utcnow()
    message.updated_at = datetime.utcnow()
    _record_attempt(db, message, status="SENT", provider_name=provider.name, error=None)
    db.commit()
    return True


def _backoff_seconds(attempt_number: int) -> int:
    from app.core.config import settings
    return settings.email_retry_backoff_seconds * (2 ** max(0, attempt_number - 1))


def process_queue(db: Session, *, limit: int = 50) -> dict:
    """Called by the scheduler (see app/scheduler.py's
    careeros_email_queue job) — picks up every QUEUED/RETRYING row
    whose scheduled_at has arrived and attempts delivery. Bounded by
    `limit` per call so one slow tick can't monopolize the process."""
    now = datetime.utcnow()
    due = db.scalars(
        select(EmailMessage)
        .where(EmailMessage.status.in_(("QUEUED", "RETRYING")), EmailMessage.scheduled_at <= now)
        .order_by(EmailMessage.scheduled_at.asc())
        .limit(limit)
    ).all()

    sent = failed = retried = 0
    for message in due:
        ok = _deliver(db, message)
        if ok:
            sent += 1
        elif message.status == "FAILED":
            failed += 1
        else:
            retried += 1

    return {"processed": len(due), "sent": sent, "failed": failed, "retried": retried}


def send_transactional_email(
    db: Session,
    *,
    user_id: int,
    recipient: str,
    template_key: str,
    render_variables: dict,
    persisted_variables: dict | None = None,
) -> bool:
    """Synchronous, unconditional (no preference check), and never
    raises. ``render_variables`` is used only in memory to render the
    real email (may contain a secret, e.g. otp_code); only
    ``persisted_variables`` (defaults to {} — nothing) is ever written
    to EmailMessage.variables_json, so a secret never lands at rest.
    See module docstring for why this bypasses the queue.

    The row is persisted (status=PROCESSING) BEFORE rendering is
    attempted, so a bad template/missing variable still leaves a
    trackable FAILED row instead of vanishing silently — the record
    always exists once this function has been called at all."""
    now = datetime.utcnow()
    record = EmailMessage(
        user_id=user_id,
        template_key=template_key,
        recipient=recipient,
        subject="",  # filled in once rendered
        variables_json=json.dumps(persisted_variables or {}),
        status="PROCESSING",
        attempts=0,
        max_attempts=1,  # a stale OTP code isn't worth retrying later — the user will just request a new one
        scheduled_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    provider = get_provider()
    try:
        template = email_templates.get_or_seed_template(db, template_key)
        subject, html_body, text_body = email_templates.render(template, render_variables)
        record.subject = subject
        record.attempts = 1
        provider.send(OutgoingEmail(to=recipient, subject=subject, text_body=text_body, html_body=html_body))
    except Exception as exc:  # noqa: BLE001 — transactional sends must never raise, see docstring
        error_summary = str(exc)[:500]
        logger.error("send_transactional_email failed for user_id=%s template_key=%s", user_id, template_key, exc_info=True)
        record.status = "FAILED"
        record.failed_at = datetime.utcnow()
        record.last_error = error_summary
        record.updated_at = datetime.utcnow()
        record.attempts = max(record.attempts, 1)
        _record_attempt(db, record, status="FAILED", provider_name=provider.name, error=error_summary)
        db.commit()
        return False

    record.status = "SENT"
    record.sent_at = datetime.utcnow()
    record.updated_at = datetime.utcnow()
    _record_attempt(db, record, status="SENT", provider_name=provider.name, error=None)
    db.commit()
    return True
