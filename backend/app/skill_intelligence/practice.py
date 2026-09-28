"""Practice, project, and certification-category recommendations.

Every recommendation here is derived from data that already exists —
the unified skill gap (Phase 1), assessment weak topics
(app.skill_intelligence.assessments), and admin-curated resources
(Phase 2) — never generated fresh by an AI call. Project and
certification recommendations reuse LearningResource
(resource_type="project" / "certification") rather than inventing new
project briefs or certification names; a skill with no admin-curated
project/certification resource yet is reported as such, not padded
with a fabricated one (AI_SAFETY.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import AssessmentAttempt, LearningResource, PracticeRecommendation, Skill, SkillAssessment
from app.skill_intelligence import assessments, gap as gap_engine, resources


@dataclass
class PracticeSuggestion:
    skill: Skill
    recommendation_type: str  # practice_questions/coding_problems/projects/mock_interviews/revision
    reason: str
    priority_score: int
    project: LearningResource | None = None  # populated only for recommendation_type == "projects"


def generate(db: Session, user_id: int, target_job_id: int | None = None) -> list[PracticeSuggestion]:
    """Compute (and persist, upserting on user+skill+type) practice
    recommendations from the candidate's current weak areas."""

    gap_result = gap_engine.compute(db, user_id, target_job_id)
    suggestions: list[PracticeSuggestion] = []

    by_canonical = {item.canonical_name: item for item in gap_result.priority_skills + gap_result.recommended_skills}

    # Skills the candidate has actually taken an assessment for, even
    # if they're not part of the current job/career gap — weak-topic
    # revision recommendations shouldn't disappear just because no
    # target job is selected right now.
    assessed_skill_ids = {
        row.skill_id
        for row in db.scalars(
            select(SkillAssessment).join(
                AssessmentAttempt, AssessmentAttempt.assessment_id == SkillAssessment.id
            ).where(AssessmentAttempt.user_id == user_id, AssessmentAttempt.status == "completed")
        )
    }
    for sid in assessed_skill_ids:
        s = db.get(Skill, sid)
        if s and s.canonical_name not in by_canonical:
            weak_topics = assessments.weak_topics_for_user(db, user_id, sid)
            if weak_topics:
                suggestions.append(
                    PracticeSuggestion(
                        skill=s,
                        recommendation_type="revision",
                        reason=f"Your assessment attempts show weak topics in {s.display_name}: {', '.join(weak_topics[:3])}.",
                        priority_score=50,
                    )
                )

    for name, item in by_canonical.items():
        skill = db.scalar(select(Skill).where(Skill.canonical_name == name))
        if not skill:
            continue

        if "weak_interview_performance" in item.source_signals:
            suggestions.append(
                PracticeSuggestion(
                    skill=skill,
                    recommendation_type="mock_interviews",
                    reason=f"Flagged as a weak area in your most recent mock interview — practice with another mock interview once you've reviewed {skill.display_name}.",
                    priority_score=item.priority_score,
                )
            )

        weak_topics = assessments.weak_topics_for_user(db, user_id, skill.id)
        if weak_topics:
            suggestions.append(
                PracticeSuggestion(
                    skill=skill,
                    recommendation_type="revision",
                    reason=f"Your assessment attempts show weak topics in {skill.display_name}: {', '.join(weak_topics[:3])}.",
                    priority_score=item.priority_score,
                )
            )
        elif item.priority_score >= 60:
            suggestions.append(
                PracticeSuggestion(
                    skill=skill,
                    recommendation_type="practice_questions",
                    reason=item.reason,
                    priority_score=item.priority_score,
                )
            )

        project_resources = [
            r for r in resources.published_for_skill(db, skill.id) if r.resource_type == "project"
        ]
        if project_resources:
            suggestions.append(
                PracticeSuggestion(
                    skill=skill,
                    recommendation_type="projects",
                    reason=f"A verified project brief is available for {skill.display_name} to build hands-on evidence for your resume.",
                    priority_score=max(item.priority_score - 10, 0),
                    project=project_resources[0],
                )
            )

    suggestions.sort(key=lambda s: s.priority_score, reverse=True)

    # Persist (idempotent per user+skill+type — replace the reason/score
    # if it already exists rather than accumulating duplicates).
    existing = {
        (r.skill_id, r.recommendation_type): r
        for r in db.scalars(
            select(PracticeRecommendation).where(
                PracticeRecommendation.user_id == user_id, PracticeRecommendation.status == "pending"
            )
        )
    }
    for s in suggestions:
        key = (s.skill.id, s.recommendation_type)
        row = existing.get(key)
        if row:
            row.reason = s.reason
            row.priority_score = s.priority_score
        else:
            db.add(
                PracticeRecommendation(
                    user_id=user_id,
                    skill_id=s.skill.id,
                    recommendation_type=s.recommendation_type,
                    reason=s.reason,
                    priority_score=s.priority_score,
                    status="pending",
                )
            )
    db.commit()
    return suggestions


def certification_guidance(db: Session, skill_ids: list[int]) -> dict[str, list[LearningResource]]:
    """Verified certification-type resources per skill, grouped by
    canonical skill name. A skill with none returns an empty list —
    never a fabricated certification name or "required" claim."""

    out: dict[str, list[LearningResource]] = {}
    for sid in skill_ids:
        skill = db.get(Skill, sid)
        if not skill:
            continue
        certs = [r for r in resources.published_for_skill(db, sid) if r.resource_type == "certification"]
        out[skill.canonical_name] = certs
    return out
