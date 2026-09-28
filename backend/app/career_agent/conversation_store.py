"""V25.4 — Conversation storage (spec section 15).

CRUD for CareerAgentConversation/CareerAgentMessage. Every function
takes ``user_id`` and either creates a row owned by that user or reads
back only rows already scoped to it — there is no function here that
can be called with one user's id and return another's conversation
(spec section 34's cross-user access test targets exactly this).
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import CareerAgentConversation, CareerAgentMessage


class ConversationNotFoundError(Exception):
    pass


def create_conversation(db: Session, user_id: int, *, title: str | None = None) -> CareerAgentConversation:
    conversation = CareerAgentConversation(user_id=user_id, title=title, status="active")
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def get_owned_conversation(db: Session, user_id: int, conversation_id: int) -> CareerAgentConversation:
    conversation = db.get(CareerAgentConversation, conversation_id)
    if not conversation or conversation.user_id != user_id:
        raise ConversationNotFoundError(f"Conversation {conversation_id} not found")
    return conversation


def list_conversations(db: Session, user_id: int, *, include_archived: bool = False) -> list[CareerAgentConversation]:
    stmt = select(CareerAgentConversation).where(CareerAgentConversation.user_id == user_id)
    if not include_archived:
        stmt = stmt.where(CareerAgentConversation.status == "active")
    stmt = stmt.order_by(CareerAgentConversation.updated_at.desc())
    return db.scalars(stmt).all()


def rename_conversation(db: Session, conversation: CareerAgentConversation, title: str) -> CareerAgentConversation:
    conversation.title = title[:200]
    conversation.updated_at = datetime.utcnow()
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def archive_conversation(db: Session, conversation: CareerAgentConversation) -> CareerAgentConversation:
    conversation.status = "archived"
    conversation.updated_at = datetime.utcnow()
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def delete_conversation(db: Session, conversation: CareerAgentConversation) -> None:
    db.delete(conversation)
    db.commit()


def add_message(
    db: Session,
    conversation: CareerAgentConversation,
    *,
    role: str,
    content: str,
    provider: str | None = None,
    model: str | None = None,
    metadata: dict | None = None,
) -> CareerAgentMessage:
    message = CareerAgentMessage(
        conversation_id=conversation.id,
        role=role,
        content=content,
        provider=provider,
        model=model,
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    db.add(message)
    conversation.message_count = (conversation.message_count or 0) + 1
    conversation.updated_at = datetime.utcnow()
    db.add(conversation)
    db.commit()
    db.refresh(message)
    return message


def get_messages(db: Session, conversation_id: int, *, limit: int = 50) -> list[CareerAgentMessage]:
    stmt = (
        select(CareerAgentMessage)
        .where(CareerAgentMessage.conversation_id == conversation_id)
        .order_by(CareerAgentMessage.id.asc())
        .limit(limit)
    )
    return db.scalars(stmt).all()


def message_out(message: CareerAgentMessage) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "provider": message.provider,
        "model": message.model,
        "metadata": json.loads(message.metadata_json) if message.metadata_json else None,
        "created_at": message.created_at.isoformat(),
    }


def conversation_out(conversation: CareerAgentConversation) -> dict:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "status": conversation.status,
        "message_count": conversation.message_count,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }
