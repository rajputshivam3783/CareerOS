"""Content-hash cache for generative outputs (bullet rewrites,
summaries, project suggestions, job advice narration) — the "avoid
unnecessary LLM calls" cost control the V20.2 spec asks for.

Keyed by (user_id, kind, context_key) where context_key is a stable
hash of exactly the inputs that would change the output (the bullet
text, the target role, the job id + resume state). Same inputs -> same
cache hit -> zero additional provider calls. A resume re-upload or a
different target naturally produces a different context_key, so the
cache can never serve stale content silently.

Only the generated *output* is stored — never the prompt sent to the
model, per AI_RESUME_PRIVACY.md's "don't store raw prompts containing
personal data unnecessarily".
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import ResumeAISuggestion


def make_context_key(*parts: str) -> str:
    joined = "\u241f".join(parts)  # unit separator — avoids accidental collisions between differently-split inputs
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


def get_cached(db: Session, *, user_id: int, kind: str, context_key: str) -> ResumeAISuggestion | None:
    return db.execute(
        select(ResumeAISuggestion)
        .where(
            ResumeAISuggestion.user_id == user_id,
            ResumeAISuggestion.kind == kind,
            ResumeAISuggestion.context_key == context_key,
        )
        .order_by(ResumeAISuggestion.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def store(
    db: Session, *, user_id: int, kind: str, context_key: str, content: str, provider: str | None, model: str | None
) -> ResumeAISuggestion:
    row = ResumeAISuggestion(
        user_id=user_id, kind=kind, context_key=context_key, content=content, provider=provider, model=model
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
