"""V20.1 — AI Infrastructure APIs.

Scope note (see ROADMAP.md / AI_ARCHITECTURE.md): these endpoints
expose the *foundation* layer only — provider health, conversation
memory, the prompt registry, and usage/observability. There is no
resume-specific, interview-specific, or career-copilot endpoint here;
those are later-version consumers of this layer, not part of it.

Auth split, matching existing conventions elsewhere in the API:
- /ai/health is unauthenticated (a load balancer / uptime check needs
  to hit it without credentials, same spirit as the top-level
  GET /health route in app.api.platform).
- /ai/conversations/* requires a logged-in user (app.core.security.current_user)
  — a conversation is the calling user's own memory.
- Everything else (provider status, prompt registry writes, usage,
  logs, config) is admin-only and reuses app.api.admin.guard so it
  authenticates exactly like every other admin route (shared
  X-Admin-Key or an admin-role JWT) rather than inventing a second
  admin auth mechanism.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai import completion_service, conversation_manager, observability, prompt_service
from app.ai.provider_router import PROVIDERS, provider_status
from app.api.admin import guard as admin_guard
from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.core.security import current_user
from app.db.session import get_db
from app.models.domain import AIConversation, User

router = APIRouter()


# ---------------------------------------------------------------------------
# Health (unauthenticated)
# ---------------------------------------------------------------------------


@router.get("/ai/health")
def ai_health():
    configured = [name for name, p in PROVIDERS.items() if p.is_configured()]
    return {
        "status": "ok" if configured else "no_providers_configured",
        "default_provider": settings.ai_default_provider,
        "fallback_provider": settings.ai_fallback_provider,
        "configured_providers": configured,
        "live_health": observability.live_provider_health(),
        "uptime_seconds": round(observability.process_uptime_seconds(), 1),
    }


# ---------------------------------------------------------------------------
# Provider status (admin)
# ---------------------------------------------------------------------------


@router.get("/ai/providers", dependencies=[Depends(admin_guard)])
def list_providers():
    return {"providers": provider_status()}


# ---------------------------------------------------------------------------
# Conversation (authenticated user)
# ---------------------------------------------------------------------------


class ConversationStartIn(BaseModel):
    session_key: str = Field(min_length=1, max_length=120)
    context_type: str | None = Field(default=None, max_length=60)


class ConversationMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    operation: str = Field(default="conversation", max_length=60)
    system_prompt: str | None = Field(default=None, max_length=2000)


@router.post("/ai/conversations")
def start_conversation(payload: ConversationStartIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = conversation_manager.get_or_create_conversation(
        db, session_key=payload.session_key, user_id=u.id, context_type=payload.context_type
    )
    return _conversation_out(conversation)


@router.get("/ai/conversations/{conversation_id}/messages")
def get_conversation_messages(conversation_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = _owned_conversation(db, conversation_id, u)
    history = conversation_manager.get_history(db, conversation.id)
    return {
        "conversation": _conversation_out(conversation),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "provider": m.provider,
                "model": m.model,
                "created_at": m.created_at.isoformat(),
            }
            for m in history
        ],
    }


@router.delete("/ai/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    """V20.6 AI_DATA_RETENTION fix — this generic conversation surface
    had no deletion endpoint even though the underlying primitive
    (conversation_manager.delete_conversation, which already cascades
    to every AIMessage) has existed since V20.1 and is already exposed
    on the career_copilot conversation surface that reuses the same
    tables. See AI_PRIVACY_GUIDE.md."""
    conversation = _owned_conversation(db, conversation_id, u)
    conversation_manager.delete_conversation(db, conversation)


@router.post("/ai/conversations/{conversation_id}/messages")
def post_conversation_message(
    conversation_id: int,
    payload: ConversationMessageIn,
    request: Request,
    u: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    # A completion call is far more expensive than a typical API call
    # (real money, real latency) — reuse the shared rate limiter under
    # its own bucket so one user can't runaway-loop the provider bill.
    enforce_rate_limit(request, "ai-conversation-message", limit=30, window=60)

    conversation = _owned_conversation(db, conversation_id, u)
    history = conversation_manager.get_history(db, conversation.id)
    chat_history = conversation_manager.history_as_chat_messages(history)

    conversation_manager.add_message(db, conversation, role="user", content=payload.message)

    try:
        result = completion_service.generate(
            db,
            operation=payload.operation,
            system_prompt=payload.system_prompt,
            summary=conversation.summary,
            history=chat_history,
            user_message=payload.message,
            user_id=u.id,
        )
    except completion_service.CompletionError as exc:
        # Full detail is already durably logged server-side by
        # completion_service.generate() via observability.record_event
        # (admin-visible in AIUsageLog) before this exception is even
        # raised — the client only needs to know AI is unavailable
        # right now, not the raw provider/SDK error text, which could
        # incidentally include internal error details never meant for
        # an end user. See AI_SECURITY_AUDIT.md.
        raise HTTPException(503, "AI providers are currently unavailable. Please try again shortly.") from exc

    assistant_message = conversation_manager.add_message(
        db,
        conversation,
        role="assistant",
        content=result.text,
        provider=result.provider,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )
    return {
        "reply": {
            "id": assistant_message.id,
            "role": "assistant",
            "content": assistant_message.content,
            "provider": assistant_message.provider,
            "model": assistant_message.model,
            "created_at": assistant_message.created_at.isoformat(),
        }
    }


def _owned_conversation(db: Session, conversation_id: int, u: User):
    conversation = db.get(AIConversation, conversation_id)
    if not conversation or conversation.user_id != u.id:
        raise HTTPException(404, "Conversation not found")
    return conversation


def _conversation_out(conversation) -> dict:
    return {
        "id": conversation.id,
        "session_key": conversation.session_key,
        "context_type": conversation.context_type,
        "message_count": conversation.message_count,
        "has_summary": bool(conversation.summary),
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Prompt registry (admin)
# ---------------------------------------------------------------------------


class PromptTemplateIn(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    template: str = Field(min_length=1)
    variables: list[str] | None = None
    description: str | None = Field(default=None, max_length=300)


@router.get("/ai/prompts", dependencies=[Depends(admin_guard)])
def list_prompts(db: Session = Depends(get_db)):
    templates = prompt_service.list_templates(db)
    return {
        "templates": [
            {
                "id": t.id,
                "key": t.key,
                "version": t.version,
                "active": t.active,
                "description": t.description,
                "template": t.template,
                "variables": t.variables,
                "updated_at": t.updated_at.isoformat(),
            }
            for t in templates
        ]
    }


@router.post("/ai/prompts", dependencies=[Depends(admin_guard)])
def create_prompt_version(payload: PromptTemplateIn, db: Session = Depends(get_db)):
    row = prompt_service.register_template(
        db, payload.key, payload.template, variables=payload.variables, description=payload.description
    )
    return {"id": row.id, "key": row.key, "version": row.version, "active": row.active}


# ---------------------------------------------------------------------------
# Usage / observability (admin)
# ---------------------------------------------------------------------------


@router.get("/ai/usage", dependencies=[Depends(admin_guard)])
def usage(since_hours: int = Query(default=24, ge=1, le=24 * 30), db: Session = Depends(get_db)):
    return observability.usage_summary(db, since_hours=since_hours)


@router.get("/ai/usage/logs", dependencies=[Depends(admin_guard)])
def usage_logs(
    limit: int = Query(default=50, ge=1, le=200),
    provider: str | None = None,
    success: bool | None = None,
    db: Session = Depends(get_db),
):
    logs = observability.recent_logs(db, limit=limit, provider=provider, success=success)
    return {
        "logs": [
            {
                "id": row.id,
                "service": row.service,
                "operation": row.operation,
                "provider": row.provider,
                "model": row.model,
                "used_fallback": row.used_fallback,
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "cost_estimate_usd": row.cost_estimate_usd,
                "latency_ms": row.latency_ms,
                "success": row.success,
                "error": row.error,
                "created_at": row.created_at.isoformat(),
            }
            for row in logs
        ]
    }


# ---------------------------------------------------------------------------
# Configuration (admin, read-only — no key values are ever returned)
# ---------------------------------------------------------------------------


@router.get("/ai/config", dependencies=[Depends(admin_guard)])
def get_config():
    return {
        "default_provider": settings.ai_default_provider,
        "fallback_provider": settings.ai_fallback_provider,
        "request_timeout_seconds": settings.ai_request_timeout_seconds,
        "max_retries": settings.ai_max_retries,
        "default_model": settings.ai_default_model,
        "default_temperature": settings.ai_default_temperature,
        "default_max_tokens": settings.ai_default_max_tokens,
        "max_context_tokens": settings.ai_max_context_tokens,
        "moderation_enabled": settings.ai_moderation_enabled,
        "conversation_history_max_messages": settings.ai_conversation_history_max_messages,
        "conversation_summary_trigger": settings.ai_conversation_summary_trigger,
        "provider_models": {
            "anthropic": settings.ai_anthropic_model,
            "openai": settings.ai_openai_model,
            "gemini": settings.ai_gemini_model,
            "openrouter": settings.ai_openrouter_model,
        },
    }
