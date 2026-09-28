"""V25.4 — Action lifecycle: create, confirm, reject (spec sections 4,
18, 26, 34).

A CareerAgentAction row is the durable record of one tool call — READ
tools are logged already COMPLETED (a full audit trail, not just of
writes); WRITE/HIGH_RISK tools are logged PENDING_CONFIRMATION and the
underlying service function is NOT called until ``confirm_action``
runs. This is the structural guarantee behind "no irreversible
external action without explicit user confirmation" — the tool
handler in tools.py is physically not invoked on the planning path for
a write, only from here, only after a confirm.

Idempotency (spec section 34, "replaying confirmed actions", "duplicate
action execution"): ``confirm_action`` checks the action's current
status before doing anything — confirming an action that is already
COMPLETED, REJECTED, or FAILED is a no-op that returns the existing
result rather than re-running the tool. There is no code path that
executes a given action row's tool call more than once.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.career_agent import tool_registry
from app.career_agent.tools import ToolInputError
from app.core.config import settings
from app.models.domain import CareerAgentAction, User


class ActionNotFoundError(Exception):
    pass


class ActionNotPendingError(Exception):
    """Raised when confirm/reject is called on an action that isn't
    (or no longer is) PENDING_CONFIRMATION — including double-confirm
    and double-reject, which are rejected rather than silently
    treated as no-ops, so a caller polling status sees a clear signal
    rather than mistaking a stale click for success."""


def create_action(
    db: Session, user: User, *, conversation_id: int | None, tool_name: str, params: dict, risk: str,
    status: str = "PENDING_CONFIRMATION",
) -> CareerAgentAction:
    action = CareerAgentAction(
        user_id=user.id,
        conversation_id=conversation_id,
        action_type=tool_name,
        risk_level=risk,
        status=status,
        payload_json=json.dumps(params),
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def _get_owned(db: Session, user_id: int, action_id: int) -> CareerAgentAction:
    action = db.get(CareerAgentAction, action_id)
    if not action or action.user_id != user_id:
        raise ActionNotFoundError(f"Action {action_id} not found")
    return action


def get_owned_action(db: Session, user_id: int, action_id: int) -> CareerAgentAction:
    return _get_owned(db, user_id, action_id)


def list_pending_actions(db: Session, user_id: int) -> list[CareerAgentAction]:
    from sqlalchemy import select

    stmt = (
        select(CareerAgentAction)
        .where(CareerAgentAction.user_id == user_id, CareerAgentAction.status == "PENDING_CONFIRMATION")
        .order_by(CareerAgentAction.created_at.desc())
    )
    return db.scalars(stmt).all()


def run_action_now(db: Session, user: User, *, conversation_id: int | None, tool_name: str, params: dict) -> CareerAgentAction:
    """For READ tools only — executes immediately and logs the result
    already COMPLETED. Never called for WRITE/HIGH_RISK tools; see
    agent_service.py, which routes by risk level before reaching
    here."""

    spec = tool_registry.get_tool(tool_name)
    if spec is None:
        raise ActionNotFoundError(f"Unknown tool: {tool_name!r}")

    action = create_action(
        db, user, conversation_id=conversation_id, tool_name=tool_name, params=params, risk=spec.risk,
        status="EXECUTING",
    )
    try:
        result = spec.handler(db, user, **params)
        action.status = "COMPLETED"
        action.result_json = json.dumps(result, default=str)
        action.completed_at = datetime.utcnow()
    except ToolInputError as exc:
        action.status = "FAILED"
        action.error = str(exc)[:500]
    except Exception as exc:  # deliberately broad — a tool failure must never surface as a raw 500
        action.status = "FAILED"
        action.error = "This request could not be completed."
        action.error = f"{action.error} ({type(exc).__name__})"[:500]
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def confirm_action(db: Session, user: User, action_id: int) -> CareerAgentAction:
    """Execute a pending WRITE/HIGH_RISK action exactly once.

    V25.6 hardening (see docs/V25_FINAL_SECURITY_AND_COMPLIANCE_AUDIT.md, finding F-06):

    * Only ``PENDING_CONFIRMATION`` can be confirmed. Previously anything other than
      COMPLETED/REJECTED/FAILED was accepted, so an action in EXECUTING (a concurrent
      request, or one that crashed mid-run) could be executed a second time.
    * The PENDING -> EXECUTING transition is a single atomic compare-and-set UPDATE.
      Two concurrent confirm calls cannot both win it, so the tool cannot run twice.
    * A pending action expires after ``career_agent_action_ttl_minutes`` so a stale
      confirmation cannot be replayed days later against a changed context.

    An action whose process dies while EXECUTING stays EXECUTING and is never re-run
    automatically - failing closed is the safe direction for an action with side effects."""
    action = _get_owned(db, user.id, action_id)

    if action.status != "PENDING_CONFIRMATION":
        raise ActionNotPendingError(f"Action {action_id} is not pending confirmation (status: {action.status})")

    ttl_minutes = settings.career_agent_action_ttl_minutes
    if ttl_minutes and action.created_at and action.created_at < datetime.utcnow() - timedelta(minutes=ttl_minutes):
        expired = db.execute(
            update(CareerAgentAction)
            .where(CareerAgentAction.id == action.id, CareerAgentAction.status == "PENDING_CONFIRMATION")
            .values(status="FAILED", error="This action expired before it was confirmed.", completed_at=datetime.utcnow())
        )
        db.commit()
        db.refresh(action)
        if expired.rowcount:
            raise ActionNotPendingError(f"Action {action_id} expired before it was confirmed")
        raise ActionNotPendingError(f"Action {action_id} is not pending confirmation (status: {action.status})")

    claimed = db.execute(
        update(CareerAgentAction)
        .where(
            CareerAgentAction.id == action.id,
            CareerAgentAction.user_id == user.id,
            CareerAgentAction.status == "PENDING_CONFIRMATION",
        )
        .values(status="EXECUTING")
    )
    db.commit()
    if claimed.rowcount != 1:
        raise ActionNotPendingError(f"Action {action_id} is already being processed")
    db.refresh(action)

    spec = tool_registry.get_tool(action.action_type)
    if spec is None:
        action.status = "FAILED"
        action.error = "This action's tool is no longer available."
        db.add(action)
        db.commit()
        db.refresh(action)
        return action

    try:
        params = json.loads(action.payload_json)
        result = spec.handler(db, user, **params)
        action.status = "COMPLETED"
        action.result_json = json.dumps(result, default=str)
        action.completed_at = datetime.utcnow()
    except ToolInputError as exc:
        action.status = "FAILED"
        action.error = str(exc)[:500]
    except Exception as exc:
        action.status = "FAILED"
        action.error = f"This request could not be completed. ({type(exc).__name__})"[:500]

    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def reject_action(db: Session, user: User, action_id: int) -> CareerAgentAction:
    action = _get_owned(db, user.id, action_id)
    if action.status != "PENDING_CONFIRMATION":
        raise ActionNotPendingError(f"Action {action_id} is not pending confirmation")
    action.status = "REJECTED"
    action.completed_at = datetime.utcnow()
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def action_out(action: CareerAgentAction) -> dict:
    return {
        "id": action.id,
        "action_type": action.action_type,
        "risk_level": action.risk_level,
        "status": action.status,
        "params": json.loads(action.payload_json),
        "result": json.loads(action.result_json) if action.result_json else None,
        "error": action.error,
        "created_at": action.created_at.isoformat(),
        "completed_at": action.completed_at.isoformat() if action.completed_at else None,
    }
