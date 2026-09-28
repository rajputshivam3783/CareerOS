"""AI conversation memory: session memory, user memory, history, and
summarization of older turns.

"Session memory" here means a conversation keyed by ``session_key``
(works for an anonymous caller); "user memory" means a conversation
tied to ``user_id`` once the caller is authenticated — the same
AIConversation row supports both, since user_id is nullable. Long-term
cross-conversation memory (a user profile the AI recalls across
separate threads) is intentionally not built here — flagged in
AI_ARCHITECTURE.md as a future extension point, not needed by the
provider-agnostic foundation this phase delivers.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai import prompt_service
from app.ai.provider_router import AllProvidersFailedError, complete as route_complete
from app.ai.providers.base import ChatMessage
from app.core.config import settings
from app.models.domain import AIConversation, AIMessage


def get_or_create_conversation(
    db: Session, *, session_key: str, user_id: int | None = None, context_type: str | None = None
) -> AIConversation:
    conversation = db.execute(
        select(AIConversation).where(AIConversation.session_key == session_key)
    ).scalar_one_or_none()
    if conversation:
        # A previously-anonymous session that has since logged in gets
        # attributed to the user without losing its history.
        if user_id and not conversation.user_id:
            conversation.user_id = user_id
            db.commit()
        return conversation

    conversation = AIConversation(session_key=session_key, user_id=user_id, context_type=context_type)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def get_history(db: Session, conversation_id: int) -> list[AIMessage]:
    return list(
        db.execute(
            select(AIMessage).where(AIMessage.conversation_id == conversation_id).order_by(AIMessage.created_at)
        ).scalars()
    )


def add_message(
    db: Session,
    conversation: AIConversation,
    *,
    role: str,
    content: str,
    provider: str | None = None,
    model: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> AIMessage:
    message = AIMessage(
        conversation_id=conversation.id,
        role=role,
        content=content,
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    db.add(message)
    conversation.message_count += 1
    db.add(conversation)
    db.commit()
    db.refresh(message)
    maybe_summarize(db, conversation)
    return message


def maybe_summarize(db: Session, conversation: AIConversation) -> None:
    """Once a thread passes AI_CONVERSATION_SUMMARY_TRIGGER messages,
    compress everything older than the most recent
    AI_CONVERSATION_HISTORY_MAX_MESSAGES turns into `conversation.summary`.

    Uses the configured LLM provider when available; falls back to a
    plain truncated concatenation (no API call) when no provider is
    configured or the call fails — same "always works, richer with a
    key" posture as app.services.career_ai.generate_advice.
    """
    if conversation.message_count < settings.ai_conversation_summary_trigger:
        return

    history = get_history(db, conversation.id)
    to_summarize = history[: -settings.ai_conversation_history_max_messages]
    if not to_summarize:
        return

    conversation_text = "\n".join(f"{m.role}: {m.content}" for m in to_summarize)

    try:
        prompt = prompt_service.render(db, "conversation.summarize", {"conversation_text": conversation_text[:8000]})
        result, _routed = route_complete(
            [ChatMessage(role="user", content=prompt)], temperature=0, max_tokens=200
        )
        new_summary = result.text.strip()
    except (AllProvidersFailedError, prompt_service.PromptNotFoundError, prompt_service.PromptValidationError):
        # Deterministic fallback: no model call, just compress by truncation.
        joined = " / ".join(m.content.strip().replace("\n", " ")[:80] for m in to_summarize[-5:])
        new_summary = f"(auto-condensed, no AI provider available) Earlier topics: {joined}"

    conversation.summary = (
        f"{conversation.summary}\n{new_summary}".strip() if conversation.summary else new_summary
    )
    db.add(conversation)
    db.commit()


def history_as_chat_messages(history: list[AIMessage], *, exclude_last: bool = False) -> list[ChatMessage]:
    rows = history[:-1] if exclude_last and history else history
    return [ChatMessage(role=m.role, content=m.content) for m in rows if m.role in ("user", "assistant")]


# ---------------------------------------------------------------------------
# V20.3 — AI Career Copilot. Additive functions only (nothing above this
# line is modified) — the Copilot's "Conversation History / New / Rename /
# Delete / Clear Conversation" requirements are all just conversation-list
# management on top of the AIConversation/AIMessage tables that already
# exist; there's no reason for a second conversation store, so these are
# thin, generically-useful additions to the one that's already here rather
# than something new in app.career_copilot.
# ---------------------------------------------------------------------------


def list_conversations(db: Session, *, user_id: int, context_type: str | None = None) -> list[AIConversation]:
    query = select(AIConversation).where(AIConversation.user_id == user_id).order_by(AIConversation.updated_at.desc())
    if context_type:
        query = query.where(AIConversation.context_type == context_type)
    return list(db.execute(query).scalars())


def rename_conversation(db: Session, conversation: AIConversation, title: str) -> AIConversation:
    conversation.title = title.strip()[:200] or None
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def delete_conversation(db: Session, conversation: AIConversation) -> None:
    # AIMessage.conversation_id has ondelete="CASCADE" (see app.models.
    # domain.AIMessage) — deleting the conversation row is sufficient.
    db.delete(conversation)
    db.commit()


def clear_conversation(db: Session, conversation: AIConversation) -> AIConversation:
    """Removes every message but keeps the conversation (and its id/
    title) — distinct from delete_conversation, which removes both."""
    db.execute(delete(AIMessage).where(AIMessage.conversation_id == conversation.id))
    conversation.message_count = 0
    conversation.summary = None
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation
