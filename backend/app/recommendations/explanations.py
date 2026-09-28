"""EXPLANATIONS — every recommendation must say why (EXPLANATIONS /
NEGATIVE REASONS requirements).

Deterministic template composition over real match data — no LLM call
on the hot path (spec: "core recommendation ranking must remain
deterministic... Do NOT make recommendations dependent on an LLM
response"). V20 AI infra *may* optionally be used for prose polish per
the AI USAGE section, but that's explicitly out of scope for this
backend-core phase and is not wired in here; ``explain()`` below is
already a complete, honest explanation on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.recommendations.job_features import JobFeatures
from app.recommendations.matching import MatchResult
from app.recommendations.scoring import ScoreResult


@dataclass
class Explanation:
    summary: str
    matched_skills: list[str]
    missing_skills: list[str]
    missing_skills_in_progress: list[str]
    experience_fit: str
    location_fit: str
    career_goal_fit: str
    personalized_match: bool = False  # V21.4 — did a learned behavior signal contribute to this recommendation?
    personalization_reasons: list[str] = field(default_factory=list)  # V21.4 — "Why This Job" behavior-only clauses
    negative_reasons: list[str] = field(default_factory=list)


def explain(job: JobFeatures, match: MatchResult, score: ScoreResult) -> Explanation:
    clauses: list[str] = []
    if match.behavior.available and match.behavior_reasons:
        # BEHAVIORAL SIGNALS lead the explanation when present — this is
        # the "Recommended because you frequently viewed backend roles..."
        # case from the spec's own example. Capped at the two strongest
        # reasons so the summary doesn't turn into a raw signal dump
        # (PRIVACY: "Do not expose internal sensitive signals" — these
        # are already plain-English, never raw event counts/scores).
        clauses.extend(match.behavior_reasons[:2])
    if match.skill.available and match.matched_skills:
        shown = ", ".join(match.matched_skills[:4])
        clauses.append(f"your {shown} skill(s) match what {job.title} at {job.organization} is asking for")
    if match.location.available and match.location.score is not None and match.location.score >= 70:
        clauses.append("the role is in a location you prefer")
    if match.career_goal.available and match.career_goal.score is not None and match.career_goal.score >= 60:
        clauses.append("it lines up with your stated career goal")
    if match.deadline_urgency.available and match.deadline_urgency.score is not None and match.deadline_urgency.score >= 85:
        clauses.append("its application deadline is approaching soon")
    if match.recency.available and match.recency.score is not None and match.recency.score >= 90:
        clauses.append("it was posted very recently")

    if clauses:
        summary = f"Recommended because {', and '.join(clauses)}."
    else:
        summary = f"Included based on the overall fit signals available for {job.title} at {job.organization}."

    def _fit_label(component_score, unavailable_text: str) -> str:
        if not component_score.available or component_score.score is None:
            return unavailable_text
        return component_score.reason

    return Explanation(
        summary=summary,
        matched_skills=match.matched_skills,
        missing_skills=match.missing_skills,
        missing_skills_in_progress=match.missing_skills_in_progress,
        experience_fit=_fit_label(match.experience, "Not enough experience data on file to assess"),
        location_fit=_fit_label(match.location, "Not enough location preference data on file to assess"),
        career_goal_fit=_fit_label(match.career_goal, "No career goal on file to assess against"),
        personalized_match=match.behavior.available and bool(match.behavior_reasons),
        personalization_reasons=match.behavior_reasons,
        negative_reasons=match.negative_reasons,
    )
