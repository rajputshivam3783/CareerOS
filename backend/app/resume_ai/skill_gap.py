"""Skill gap analysis: matched, missing, weak, transferable, and
recommended skills against a target job, plus a prioritized gap list.

"Weak" and "transferable" are the two judgment calls here, so both are
defined by an explicit, inspectable rule rather than a model's
impression:

- **Weak** = the skill is in the resume's Skills list but never
  reinforced anywhere in Experience or Projects — i.e. claimed but not
  demonstrated in this resume's own text.
- **Transferable** = a missing job skill that has a curated adjacency
  to a skill the candidate *does* have (see ``_ADJACENT_SKILLS`` — a
  small, fixed, documented map, not inferred per-candidate). This is
  conservative by design: an empty/no-match result is expected and
  correct far more often than a hit.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.domain import Job
from app.resume_ai.normalization import NormalizedProfile
from app.services.career import SKILLS, job_text

# Small, fixed adjacency map between skills already in the shared
# SKILLS vocabulary — e.g. someone with Java has a head start on
# Kotlin-flavored JVM roles, someone with React has transferable UI
# fundamentals for a Next.js-heavy role. Deliberately conservative and
# symmetric-ish; extend carefully, this is a curated editorial claim,
# not a generated one.
_ADJACENT_SKILLS: dict[str, list[str]] = {
    "java": ["spring boot"],
    "spring boot": ["java"],
    "javascript": ["typescript", "react", "next.js"],
    "typescript": ["javascript", "react", "next.js"],
    "react": ["next.js", "javascript", "typescript"],
    "next.js": ["react", "javascript", "typescript"],
    "python": ["fastapi", "pandas", "machine learning"],
    "fastapi": ["python"],
    "pandas": ["python", "machine learning"],
    "machine learning": ["python", "pandas"],
    "aws": ["azure", "docker", "kubernetes"],
    "azure": ["aws", "docker", "kubernetes"],
    "docker": ["kubernetes", "aws", "azure"],
    "kubernetes": ["docker", "aws", "azure"],
    "sql": ["python", "excel", "power bi"],
    "excel": ["power bi", "sql"],
    "power bi": ["excel", "sql"],
}


@dataclass
class SkillGapResult:
    matched_skills: list[str]
    missing_skills: list[str]
    weak_skills: list[str]
    transferable_skills: dict[str, list[str]]  # missing skill -> candidate skill(s) it's adjacent to
    recommended_skills: list[str]  # missing skills, filtered to ones with real signal in the job text
    prioritized_gaps: list[dict]  # [{skill, mentions_in_job, reason}], most-mentioned first


def analyze(profile: NormalizedProfile, job: Job) -> SkillGapResult:
    text = job_text(job)
    job_skills = [s for s in SKILLS if s in text]
    resume_skills = set(profile.technical_skills)

    matched = sorted(resume_skills & set(job_skills))
    missing = sorted(set(job_skills) - resume_skills)

    body_text = " ".join(profile.experience_entries + profile.project_entries).lower()
    weak = sorted(skill for skill in matched if skill not in body_text)

    transferable: dict[str, list[str]] = {}
    for gap in missing:
        adjacent_candidates = [s for s in _ADJACENT_SKILLS.get(gap, []) if s in resume_skills]
        if adjacent_candidates:
            transferable[gap] = adjacent_candidates

    # Recommended = missing skills the candidate has no transferable
    # bridge to yet — these are the ones worth learning from closer to
    # scratch, as opposed to ones already one step away.
    recommended = [s for s in missing if s not in transferable]

    mention_counts = {skill: text.count(skill) for skill in missing}
    prioritized = sorted(
        (
            {
                "skill": skill,
                "mentions_in_job": count,
                "reason": (
                    f"Appears {count} time(s) in the job listing and isn't on the resume"
                    if count > 1
                    else "Required/preferred by the job listing and isn't on the resume"
                ),
            }
            for skill, count in mention_counts.items()
        ),
        key=lambda item: item["mentions_in_job"],
        reverse=True,
    )

    return SkillGapResult(
        matched_skills=matched,
        missing_skills=missing,
        weak_skills=weak,
        transferable_skills=transferable,
        recommended_skills=recommended,
        prioritized_gaps=prioritized,
    )
