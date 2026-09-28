"""Versioned prompt template registry.

Templates live in the ``ai_prompt_templates`` table so an admin can
edit copy without a deploy (same idea as
app.services.notification_templates for notification bodies). A small
set of built-in defaults is seeded at startup — see ``seed_default_prompts`` —
so the registry is useful out of the box, exactly like notification
templates' ``DEFAULT_TEMPLATES``.

Variables use simple ``{name}`` placeholders (``str.format`` style).
``render`` validates every declared variable is supplied before
substituting, so a missing variable fails loudly with a clear message
instead of leaving a literal ``{name}`` in the prompt sent to a model.
"""

from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import AIPromptTemplate

# key -> (template, [required variables], description)
DEFAULT_PROMPTS: dict[str, tuple[str, list[str], str]] = {
    "system.default_assistant": (
        "You are the CareerOS AI assistant. Be concise, factual, and never invent "
        "job listings, deadlines, or eligibility criteria that weren't given to you.",
        [],
        "Fallback system prompt used when a caller doesn't supply its own.",
    ),
    "conversation.summarize": (
        "Summarize the following conversation in 2-3 sentences, preserving any "
        "concrete facts, decisions, or numbers mentioned. Conversation:\n\n{conversation_text}",
        ["conversation_text"],
        "Used by conversation_manager to compress old turns once a thread exceeds "
        "AI_CONVERSATION_SUMMARY_TRIGGER messages.",
    ),
}


class PromptValidationError(ValueError):
    pass


class PromptNotFoundError(LookupError):
    pass


def _placeholder_names(template: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", template))


def seed_default_prompts(db: Session) -> None:
    """Idempotent — only inserts keys that don't already have any row,
    never overwrites an admin's edits. Mirrors
    notification_templates.seed_default_templates."""
    existing_keys = {row[0] for row in db.execute(select(AIPromptTemplate.key)).all()}
    created = False
    for key, (template, variables, description) in DEFAULT_PROMPTS.items():
        if key in existing_keys:
            continue
        db.add(
            AIPromptTemplate(
                key=key,
                version=1,
                template=template,
                variables=json.dumps(variables),
                description=description,
                active=True,
            )
        )
        created = True
    if created:
        db.commit()


def get_active_template(db: Session, key: str) -> AIPromptTemplate:
    row = db.execute(
        select(AIPromptTemplate)
        .where(AIPromptTemplate.key == key, AIPromptTemplate.active.is_(True))
        .order_by(AIPromptTemplate.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise PromptNotFoundError(f"No active prompt template for key '{key}'")
    return row


def render(db: Session, key: str, variables: dict[str, str] | None = None) -> str:
    """Look up the active version of ``key`` and substitute ``variables``.

    Raises PromptNotFoundError if no active template exists for the key,
    or PromptValidationError if a variable the template requires wasn't
    supplied.
    """
    template_row = get_active_template(db, key)
    variables = variables or {}

    declared = set(json.loads(template_row.variables)) if template_row.variables else _placeholder_names(
        template_row.template
    )
    missing = declared - set(variables)
    if missing:
        raise PromptValidationError(f"Prompt '{key}' is missing required variable(s): {sorted(missing)}")

    try:
        return template_row.template.format(**variables)
    except KeyError as exc:
        raise PromptValidationError(f"Prompt '{key}' references undeclared placeholder {exc}") from exc


def register_template(
    db: Session, key: str, template: str, *, variables: list[str] | None = None, description: str | None = None
) -> AIPromptTemplate:
    """Create a new version of ``key``: deactivates the previous active
    version (kept for history/audit) and inserts the new one active."""
    declared = variables if variables is not None else sorted(_placeholder_names(template))

    latest = db.execute(
        select(AIPromptTemplate).where(AIPromptTemplate.key == key).order_by(AIPromptTemplate.version.desc()).limit(1)
    ).scalar_one_or_none()
    next_version = (latest.version + 1) if latest else 1

    if latest and latest.active:
        latest.active = False

    row = AIPromptTemplate(
        key=key,
        version=next_version,
        template=template,
        variables=json.dumps(declared),
        description=description,
        active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_templates(db: Session) -> list[AIPromptTemplate]:
    return list(db.execute(select(AIPromptTemplate).order_by(AIPromptTemplate.key, AIPromptTemplate.version.desc())).scalars())
