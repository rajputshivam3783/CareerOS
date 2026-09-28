"""Skill graph traversal — prerequisites, related, advanced-version,
alternative, and complementary skills for a given canonical skill.

Pure graph lookups over SkillRelationship (see SKILL_GRAPH.md for the
seeded edges); no AI call, no inference beyond what's explicitly in the
table. ``prerequisites_for`` and ``learning_order`` are the only two
functions that do real traversal (a bounded-depth walk, cycle-safe);
everything else is a one-hop neighbor lookup.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import Skill, SkillRelationship

_MAX_PREREQ_DEPTH = 6  # generous bound; the seeded graph is at most 4 deep


@dataclass
class SkillNeighbors:
    skill: Skill
    prerequisites: list[Skill]
    related: list[Skill]
    advanced_versions: list[Skill]
    alternatives: list[Skill]
    complementary: list[Skill]


def _skills_by_id(db: Session, ids: set[int]) -> dict[int, Skill]:
    if not ids:
        return {}
    return {s.id: s for s in db.scalars(select(Skill).where(Skill.id.in_(ids)))}


def neighbors(db: Session, skill: Skill) -> SkillNeighbors:
    """One-hop neighbors of ``skill`` in every relationship direction
    that makes sense to read outward from it: prerequisites point
    *into* this skill (things you need before it), everything else
    points *out* from it."""

    incoming = list(
        db.scalars(
            select(SkillRelationship).where(
                SkillRelationship.to_skill_id == skill.id, SkillRelationship.relationship_type == "prerequisite"
            )
        )
    )
    outgoing = list(db.scalars(select(SkillRelationship).where(SkillRelationship.from_skill_id == skill.id)))

    ids = {r.from_skill_id for r in incoming} | {r.to_skill_id for r in outgoing}
    by_id = _skills_by_id(db, ids)

    def _pick(rels: list[SkillRelationship], rel_type: str, key: str) -> list[Skill]:
        out = []
        for r in rels:
            if r.relationship_type != rel_type:
                continue
            target_id = getattr(r, key)
            s = by_id.get(target_id)
            if s:
                out.append(s)
        return out

    return SkillNeighbors(
        skill=skill,
        prerequisites=_pick(incoming, "prerequisite", "from_skill_id"),
        related=_pick(outgoing, "related", "to_skill_id"),
        advanced_versions=_pick(outgoing, "advanced_version", "to_skill_id"),
        alternatives=_pick(outgoing, "alternative", "to_skill_id"),
        complementary=_pick(outgoing, "complementary", "to_skill_id"),
    )


def prerequisites_for(db: Session, skill: Skill) -> list[Skill]:
    """Full prerequisite chain for ``skill``, nearest-first, walking
    the `prerequisite` edges backward. Cycle-safe and depth-bounded —
    the seeded graph has none, but admin-added edges could
    theoretically introduce one."""

    chain: list[Skill] = []
    seen: set[int] = {skill.id}
    frontier = [skill.id]
    depth = 0

    while frontier and depth < _MAX_PREREQ_DEPTH:
        rels = list(db.scalars(select(SkillRelationship).where(SkillRelationship.to_skill_id.in_(frontier), SkillRelationship.relationship_type == "prerequisite")))
        next_ids = [r.from_skill_id for r in rels if r.from_skill_id not in seen]
        if not next_ids:
            break
        by_id = _skills_by_id(db, set(next_ids))
        for nid in next_ids:
            s = by_id.get(nid)
            if s and nid not in seen:
                chain.append(s)
                seen.add(nid)
        frontier = next_ids
        depth += 1

    return chain


def learning_order(db: Session, skill: Skill) -> list[Skill]:
    """Prerequisites in the order they should be learned (furthest
    prerequisite first, target skill last) — used by
    app.skill_intelligence gap/learning-path composition to sequence a
    path, not just list the gap."""

    chain = prerequisites_for(db, skill)
    return list(reversed(chain)) + [skill]
