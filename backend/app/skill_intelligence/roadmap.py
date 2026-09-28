"""Career roadmap — the full stage structure from the spec's LEARNING
PATH section: Goal -> Required Skills -> Current Level -> Skill Gaps ->
Prerequisites -> Learning Modules -> Practice -> Assessment -> Project
-> Interview Preparation -> Target Role.

Every stage is populated from data that already exists elsewhere in
V20.5 (gap.py, learning_path.py, practice.py, graph.py) plus
CareerPreference (V20.3) / Job (V1) for the goal/target-role framing —
nothing here computes anything new. This is purely a presentation-
layer composition for the roadmap visualization
(GET /api/v1/career-roadmap), not a second gap or ranking engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.domain import CareerPreference, Job, Skill, SkillAssessment
from app.skill_intelligence import gap as gap_engine
from app.skill_intelligence import learning_path, practice as practice_engine
from sqlalchemy import select


@dataclass
class RoadmapStage:
    stage: str
    summary: str
    items: list[str] = field(default_factory=list)


@dataclass
class Roadmap:
    goal: str
    stages: list[RoadmapStage]


def build(db: Session, user_id: int, target_job_id: int | None = None) -> Roadmap:
    prefs = db.get(CareerPreference, user_id)
    job = db.get(Job, target_job_id) if target_job_id else None
    goal = job.title if job else (prefs.target_role if prefs and prefs.target_role else "No target role set yet")

    gap_result = gap_engine.compute(db, user_id, target_job_id)
    draft = learning_path.build(db, user_id, target_job_id)
    suggestions = practice_engine.generate(db, user_id, target_job_id)

    required_skills = sorted({s.skill.canonical_name for s in draft.steps} | set(gap_result.matched_skills))
    coverage_pct = (
        round(100 * len(gap_result.matched_skills) / max(1, len(gap_result.matched_skills) + len(gap_result.priority_skills)), 1)
        if (gap_result.matched_skills or gap_result.priority_skills) else None
    )

    prereq_names = [s.skill.display_name for s in draft.steps if s.reason.startswith("Prerequisite for")]

    module_names = [s.skill.display_name for s in draft.steps]

    practice_items = [f"{s.skill.display_name}: {s.recommendation_type.replace('_', ' ')}" for s in suggestions[:5]]

    assessment_titles: list[str] = []
    priority_names = {i.canonical_name for i in gap_result.priority_skills}
    if priority_names:
        skill_rows = list(db.scalars(select(Skill).where(Skill.canonical_name.in_(priority_names))))
        skill_ids = [s.id for s in skill_rows]
        if skill_ids:
            assessments = list(
                db.scalars(select(SkillAssessment).where(SkillAssessment.skill_id.in_(skill_ids), SkillAssessment.status == "published"))
            )
            assessment_titles = [a.title for a in assessments]

    project_items = [f"{s.skill.display_name}: {s.project.title}" for s in suggestions if s.recommendation_type == "projects" and s.project]

    interview_prep = [item.display_name for item in gap_result.priority_skills if "weak_interview_performance" in item.source_signals]

    stages = [
        RoadmapStage("Goal", goal, []),
        RoadmapStage("Required Skills", f"{len(required_skills)} skill(s) relevant to this goal", required_skills),
        RoadmapStage("Current Level", "Skill coverage against required skills" + (f": {coverage_pct}%" if coverage_pct is not None else " (not enough data yet)"), gap_result.matched_skills),
        RoadmapStage("Skill Gaps", f"{len(gap_result.priority_skills)} priority gap(s)", [i.display_name for i in gap_result.priority_skills]),
        RoadmapStage("Prerequisites", "Prerequisite skills to learn first", prereq_names),
        RoadmapStage("Learning Modules", "Ordered sequence from your learning path", module_names),
        RoadmapStage("Practice", "Recommended practice activities", practice_items),
        RoadmapStage("Assessment", "Assessments available for your gap skills", assessment_titles),
        RoadmapStage("Project", "Verified project briefs for hands-on evidence", project_items),
        RoadmapStage("Interview Preparation", "Skills flagged by your latest mock interview", interview_prep),
        RoadmapStage("Target Role", goal, []),
    ]
    return Roadmap(goal=goal, stages=stages)
