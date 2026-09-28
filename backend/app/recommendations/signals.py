"""BEHAVIOR SIGNALS (read side) — turns a candidate's
``BehaviorSignalAggregate`` rows (written by app.recommendations.events)
into one ``BehaviorSignals`` snapshot the matching/scoring/explanation
stages can use, without any of them needing to know how signals are
stored or decayed.

USER CONTROLS: when personalization is turned off
(``RecommendationPreference.personalization_enabled is False``), the
caller (app.recommendations.service) never calls ``build`` at all —
the "behavior" scoring component simply reports itself unavailable,
exactly like any other missing signal (see
app.recommendations.scoring's redistribution rule), and no learned
data is read or applied for that request.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import BehaviorSignalAggregate
from app.recommendations.job_features import JobFeatures

# Below this, a signal is treated as noise, not a real preference —
# keeps `explain()` from ever saying "you frequently viewed X roles"
# off the back of a single one-off impression.
_MEANINGFUL_SCORE_THRESHOLD = 0.15


@dataclass
class BehaviorSignals:
    scores: dict[tuple[str, str], float] = field(default_factory=dict)  # (signal_type, signal_key) -> score

    def score_for(self, signal_type: str, signal_key: str | None) -> float:
        if not signal_key:
            return 0.0
        return self.scores.get((signal_type, signal_key.strip().lower()), 0.0)

    def top_positive(self, signal_type: str, limit: int = 3) -> list[str]:
        items = [
            (key, score) for (stype, key), score in self.scores.items()
            if stype == signal_type and score >= _MEANINGFUL_SCORE_THRESHOLD
        ]
        items.sort(key=lambda pair: pair[1], reverse=True)
        return [key for key, _score in items[:limit]]


def build(db: Session, user_id: int) -> BehaviorSignals:
    rows = db.scalars(select(BehaviorSignalAggregate).where(BehaviorSignalAggregate.user_id == user_id)).all()
    scores = {(row.signal_type, row.signal_key): row.score for row in rows}
    return BehaviorSignals(scores=scores)


def job_affinity(behavior: BehaviorSignals, job: JobFeatures) -> tuple[float, list[str]]:
    """Combines every signal key relevant to `job` into one 0-100
    affinity score plus the plain-English reasons behind it (used by
    matching._behavior_match and explanations.explain). Purely a
    lookup + weighted sum over already-computed aggregates — no new
    decay/weight logic here, that all lives in app.recommendations.events."""
    contributions: list[tuple[str, float]] = []

    company_score = behavior.score_for("company", job.organization)
    if company_score:
        contributions.append((f"you've engaged with roles at {job.organization} before", company_score))

    location_score = behavior.score_for("location", job.location)
    if location_score:
        contributions.append((f"you've shown interest in {job.location} roles", location_score))

    job_type_score = behavior.score_for("job_type", job.job_type)
    if job_type_score:
        contributions.append((f"you've engaged with other {job.job_type} opportunities", job_type_score))

    skill_hits = [s for s in job.skills if behavior.score_for("skill", s) > 0]
    skill_score = sum(behavior.score_for("skill", s) for s in skill_hits)
    if skill_hits:
        shown = ", ".join(sorted(skill_hits)[:3])
        contributions.append((f"you've engaged with {shown} roles before", skill_score))

    role_keywords = [w for w in (job.title or "").lower().split() if behavior.score_for("role_keyword", w) > 0]
    role_score = sum(behavior.score_for("role_keyword", w) for w in role_keywords)
    if role_keywords:
        shown = ", ".join(sorted(set(role_keywords))[:2])
        contributions.append((f"you frequently view {shown} roles", role_score))

    total = sum(score for _reason, score in contributions)
    reasons = [reason for reason, score in sorted(contributions, key=lambda p: p[1], reverse=True) if score > 0]

    if not contributions:
        return 0.0, []

    # SCORE_CLAMP bounds a single aggregate at [-5, 10]; several
    # positive signals can stack, so normalize the combined total
    # against a generous ceiling (25 = roughly "five strong signals")
    # rather than the single-signal clamp, then clip to [0, 100].
    normalized = max(0.0, min(100.0, (total / 25.0) * 100.0))
    return normalized, reasons[:3]
