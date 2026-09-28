"""V25.2 — the append-only platform-administration audit trail.

Every important platform-admin action goes through
``record_platform_action`` exactly once. That function is the only
writer of ``platform_audit_logs`` anywhere in the codebase, and
nothing anywhere issues an UPDATE or DELETE against that table — the
append-only guarantee (spec sections 10/32) is upheld by there being
no code capable of violating it, not by a permission check that could
be misconfigured.

Relationship to ``app.core.audit.log_audit`` (V16): both are written.
``log_audit`` keeps the platform-wide `audit_logs` trail complete and
unchanged, so every existing consumer (GET /admin/audit-logs, the
V17.3 CSV export, the security-event taxonomy) keeps seeing admin
actions exactly as it does today. ``record_platform_action``
additionally writes the structured governance record that the
investigation UI filters on. See ``PlatformAuditLog``'s docstring in
app.models.domain for why that structure can't just live in
`audit_logs.detail`.

WHAT IS NEVER RECORDED
----------------------
``metadata`` is filtered through ``_safe_metadata`` before it is
stored: values are coerced to short scalars, keys matching known
secret-ish names are dropped outright, and long strings are truncated.
An audit trail that accidentally becomes a copy of the data it is
auditing is a liability, not a control.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.platform_admin import PlatformActor
from app.core.request_context import get_client_ip, get_request_id
from app.models.domain import PlatformAuditLog

log = logging.getLogger("careeros.platform_audit")


class PlatformAction:
    """The catalog of auditable platform-admin actions.

    String constants (not an Enum) for the same reason as
    ``PlatformPermission`` — they land directly in the DB column, the
    API response and the frontend filter dropdown.
    """

    USER_SUSPENDED = "USER_SUSPENDED"
    USER_REACTIVATED = "USER_REACTIVATED"
    USER_DEACTIVATED = "USER_DEACTIVATED"
    USER_VIEWED = "USER_VIEWED"
    ROLE_CHANGED = "ROLE_CHANGED"

    ORGANIZATION_SUSPENDED = "ORGANIZATION_SUSPENDED"
    ORGANIZATION_REACTIVATED = "ORGANIZATION_REACTIVATED"
    ORGANIZATION_DEACTIVATED = "ORGANIZATION_DEACTIVATED"

    JOB_APPROVED = "JOB_APPROVED"
    JOB_REJECTED = "JOB_REJECTED"
    JOB_SUSPENDED = "JOB_SUSPENDED"
    JOB_RESTORED = "JOB_RESTORED"

    PLATFORM_SETTING_CHANGED = "PLATFORM_SETTING_CHANGED"
    MAINTENANCE_MODE_ENABLED = "MAINTENANCE_MODE_ENABLED"
    MAINTENANCE_MODE_DISABLED = "MAINTENANCE_MODE_DISABLED"

    ANNOUNCEMENT_CREATED = "ANNOUNCEMENT_CREATED"
    ANNOUNCEMENT_SENT = "ANNOUNCEMENT_SENT"

    BULK_JOB_MODERATION = "BULK_JOB_MODERATION"
    BULK_USER_STATUS_UPDATE = "BULK_USER_STATUS_UPDATE"
    BULK_ORGANIZATION_STATUS_UPDATE = "BULK_ORGANIZATION_STATUS_UPDATE"

    # V25.3 — an administrator recorded a triage decision about a
    # detected data-quality issue. Note what this is NOT: no V25.3
    # endpoint modifies an inspected job, account or application, so
    # there is no "DATA_QUALITY_FIXED" action to record.
    DATA_QUALITY_TRIAGED = "DATA_QUALITY_TRIAGED"


ALL_PLATFORM_ACTIONS: tuple[str, ...] = tuple(
    value for name, value in vars(PlatformAction).items() if not name.startswith("_") and isinstance(value, str)
)

TARGET_TYPES: tuple[str, ...] = (
    "user",
    "organization",
    "job",
    "platform_setting",
    "announcement",
    "bulk",
    # V25.3 data-quality triage targets. "job", "user" and "application"
    # above already cover most rules; these two name the remainder.
    "candidate",
    "application",
    "skill",
    "data_quality",
)

RESULTS: tuple[str, ...] = ("success", "failure", "partial")

# Substrings that disqualify a metadata key. Matched case-insensitively
# against the whole key, so "password_hash", "refresh_token" and
# "otp_code" are all dropped. Conservative on purpose: a dropped field
# costs an investigator one extra query; a leaked one can't be undone.
_FORBIDDEN_KEY_PARTS = (
    "password",
    "token",
    "secret",
    "otp",
    "api_key",
    "apikey",
    "hash",
    "credential",
    "authorization",
    "resume",
    "document",
    "cookie",
    "session",
)

_MAX_VALUE_LENGTH = 300
_MAX_METADATA_KEYS = 20


def _safe_metadata(metadata: dict | None) -> str | None:
    """Reduce caller-supplied metadata to something safe to persist.

    Drops forbidden keys, coerces values to scalars, truncates long
    strings, and caps the number of keys. Returns None for an empty
    result so the column stays NULL rather than holding "{}".
    """
    if not metadata:
        return None
    clean: dict[str, object] = {}
    for key, value in metadata.items():
        if len(clean) >= _MAX_METADATA_KEYS:
            break
        key_str = str(key)
        lowered = key_str.lower()
        if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
            continue
        if value is None or isinstance(value, (bool, int, float)):
            clean[key_str] = value
        elif isinstance(value, (list, tuple)):
            # Lists are kept only as a count plus a short sample —
            # a bulk operation on 5,000 ids must not write 5,000 ids
            # into one audit row.
            items = list(value)[:10]
            clean[key_str] = {"count": len(value), "sample": [str(i)[:60] for i in items]}
        else:
            clean[key_str] = str(value)[:_MAX_VALUE_LENGTH]
    if not clean:
        return None
    try:
        return json.dumps(clean, default=str)
    except (TypeError, ValueError):  # pragma: no cover - default=str makes this near-impossible
        return None


def record_platform_action(
    db: Session,
    actor: PlatformActor,
    *,
    action: str,
    target_type: str,
    target_id: str | int | None = None,
    organization_id: int | None = None,
    reason: str | None = None,
    note: str | None = None,
    metadata: dict | None = None,
    result: str = "success",
) -> PlatformAuditLog:
    """Append one governance record (and the matching `audit_logs`
    row) for a platform-admin action.

    Does NOT commit — the caller owns the transaction boundary, which
    is what makes the audit row and the state change it describes
    atomic: either both land or neither does. This matches the
    contract of ``app.core.audit.log_audit``, which every other
    subsystem in this codebase already follows.
    """
    if result not in RESULTS:
        result = "success"

    row = PlatformAuditLog(
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        organization_id=organization_id,
        actor_user_id=actor.user_id,
        actor_type=actor.actor_type,
        actor_label=actor.label,
        reason=reason,
        note=note,
        metadata_json=_safe_metadata(metadata),
        result=result,
        request_id=get_request_id(),
        ip_address=get_client_ip(),
    )
    db.add(row)

    # Mirror into the platform-wide trail so anything already reading
    # `audit_logs` (GET /admin/audit-logs, the V17.3 export, external
    # log shipping) sees platform-admin actions too. Deliberately a
    # short summary, not a duplicate of the structured record — the
    # structured one is authoritative.
    log_audit(
        db,
        action=action.lower(),
        entity_type=target_type,
        entity_id=str(target_id) if target_id is not None else None,
        detail=f"platform_admin action result={result}" + (f" reason={reason}" if reason else ""),
    )
    return row
