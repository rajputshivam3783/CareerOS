"""V16 — centralized audit logging.

Every write that previously did ``db.add(AuditLog(action=..., ...))``
directly now goes through ``log_audit`` instead, so every row
automatically carries *who* did it (actor) and *which request*
(request_id/IP) it happened in — not just *what* happened. Before V16,
``actor_type``/``actor_id`` didn't exist on the table, so an audit row
proved an action occurred but not who was signed in when it did
(the admin panel authenticates with one shared static key, not
per-admin logins — see ``app.api.admin.require_admin_access``).

This does not change the (action, entity_type, entity_id, detail)
call sites' meaning at all — it's a drop-in replacement that adds
columns, not a redesign of what gets logged.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.request_context import get_client_ip, get_request_id, get_actor
from app.models.domain import AuditLog


def log_audit(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    detail: str | None = None,
) -> AuditLog:
    """Create (but don't commit) an audit row, filling in the current
    request's actor/request-id/IP from context. Callers keep control
    of the commit boundary — this matches every existing call site,
    which does ``db.add(AuditLog(...))`` then commits once, sometimes
    alongside other changes in the same transaction."""
    actor = get_actor()
    row = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail=detail,
        actor_type=actor.actor_type if actor else None,
        actor_id=actor.actor_id if actor else None,
        actor_label=actor.label if actor else None,
        request_id=get_request_id(),
        ip_address=get_client_ip(),
    )
    db.add(row)
    return row
