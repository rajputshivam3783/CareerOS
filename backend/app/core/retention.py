"""V25.6 — configurable data-retention policy and an OPT-IN purge.

Nothing in CareerOS deletes data on a timer by default. ``settings.retention_purge_enabled``
must be set to true AND ``purge_expired`` (or ``scripts/retention_purge.py``) must be run.
Even then only the categories below are touched. Audit logs, security events, applications,
applicant (hiring) records, jobs, organisations and user accounts are NEVER purged here -
their retention is a business/legal decision documented in
docs/DATA_RETENTION_AND_DELETION.md, and person-level removal is handled by the
account-erasure workflow (app.core.account_lifecycle).

``0`` for any ``*_days`` setting means "keep indefinitely".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.domain import AIUsageLog, EmailMessage, EmailVerification, Notification, RefreshToken

log = logging.getLogger("careeros.retention")


@dataclass(frozen=True)
class RetentionRule:
    key: str
    description: str
    setting_name: str
    reason: str


# Human-readable policy; docs/DATA_RETENTION_AND_DELETION.md is generated from the same facts.
PURGEABLE_RULES: tuple[RetentionRule, ...] = (
    RetentionRule(
        "auth_artifacts",
        "Consumed or expired one-time-code rows and revoked or expired refresh tokens",
        "retention_auth_artifacts_days",
        "Only needed while valid plus a short window for support/forensics; contain no plaintext secrets.",
    ),
    RetentionRule(
        "notifications",
        "Read or archived in-app notifications",
        "retention_notifications_days",
        "Convenience feed; unread notifications are never purged.",
    ),
    RetentionRule(
        "email_messages",
        "Outbound email delivery records (recipient, subject, status; OTP values are never stored)",
        "retention_email_messages_days",
        "Delivery troubleshooting; contains recipient address.",
    ),
    RetentionRule(
        "ai_usage_logs",
        "Per-call AI usage/cost telemetry (no prompt or response text)",
        "retention_ai_usage_logs_days",
        "Cost reporting and capacity planning.",
    ),
)

NEVER_PURGED = (
    "audit_logs",
    "platform_audit_logs (security events live here)",
    "applications / applicants / interviews / offers",
    "jobs / organizations / organization_members",
    "users (use account erasure instead)",
)


def _cutoff(days: int, now: datetime) -> datetime | None:
    return now - timedelta(days=days) if days and days > 0 else None


def purge_expired(db: Session, *, dry_run: bool = True, now: datetime | None = None) -> dict[str, int]:
    """Delete (or, with ``dry_run=True``, only count) rows past their retention period.

    Returns ``{rule_key: rows}``. Does NOT commit; the caller decides. Refuses to delete
    unless ``settings.retention_purge_enabled`` is true (dry runs are always allowed)."""
    now = now or datetime.utcnow()
    if not dry_run and not settings.retention_purge_enabled:
        raise RuntimeError("Retention purge is disabled (RETENTION_PURGE_ENABLED=false); run with dry_run=True to preview")

    plan: list[tuple[str, object, object]] = []  # (key, table-model, where-clause)

    cutoff = _cutoff(settings.retention_auth_artifacts_days, now)
    if cutoff:
        plan.append(
            (
                "auth_artifacts",
                EmailVerification,
                (EmailVerification.created_at < cutoff)
                & ((EmailVerification.consumed.is_(True)) | (EmailVerification.expires_at < now)),
            )
        )
        plan.append(
            (
                "auth_artifacts",
                RefreshToken,
                (RefreshToken.created_at < cutoff) & ((RefreshToken.revoked_at.is_not(None)) | (RefreshToken.expires_at < now)),
            )
        )
    cutoff = _cutoff(settings.retention_notifications_days, now)
    if cutoff:
        plan.append(
            ("notifications", Notification, (Notification.created_at < cutoff) & ((Notification.read.is_(True)) | (Notification.archived.is_(True))))
        )
    cutoff = _cutoff(settings.retention_email_messages_days, now)
    if cutoff:
        plan.append(("email_messages", EmailMessage, EmailMessage.created_at < cutoff))
    cutoff = _cutoff(settings.retention_ai_usage_logs_days, now)
    if cutoff:
        plan.append(("ai_usage_logs", AIUsageLog, AIUsageLog.created_at < cutoff))

    counts: dict[str, int] = {rule.key: 0 for rule in PURGEABLE_RULES}
    for key, model, clause in plan:
        if dry_run:
            counts[key] += int(db.scalar(select(func.count()).select_from(model).where(clause)) or 0)
        else:
            counts[key] += db.execute(delete(model).where(clause)).rowcount or 0
    log.info("Retention %s: %s", "dry-run" if dry_run else "purge", counts)
    return counts
