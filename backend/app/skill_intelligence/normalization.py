"""Resolve free-text skill names to the canonical Skill catalog.

Matching is exact, case-insensitive, against ``skills.canonical_name``
and ``skill_aliases.alias`` only — no fuzzy matching, no AI call, no
invented canonical form for something not already in the catalog. A
name that doesn't resolve is reported as unrecognized (see
``UnresolvedSkill``) rather than silently created as a new Skill row;
only an admin (via app.api.skill_intelligence admin endpoints) or the
seed catalog adds new canonical skills. This mirrors AI_SAFETY.md's
"never fabricate skills" rule.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import Skill, SkillAlias


@dataclass
class ResolvedSkill:
    input_text: str
    skill: Skill


def _lookup_map(db: Session) -> dict[str, Skill]:
    """canonical_name/alias (lowercased) -> Skill, built in one pass."""

    skills = {s.id: s for s in db.scalars(select(Skill))}
    lookup: dict[str, Skill] = {s.canonical_name.lower(): s for s in skills.values()}
    for alias in db.scalars(select(SkillAlias)):
        skill = skills.get(alias.skill_id)
        if skill is not None:
            lookup.setdefault(alias.alias.lower(), skill)
    return lookup


def resolve(db: Session, name: str) -> Skill | None:
    """Resolve a single free-text skill name to its canonical Skill,
    or None if the catalog has no matching canonical name or alias."""

    if not name or not name.strip():
        return None
    lookup = _lookup_map(db)
    return lookup.get(name.strip().lower())


def resolve_many(db: Session, names: list[str]) -> tuple[list[ResolvedSkill], list[str]]:
    """Resolve a batch of free-text skill names in one query pass.
    Returns (resolved, unrecognized) — unrecognized names are returned
    verbatim (trimmed) so the caller can surface them as "not in the
    catalog yet" rather than dropping them silently."""

    lookup = _lookup_map(db)
    resolved: list[ResolvedSkill] = []
    unrecognized: list[str] = []
    seen_skill_ids: set[int] = set()

    for raw in names:
        clean = (raw or "").strip()
        if not clean:
            continue
        skill = lookup.get(clean.lower())
        if skill is None:
            unrecognized.append(clean)
        elif skill.id not in seen_skill_ids:
            resolved.append(ResolvedSkill(input_text=clean, skill=skill))
            seen_skill_ids.add(skill.id)

    return resolved, unrecognized
