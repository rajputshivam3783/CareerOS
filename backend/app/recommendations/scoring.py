"""RECOMMENDATION SCORING & CATEGORIES — Stage 3 of the pipeline.

Deterministic weighted combination of app.recommendations.matching's
component scores into one 0-100 overall score, plus category
classification (RECOMMENDATION CATEGORIES requirement). See
RECOMMENDATION_SCORING.md for the full weight table and the
redistribution rule below.

WEIGHT REDISTRIBUTION RULE (documented, not implicit): each component
has a base weight (see ``_BASE_WEIGHTS``). If a component is
unavailable (``ComponentScore.available is False`` — no data to score
it from), its weight is *not* silently treated as zero; instead the
remaining available components' weights are scaled up proportionally
so they still sum to 100%. This means a candidate with no resume isn't
penalized by a phantom zero for "resume match" — the score is instead
an honest combination of whatever *is* known, and the missing signal
is reported (not hidden) via ``ScoreResult.unavailable_components``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.recommendations import ranking_config
from app.recommendations.job_features import JobFeatures
from app.recommendations.matching import MatchResult

# Fallback used only if app.recommendations.ranking_config is
# unreachable for some reason (defensive; ranking_config itself
# already falls back to the same documented defaults on a DB read
# failure, so this should never actually be needed in practice).
_FALLBACK_BASE_WEIGHTS: dict[str, float] = dict(ranking_config.DEFAULT_COMPONENT_WEIGHTS)


@dataclass
class ScoreResult:
    overall: int
    breakdown: dict[str, int]  # component -> 0-100, only available components
    unavailable_components: list[str]
    weights_used: dict[str, float]  # component -> effective weight (after redistribution)


def score(match: MatchResult, job: JobFeatures, db: Session | None = None, weights_config: dict[str, float] | None = None) -> ScoreResult:
    if weights_config is None:
        weights_config = ranking_config.get(db, "component_weights") if db is not None else _FALLBACK_BASE_WEIGHTS

    components = {
        "skill": match.skill,
        "resume": match.resume,
        "experience": match.experience,
        "education": match.education,
        "location": match.location,
        "career_goal": match.career_goal,
        "work_mode": match.work_mode,
        "recency": match.recency,
        "behavior": match.behavior,
        "deadline_urgency": match.deadline_urgency,
    }

    available = {name: comp for name, comp in components.items() if comp.available and comp.score is not None}
    unavailable = [name for name in components if name not in available]

    total_base_weight = sum(weights_config.get(name, 0) for name in available) or 1.0
    weights_used = {name: (weights_config.get(name, 0) / total_base_weight) * 100 for name in available}

    overall = round(sum(available[name].score * (weights_used[name] / 100) for name in available))
    breakdown = {name: available[name].score for name in available}

    return ScoreResult(
        overall=min(100, max(0, overall)),
        breakdown=breakdown,
        unavailable_components=unavailable,
        weights_used={k: round(v, 1) for k, v in weights_used.items()},
    )


@dataclass
class CategoryResult:
    primary: str
    tags: list[str] = field(default_factory=list)


def classify(score_result: ScoreResult, match: MatchResult, job: JobFeatures) -> CategoryResult:
    """RECOMMENDATION CATEGORIES: Best Match / Strong Match /
    Skill-Building Opportunity / Career Growth Opportunity / Recently
    Posted Match / Deadline Approaching. A job can carry multiple tags
    (e.g. "Strong Match" + "Deadline Approaching"); ``primary`` is the
    single most useful label to lead with, in the priority order
    below. Thresholds are fixed constants, not learned — see
    RECOMMENDATION_SCORING.md."""
    tags: list[str] = []

    skill_score = match.skill.score if match.skill.available else None
    missing_count = len(match.missing_skills)

    is_best_match = score_result.overall >= 85 and (skill_score or 0) >= 75
    is_strong_match = not is_best_match and score_result.overall >= 70
    is_skill_building = (
        skill_score is not None
        and 35 <= skill_score < 75
        and 0 < missing_count <= 4
        and score_result.overall >= 45
    )
    is_career_growth = (
        match.career_goal.available
        and (match.career_goal.score or 0) >= 60
        and match.experience.available
        and (match.experience.score or 100) < 55
    )
    is_recently_posted = match.recency.available and (match.recency.score or 0) >= 90 and score_result.overall >= 50
    deadline_days = (job.deadline - date.today()).days if job.deadline else None
    is_deadline_approaching = deadline_days is not None and 0 <= deadline_days <= 5 and score_result.overall >= 40

    if is_best_match:
        tags.append("Best Match")
    if is_strong_match:
        tags.append("Strong Match")
    if is_skill_building:
        tags.append("Skill-Building Opportunity")
    if is_career_growth:
        tags.append("Career Growth Opportunity")
    if is_recently_posted:
        tags.append("Recently Posted Match")
    if is_deadline_approaching:
        tags.append("Deadline Approaching")

    if not tags:
        tags.append("Potential Match")

    priority_order = [
        "Best Match", "Strong Match", "Skill-Building Opportunity",
        "Career Growth Opportunity", "Recently Posted Match", "Deadline Approaching", "Potential Match",
    ]
    primary = next(t for t in priority_order if t in tags)

    return CategoryResult(primary=primary, tags=tags)


def eligibility_bucket(skill_score: int | None, missing_count: int) -> str:
    """SKILL-BUILDING JOBS requirement: clearly distinguish
    Qualified/Strong Match, Potential Match, and Skill-Building
    Opportunity so candidates are never told they're eligible when
    eligibility can't be established from what's on file."""
    if skill_score is None:
        return "Potential Match"
    if skill_score >= 75 and missing_count <= 1:
        return "Qualified / Strong Match"
    if skill_score >= 40:
        return "Skill-Building Opportunity"
    return "Potential Match"
