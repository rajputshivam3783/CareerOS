"""Learning resource lookups.

Every row here was entered by an admin (see app.api.skill_intelligence
admin endpoints) — this module only ever reads LearningResource, never
generates or invents one. ``published_for_skill`` is the only lookup
the candidate-facing learning-path builder uses, and it deliberately
filters to ``status == "published" and is_verified``, so an
unverified/draft resource can never reach a candidate's plan.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import LearningResource


def published_for_skill(db: Session, skill_id: int) -> list[LearningResource]:
    return list(
        db.scalars(
            select(LearningResource)
            .where(
                LearningResource.skill_id == skill_id,
                LearningResource.status == "published",
                LearningResource.is_verified.is_(True),
            )
            .order_by(LearningResource.rating.desc().nulls_last())
        )
    )


def best_for_skill(db: Session, skill_id: int) -> LearningResource | None:
    """Single best verified resource for a skill, or None — "None"
    means "no verified resource yet", surfaced honestly to the
    candidate rather than substituted with anything fabricated."""

    rows = published_for_skill(db, skill_id)
    return rows[0] if rows else None
