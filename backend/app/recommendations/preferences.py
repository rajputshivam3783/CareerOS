"""PERSONALIZATION — recommendation-specific preferences (RecommendationPreference).

Broader personalization signals (preferred role, location, salary,
career goals) already live in ``CareerPreference``/``Profile`` and are
read, not re-collected, by app.recommendations.candidate_features. This
module only manages the couple of settings unique to the
recommendation surface itself.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.domain import RecommendationPreference

VALID_DIVERSITY_LEVELS = {"low", "balanced", "high"}


def get_or_default(db: Session, user_id: int) -> RecommendationPreference:
    existing = db.get(RecommendationPreference, user_id)
    if existing is not None:
        return existing
    # Not yet persisted for this user — build a transient row with the
    # same defaults the column definitions declare. Those `default=`
    # values are INSERT-time (server-side/flush-time) SQLAlchemy
    # defaults, not Python-object defaults, so a plain
    # ``RecommendationPreference(user_id=user_id)`` would otherwise
    # read back as None for every boolean field until first saved.
    return RecommendationPreference(
        user_id=user_id,
        include_government=True,
        include_private=True,
        include_internships=True,
        include_apprenticeships=True,
        diversity_level="balanced",
        personalization_enabled=True,
    )


def update(
    db: Session,
    user_id: int,
    *,
    include_government: bool | None = None,
    include_private: bool | None = None,
    include_internships: bool | None = None,
    include_apprenticeships: bool | None = None,
    preferred_employment_types: list[str] | None = None,
    diversity_level: str | None = None,
    personalization_enabled: bool | None = None,
) -> RecommendationPreference:
    row = db.get(RecommendationPreference, user_id)
    if row is None:
        row = RecommendationPreference(user_id=user_id)
        db.add(row)

    if include_government is not None:
        row.include_government = include_government
    if include_private is not None:
        row.include_private = include_private
    if include_internships is not None:
        row.include_internships = include_internships
    if include_apprenticeships is not None:
        row.include_apprenticeships = include_apprenticeships
    if preferred_employment_types is not None:
        row.preferred_employment_types = ",".join(preferred_employment_types)
    if diversity_level is not None:
        if diversity_level not in VALID_DIVERSITY_LEVELS:
            raise ValueError(f"diversity_level must be one of {sorted(VALID_DIVERSITY_LEVELS)}")
        row.diversity_level = diversity_level
    if personalization_enabled is not None:
        row.personalization_enabled = personalization_enabled

    db.commit()
    db.refresh(row)
    return row


def reset_to_defaults(db: Session, user_id: int) -> RecommendationPreference:
    """USER CONTROLS — "Reset Recommendation Preferences": reverts the
    candidate's stated recommendation settings (opportunity-type
    filters, diversity level, employment-type filter, personalization
    toggle) back to their defaults. Does NOT touch learned behavioral
    data (BehaviorSignalAggregate) or the per-job feedback exclusion
    list — see app.recommendations.controls.clear_behavior_history for
    that ("Clear Recommendation History" is a distinct control)."""
    row = db.get(RecommendationPreference, user_id)
    if row is None:
        row = RecommendationPreference(user_id=user_id)
        db.add(row)
    row.include_government = True
    row.include_private = True
    row.include_internships = True
    row.include_apprenticeships = True
    row.preferred_employment_types = None
    row.diversity_level = "balanced"
    row.personalization_enabled = True
    db.commit()
    db.refresh(row)
    return row
