"""V17.2 — centralized security event service.

This does not replace ``app.core.audit.log_audit`` (V16) — every
security event is still an audit row, so ``GET /admin/audit-logs``
keeps working exactly as it does today. What this adds is:

1. A single, named taxonomy (``SecurityEvent``) for the specific event
   types the V17.2 hardening pass asked to have logged, instead of
   each call site inventing its own action string.
2. A real, working extension point for "future SIEM/webhook/
   notification integration" — ``register_handler()`` — rather than a
   claim that any such integration already exists. **No handler is
   registered by default.** Wiring an actual webhook or SIEM forwarder
   is future work; this only makes it possible to add one without
   touching every call site that raises an event, by writing a
   function and calling ``register_handler`` once (e.g. in
   ``app/main.py`` startup) — see the example at the bottom of this
   file's docstring section.

A handler that raises is caught and logged, never allowed to fail the
request that triggered the event — a broken webhook integration must
not be able to break login.

Example future handler (not implemented, illustrative only)::

    def forward_to_siem(event: SecurityEvent, entity_type, entity_id, detail):
        requests.post(SIEM_WEBHOOK_URL, json={...}, timeout=2)

    register_handler(forward_to_siem)
"""

from __future__ import annotations

import logging
from enum import Enum

from sqlalchemy.orm import Session

from app.core.audit import log_audit

log = logging.getLogger("careeros.security_events")


class SecurityEvent(str, Enum):
    LOGIN_FAILED = "login_failed"
    LOGIN_SUCCESS = "login"
    LOGOUT = "logout"
    LOGOUT_ALL = "logout_all"
    OTP_VERIFY_SUCCESS = "verify_email"
    OTP_VERIFY_FAILED = "otp_verify_failed"
    OTP_RESEND = "otp_resend"
    PASSWORD_CHANGE = "password_change"
    PASSWORD_RESET = "reset_password"
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_UNLOCKED = "account_unlocked"
    ACCOUNT_LOCKED_LOGIN_ATTEMPT = "login_blocked_locked_account"
    SESSION_REVOKED = "session_revoked"
    TOKEN_REVOKED = "token_revoked"
    REFRESH_TOKEN_USE = "refresh_token_use"
    REFRESH_TOKEN_REUSE_DETECTED = "refresh_token_reuse_detected"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    # --- V25.2 (Advanced Admin & Platform Governance) -------------------
    # Added to this existing taxonomy rather than to a new
    # `security_events` table: every one of these is already exactly
    # what this module records — a named event, attributed to an actor
    # and a request, written to `audit_logs`. A second store would
    # duplicate the audit system spec section 28 asks us not to
    # duplicate, and would leave an investigator querying two places.
    #
    # None of these ever carries a password, token, OTP or session id
    # in its `detail` — see each call site.
    PRIVILEGE_ESCALATION_ATTEMPT = "privilege_escalation_attempt"
    CROSS_TENANT_ACCESS_ATTEMPT = "cross_tenant_access_attempt"
    INVALID_INVITATION_ATTEMPT = "invalid_invitation_attempt"
    SUSPENDED_ACCOUNT_ACCESS_ATTEMPT = "suspended_account_access_attempt"
    PLATFORM_SETTING_CHANGED = "platform_setting_changed"
    # --- V25.6 (Enterprise Security & Compliance) -----------------------
    # Account lifecycle events. Neither carries an email, name or password in `detail`.
    ACCOUNT_SELF_DEACTIVATED = "account_self_deactivated"
    ACCOUNT_ERASED = "account_erased"
    ACCOUNT_LIFECYCLE_AUTH_FAILED = "account_lifecycle_auth_failed"


# The subset of the taxonomy above that the admin security-events
# screen surfaces (spec sections 22/23). Deliberately not "every
# audit action": a successful login is an audit event, not a security
# *incident*, and listing millions of them would bury the handful that
# matter. Ordinary successful logins/logouts are therefore excluded.
SECURITY_INCIDENT_ACTIONS: tuple[str, ...] = (
    SecurityEvent.LOGIN_FAILED.value,
    SecurityEvent.OTP_VERIFY_FAILED.value,
    SecurityEvent.ACCOUNT_LOCKED.value,
    SecurityEvent.ACCOUNT_LOCKED_LOGIN_ATTEMPT.value,
    SecurityEvent.REFRESH_TOKEN_REUSE_DETECTED.value,
    SecurityEvent.SUSPICIOUS_ACTIVITY.value,
    SecurityEvent.PRIVILEGE_ESCALATION_ATTEMPT.value,
    SecurityEvent.CROSS_TENANT_ACCESS_ATTEMPT.value,
    SecurityEvent.INVALID_INVITATION_ATTEMPT.value,
    SecurityEvent.SUSPENDED_ACCOUNT_ACCESS_ATTEMPT.value,
    SecurityEvent.PLATFORM_SETTING_CHANGED.value,
    SecurityEvent.ACCOUNT_LIFECYCLE_AUTH_FAILED.value,
)


_handlers: list = []


def register_handler(fn) -> None:
    """Register a callable invoked (synchronously, best-effort) after
    every recorded security event: ``fn(event, entity_type, entity_id,
    detail)``. See module docstring — no handler is registered by
    default anywhere in this project."""
    _handlers.append(fn)


def record_security_event(
    db: Session,
    event: SecurityEvent,
    entity_type: str,
    entity_id: str | None = None,
    detail: str | None = None,
):
    """Write the event as an audit row (same table/shape as every
    other app.core.audit.log_audit call — actor/request-id/IP are
    filled in automatically the same way) and notify any registered
    handlers. Does not commit — same contract as log_audit; the caller
    controls the transaction boundary."""
    row = log_audit(db, action=event.value, entity_type=entity_type, entity_id=entity_id, detail=detail)
    for handler in _handlers:
        try:
            handler(event, entity_type, entity_id, detail)
        except Exception:
            log.exception("Security event handler %r raised for event %s", handler, event.value)
    return row
