"""V25.4 — Advanced AI Career Agent & Automation API.

Reuses, never rewrites: ``current_user`` (app.core.security),
``enforce_rate_limit`` (app.core.rate_limit). Every endpoint here
resolves the acting user from the verified JWT and passes only that
id into app.career_agent — no endpoint accepts or trusts a
caller-supplied user id (spec sections 17, 34), and no endpoint here
exposes a recruiter/admin tool (see app.career_agent.permissions).

Mounted at ``/career-agent`` — deliberately separate from
``/career-copilot`` (V20.3, unchanged): the Copilot remains a
pure grounded-chat advisor; the Agent additionally executes
tools/actions with a confirmation model. Neither replaces the other.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.career_agent import agent_service, brief as brief_service, conversation_store, preferences as agent_preferences
from app.career_agent import actions as actions_service
from app.career_agent import tool_registry
from app.core.rate_limit import enforce_rate_limit
from app.core.security import current_user
from app.db.session import get_db
from app.models.domain import User

router = APIRouter(prefix="/career-agent")


def _owned_conversation(db: Session, conversation_id: int, u: User):
    try:
        return conversation_store.get_owned_conversation(db, u.id, conversation_id)
    except conversation_store.ConversationNotFoundError as exc:
        raise HTTPException(404, "Conversation not found") from exc


# ---------------------------------------------------------------------------
# Tools (read-only introspection — spec section 29's "tool/action indicators")
# ---------------------------------------------------------------------------


@router.get("/tools")
def list_tools(u: User = Depends(current_user)):
    return {"tools": tool_registry.list_tools_for_candidate()}


# ---------------------------------------------------------------------------
# Conversations & history (spec section 15)
# ---------------------------------------------------------------------------


class ConversationStartIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@router.get("/conversations")
def list_conversations(include_archived: bool = False, u: User = Depends(current_user), db: Session = Depends(get_db)):
    conversations = conversation_store.list_conversations(db, u.id, include_archived=include_archived)
    return {"conversations": [conversation_store.conversation_out(c) for c in conversations]}


@router.post("/conversations")
def start_conversation(payload: ConversationStartIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = conversation_store.create_conversation(db, u.id, title=payload.title)
    return conversation_store.conversation_out(conversation)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = _owned_conversation(db, conversation_id, u)
    messages = conversation_store.get_messages(db, conversation.id)
    return {
        "conversation": conversation_store.conversation_out(conversation),
        "messages": [conversation_store.message_out(m) for m in messages],
    }


@router.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: int, payload: RenameIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = _owned_conversation(db, conversation_id, u)
    conversation = conversation_store.rename_conversation(db, conversation, payload.title)
    return conversation_store.conversation_out(conversation)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = _owned_conversation(db, conversation_id, u)
    conversation_store.delete_conversation(db, conversation)


@router.post("/conversations/{conversation_id}/archive")
def archive_conversation(conversation_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = _owned_conversation(db, conversation_id, u)
    conversation = conversation_store.archive_conversation(db, conversation)
    return conversation_store.conversation_out(conversation)


@router.post("/conversations/{conversation_id}/messages")
def post_message(
    conversation_id: int, payload: MessageIn, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)
):
    enforce_rate_limit(request, "career-agent-message", limit=20, window=60)
    conversation = _owned_conversation(db, conversation_id, u)
    result = agent_service.handle_message(db, u, conversation, payload.message)
    return result


# ---------------------------------------------------------------------------
# Actions / confirmation model (spec sections 4, 18, 26, 30)
# ---------------------------------------------------------------------------


@router.get("/pending-actions")
def pending_actions(u: User = Depends(current_user), db: Session = Depends(get_db)):
    items = actions_service.list_pending_actions(db, u.id)
    return {"pending_actions": [actions_service.action_out(a) for a in items]}


@router.post("/actions/{action_id}/confirm")
def confirm_action(action_id: int, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    enforce_rate_limit(request, "career-agent-action-confirm", limit=30, window=60)
    try:
        action = actions_service.get_owned_action(db, u.id, action_id)
    except actions_service.ActionNotFoundError as exc:
        raise HTTPException(404, "Action not found") from exc
    conversation = None
    if action.conversation_id:
        try:
            conversation = conversation_store.get_owned_conversation(db, u.id, action.conversation_id)
        except conversation_store.ConversationNotFoundError:
            conversation = None
    try:
        return agent_service.confirm_pending_action(db, u, conversation, action_id)
    except actions_service.ActionNotPendingError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/actions/{action_id}/reject")
def reject_action(action_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        action = actions_service.get_owned_action(db, u.id, action_id)
    except actions_service.ActionNotFoundError as exc:
        raise HTTPException(404, "Action not found") from exc
    conversation = None
    if action.conversation_id:
        try:
            conversation = conversation_store.get_owned_conversation(db, u.id, action.conversation_id)
        except conversation_store.ConversationNotFoundError:
            conversation = None
    try:
        return agent_service.reject_pending_action(db, u, conversation, action_id)
    except actions_service.ActionNotPendingError as exc:
        raise HTTPException(409, str(exc)) from exc


# ---------------------------------------------------------------------------
# Preferences (spec section 14/21)
# ---------------------------------------------------------------------------


class PreferencesIn(BaseModel):
    proactive_enabled: bool | None = None
    frequency: str | None = Field(default=None, max_length=20)
    quiet_hours_start: int | None = Field(default=None, ge=0, le=23)
    quiet_hours_end: int | None = Field(default=None, ge=0, le=23)
    channels: str | None = Field(default=None, max_length=120)


@router.get("/preferences")
def get_preferences(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return agent_preferences.get_or_default(db, u.id)


@router.patch("/preferences")
def put_preferences(payload: PreferencesIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        record = agent_preferences.upsert(db, u.id, payload.model_dump())
    except agent_preferences.InvalidPreferenceError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {field: getattr(record, field) for field in agent_preferences.FIELDS}


# ---------------------------------------------------------------------------
# Career brief & dashboard (spec sections 22, 31)
# ---------------------------------------------------------------------------


@router.get("/brief")
def get_brief(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return brief_service.build_brief(db, u)
