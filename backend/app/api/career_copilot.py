"""V20.3 — AI Career Copilot APIs.

Reuses, never rewrites: ``current_user``/``admin_guard``
(app.core.security / app.api.admin), ``get_public_job``
(app.api.platform), ``enforce_rate_limit`` (app.core.rate_limit), and
every V20.1 conversation-storage function (app.ai.conversation_manager)
— conversations/messages live in the exact same ``ai_conversations`` /
``ai_messages`` tables V20.1's own `/ai/conversations/*` endpoints use,
tagged ``context_type="career_copilot"`` so the two stay distinguishable
without a second table.

Authorization (see AI_SAFETY.md): every candidate-facing endpoint here
operates only on the calling user's own data — there is no parameter
anywhere that accepts another user's id. `/career-copilot/usage` is
admin-only and returns aggregated operational metadata (provider,
latency, cost), never conversation content.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai import conversation_manager, observability
from app.api.admin import guard as admin_guard
from app.api.platform import get_public_job
from app.career_copilot import action_plan, assistant, career_preferences, context_engine, government_guidance, job_recommendations, roadmap
from app.core.rate_limit import enforce_rate_limit
from app.core.security import current_user
from app.db.session import get_db
from app.models.domain import AIConversation, CareerActionItem, User

router = APIRouter()

CONTEXT_TYPE = "career_copilot"


def _owned_conversation(db: Session, conversation_id: int, u: User) -> AIConversation:
    conversation = db.get(AIConversation, conversation_id)
    if not conversation or conversation.user_id != u.id or conversation.context_type != CONTEXT_TYPE:
        raise HTTPException(404, "Conversation not found")
    return conversation


def _owned_action_item(db: Session, item_id: int, u: User) -> CareerActionItem:
    item = db.get(CareerActionItem, item_id)
    if not item or item.user_id != u.id:
        raise HTTPException(404, "Action item not found")
    return item


# ---------------------------------------------------------------------------
# Context & preferences
# ---------------------------------------------------------------------------


@router.get("/career-copilot/context")
def get_context(u: User = Depends(current_user), db: Session = Depends(get_db)):
    context = context_engine.build(db, u.id)
    return {
        "profile": context.profile,
        "preferences": context.preferences,
        "resume_summary": context.resume_summary,
        "saved_jobs": context.saved_jobs,
        "applications": context.applications,
        "upcoming_deadlines": context.upcoming_deadlines,
        "skill_intelligence": context.skill_intelligence,
        "unknown_fields": context.unknown_fields,
    }


class PreferencesIn(BaseModel):
    target_role: str | None = Field(default=None, max_length=160)
    preferred_industry: str | None = Field(default=None, max_length=160)
    preferred_location: str | None = Field(default=None, max_length=160)
    preferred_work_mode: str | None = Field(default=None, max_length=30)
    experience_level: str | None = Field(default=None, max_length=40)
    target_companies: str | None = None
    salary_expectation: str | None = Field(default=None, max_length=120)
    preferred_skills: str | None = None
    learning_goals: str | None = None
    career_goal: str | None = None


@router.get("/career-copilot/preferences")
def get_preferences(u: User = Depends(current_user), db: Session = Depends(get_db)):
    prefs = career_preferences.get(db, u.id)
    if not prefs:
        return {field: None for field in career_preferences.FIELDS}
    return {field: getattr(prefs, field) for field in career_preferences.FIELDS}


@router.put("/career-copilot/preferences")
def put_preferences(payload: PreferencesIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    prefs = career_preferences.upsert(db, u.id, payload.model_dump())
    return {field: getattr(prefs, field) for field in career_preferences.FIELDS}


# ---------------------------------------------------------------------------
# Conversations (reuses V20.1 storage, tagged context_type="career_copilot")
# ---------------------------------------------------------------------------


class ConversationStartIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    job_id: int | None = None


@router.get("/career-copilot/conversations")
def list_conversations(u: User = Depends(current_user), db: Session = Depends(get_db)):
    conversations = conversation_manager.list_conversations(db, user_id=u.id, context_type=CONTEXT_TYPE)
    return {"conversations": [_conversation_out(c) for c in conversations]}


@router.post("/career-copilot/conversations")
def start_conversation(payload: ConversationStartIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    import uuid

    session_key = f"career-copilot:{u.id}:{uuid.uuid4().hex}"
    conversation = conversation_manager.get_or_create_conversation(db, session_key=session_key, user_id=u.id, context_type=CONTEXT_TYPE)
    if payload.title:
        conversation = conversation_manager.rename_conversation(db, conversation, payload.title)
    return _conversation_out(conversation)


@router.patch("/career-copilot/conversations/{conversation_id}")
def rename_conversation(conversation_id: int, payload: RenameIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = _owned_conversation(db, conversation_id, u)
    conversation = conversation_manager.rename_conversation(db, conversation, payload.title)
    return _conversation_out(conversation)


@router.delete("/career-copilot/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = _owned_conversation(db, conversation_id, u)
    conversation_manager.delete_conversation(db, conversation)


@router.post("/career-copilot/conversations/{conversation_id}/clear")
def clear_conversation(conversation_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = _owned_conversation(db, conversation_id, u)
    conversation = conversation_manager.clear_conversation(db, conversation)
    return _conversation_out(conversation)


@router.get("/career-copilot/conversations/{conversation_id}/messages")
def get_messages(conversation_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = _owned_conversation(db, conversation_id, u)
    history = conversation_manager.get_history(db, conversation.id)
    return {
        "conversation": _conversation_out(conversation),
        "messages": [
            {"id": m.id, "role": m.role, "content": m.content, "provider": m.provider, "model": m.model, "created_at": m.created_at.isoformat()}
            for m in history
        ],
    }


@router.post("/career-copilot/conversations/{conversation_id}/messages")
def post_message(conversation_id: int, payload: MessageIn, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    enforce_rate_limit(request, "career-copilot-message", limit=30, window=60)
    conversation = _owned_conversation(db, conversation_id, u)

    conversation_manager.add_message(db, conversation, role="user", content=payload.message)

    try:
        result = assistant.send_message(db, conversation, payload.message, user_id=u.id, job_id=payload.job_id)
    except assistant.CopilotError as exc:
        # Same rationale as app/api/ai.py's completion endpoint: the
        # underlying provider error is already logged server-side
        # (completion_service.generate -> observability.record_event)
        # before CopilotError is raised — don't re-expose raw provider/
        # SDK error text to the candidate. See AI_SECURITY_AUDIT.md.
        raise HTTPException(503, "Career Copilot is currently unavailable. Please try again shortly.") from exc

    reply = conversation_manager.add_message(
        db, conversation, role="assistant", content=result["text"], provider=result["provider"], model=result["model"]
    )
    return {
        "reply": {"id": reply.id, "role": "assistant", "content": reply.content, "provider": reply.provider, "model": reply.model, "created_at": reply.created_at.isoformat()},
        "context_used": result["context_used"],
    }


def _conversation_out(conversation: AIConversation) -> dict:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "message_count": conversation.message_count,
        "has_summary": bool(conversation.summary),
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Recommendations, roadmap, action plan, government guidance (deterministic — no AI call)
# ---------------------------------------------------------------------------


@router.get("/career-copilot/recommendations")
def get_recommendations(limit: int = Query(default=10, ge=1, le=50), u: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"recommendations": job_recommendations.recommend(db, u.id, limit=limit)}


@router.get("/career-copilot/roadmap")
def get_roadmap(job_id: int | None = None, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if job_id:
        get_public_job(job_id, db)  # 404s if the job doesn't exist or isn't published
    return roadmap.build(db, u.id, job_id=job_id)


@router.get("/career-copilot/action-plan")
def get_action_plan(u: User = Depends(current_user), db: Session = Depends(get_db)):
    items = action_plan.generate_and_persist(db, u.id)
    return {"items": [_action_item_out(item) for item in items]}


class ActionItemStatusIn(BaseModel):
    status: str = Field(pattern="^(pending|done|dismissed)$")


@router.patch("/career-copilot/action-plan/{item_id}")
def update_action_item(item_id: int, payload: ActionItemStatusIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    item = _owned_action_item(db, item_id, u)
    item = action_plan.set_status(db, item, payload.status)
    return _action_item_out(item)


def _action_item_out(item: CareerActionItem) -> dict:
    return {
        "id": item.id, "bucket": item.bucket, "title": item.title, "reason": item.reason,
        "priority": item.priority, "source": item.source, "related_job_id": item.related_job_id,
        "status": item.status, "updated_at": item.updated_at.isoformat(),
    }


@router.get("/career-copilot/government-guidance/{job_id}")
def get_government_guidance(job_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    job = get_public_job(job_id, db)
    return government_guidance.guidance(db, u.id, job)


# ---------------------------------------------------------------------------
# AI usage (admin) — reuses V20.1 observability, filtered to career_copilot operations
# ---------------------------------------------------------------------------


@router.get("/career-copilot/usage", dependencies=[Depends(admin_guard)])
def copilot_usage(since_hours: int = Query(default=24, ge=1, le=24 * 30), db: Session = Depends(get_db)):
    summary = observability.usage_summary(db, since_hours=since_hours)
    logs = observability.recent_logs(db, limit=100)
    copilot_logs = [row for row in logs if (row.operation or "").startswith("career_copilot.")]
    return {
        "since_hours": since_hours,
        "overall_ai_usage": summary,
        "recent_career_copilot_calls": [
            {"operation": row.operation, "provider": row.provider, "model": row.model, "success": row.success, "latency_ms": row.latency_ms, "cost_estimate_usd": row.cost_estimate_usd, "created_at": row.created_at.isoformat()}
            for row in copilot_logs
        ],
    }
