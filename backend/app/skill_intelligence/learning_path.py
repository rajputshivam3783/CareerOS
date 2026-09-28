"""Generate a personalized, ordered learning path.

Structure (per the V20.5 spec): Goal -> Required Skills -> Current
Level -> Skill Gaps -> Prerequisites -> Learning Modules -> Practice ->
Assessment -> Project -> Interview Preparation -> Target Role.

Phase 2 implements the path-building core (goal through learning
modules, i.e. an ordered, resourced skill sequence); the
Practice/Assessment/Project/Interview-Prep stages plug in during Phase
3 (app.skill_intelligence.assessments / practice) without changing
anything here — this module returns a sequence of skills, not the
final module list, so those phases only need to insert additional
step *kinds* around it, not touch the ordering logic.

Reuses app.skill_intelligence.gap (Phase 1, itself a composition of
V20.2/V20.3/V20.4) and app.skill_intelligence.graph — no separate gap
or ranking logic here.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import LearningResource, Skill
from app.skill_intelligence import gap as gap_engine
from app.skill_intelligence import graph, resources


@dataclass
class PathStep:
    skill: Skill
    reason: str  # why this skill is in the path (from the gap item, or "prerequisite for X")
    resource: LearningResource | None


@dataclass
class LearningPathDraft:
    steps: list[PathStep]
    unresourced_skill_names: list[str]  # skills in the path with no verified resource yet
    based_on: gap_engine.UnifiedSkillGapResult


def build(db: Session, user_id: int, target_job_id: int | None = None, max_priority_skills: int = 6) -> LearningPathDraft:
    """Build a draft path from the candidate's current unified skill
    gap. Order: for each priority-gap skill (highest priority first),
    walk its prerequisite chain first (nearest-first — i.e. furthest
    prerequisite learned before the skill that needs it), then the
    skill itself; duplicate skills across chains are kept at their
    first (highest-priority) position only."""

    result = gap_engine.compute(db, user_id, target_job_id)
    target_skills = [item for item in result.priority_skills][:max_priority_skills]
    if not target_skills:
        target_skills = result.recommended_skills[:max_priority_skills]

    steps: list[PathStep] = []
    seen_skill_ids: set[int] = set()
    unresourced: list[str] = []

    for item in target_skills:
        skill = db.scalar(select(Skill).where(Skill.canonical_name == item.canonical_name))
        if not skill:
            continue
        ordered = graph.learning_order(db, skill)  # prerequisites-first, target last
        for s in ordered:
            if s.id in seen_skill_ids:
                continue
            seen_skill_ids.add(s.id)
            reason = item.reason if s.id == skill.id else f"Prerequisite for {skill.display_name}"
            resource = resources.best_for_skill(db, s.id)
            if resource is None:
                unresourced.append(s.display_name)
            steps.append(PathStep(skill=s, reason=reason, resource=resource))

    return LearningPathDraft(steps=steps, unresourced_skill_names=unresourced, based_on=result)
