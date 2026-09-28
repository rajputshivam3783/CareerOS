"""V24.4 — content-hash cache for recruiter-analytics AI outputs.
Same design as ``app.applications.ai.cache`` (V22.4), generalized to
``(scope_type, scope_id)`` instead of a single ``application_id`` FK —
see ``RecruiterAIInsight``'s docstring for why. Same guarantee: same
inputs -> same context_key -> cache hit -> zero additional provider
calls (cost control, spec section 14), and a pipeline/job change that
alters the underlying facts changes the fingerprint, which changes the
context_key, which is the entire "invalidation" mechanism (spec
section 13) — there is no separate invalidation step to get wrong.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.domain import RecruiterAIInsight


def make_context_key(kind: str, fingerprint: dict, *extra: str) -> str:
    parts = [kind, json.dumps(fingerprint, sort_keys=True, default=str), *extra]
    joined = "\u241f".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


def get_cached(db: Session, *, scope_type: str, scope_id: int, kind: str, context_key: str) -> RecruiterAIInsight | None:
    return db.scalar(
        select(RecruiterAIInsight)
        .where(
            RecruiterAIInsight.scope_type == scope_type,
            RecruiterAIInsight.scope_id == scope_id,
            RecruiterAIInsight.kind == kind,
            RecruiterAIInsight.context_key == context_key,
        )
        .order_by(RecruiterAIInsight.created_at.desc())
        .limit(1)
    )


def store(
    db: Session, *, scope_type: str, scope_id: int, kind: str, context_key: str, content: dict,
    provider: str | None, model: str | None, degraded: bool,
) -> RecruiterAIInsight:
    """Same race-safe get-or-return-existing pattern as
    ``app.applications.ai.cache.store`` (V23.5 bug fix) — two near-
    simultaneous requests for the same scope/kind/context_key can both
    miss ``get_cached`` and both reach this insert; the UNIQUE
    constraint stops the second row, and the loser returns the
    winner's row instead of raising a 500."""
    row = RecruiterAIInsight(
        scope_type=scope_type, scope_id=scope_id, kind=kind, context_key=context_key,
        content_json=json.dumps(content), provider=provider, model=model, degraded=degraded,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = get_cached(db, scope_type=scope_type, scope_id=scope_id, kind=kind, context_key=context_key)
        if existing is not None:
            return existing
        raise
    db.refresh(row)
    return row


def content_of(row: RecruiterAIInsight) -> dict:
    return json.loads(row.content_json)
