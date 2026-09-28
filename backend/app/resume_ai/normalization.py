"""Normalizes an ``ExtractedResume`` into a stable ``NormalizedProfile``.

Handles the variation resumes actually have: different section-header
wording (already folded into one canonical set by
``extraction._SECTION_ALIASES``), duplicate/overlapping skill mentions,
common skill-name spelling variations, and sections that are simply
missing. Missing stays missing — normalization never fills a gap with
an inferred value; it only cleans up what extraction actually found.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.resume_ai.extraction import NOT_FOUND, ExtractedResume
from app.services.resume_parser import detect_skills

# Small, deliberately conservative alias map — only maps a spelling
# variation to a skill that's already in the shared SKILLS vocabulary
# (app.services.career.SKILLS), the same list job matching uses. This
# never introduces a skill concept that isn't already recognized
# elsewhere in the platform, so a normalized skill always means the
# same thing in a resume score as it does in a job match.
_SKILL_ALIASES: dict[str, str] = {
    "js": "javascript", "reactjs": "react", "react.js": "react",
    "ts": "typescript", "postgres": "sql", "postgresql": "sql", "mysql": "sql",
    "k8s": "kubernetes", "ml": "machine learning", "aws cloud": "aws",
}

# Deliberately small and generic — soft skills are inherently fuzzier
# to detect than named technologies, so this only flags terms a
# resume states outright rather than trying to infer soft skills from
# achievement language.
_SOFT_SKILLS = [
    "communication", "leadership", "teamwork", "collaboration", "problem solving",
    "problem-solving", "time management", "adaptability", "critical thinking",
    "mentoring", "stakeholder management", "public speaking", "conflict resolution",
    "attention to detail", "creativity", "decision making",
]

ACTION_VERBS = [
    "led", "built", "designed", "developed", "implemented", "launched", "created",
    "improved", "optimized", "reduced", "increased", "automated", "architected",
    "delivered", "managed", "mentored", "spearheaded", "streamlined", "drove",
    "established", "scaled", "migrated", "resolved", "coordinated",
]

_BULLET_PREFIX_RE = re.compile(r"^[\s]*[•▪●◦\-\*]\s*")


@dataclass
class NormalizedProfile:
    name: str = NOT_FOUND
    email: str = NOT_FOUND
    phone: str = NOT_FOUND
    location: str = NOT_FOUND
    github: str = NOT_FOUND
    linkedin: str = NOT_FOUND
    portfolio: str = NOT_FOUND

    summary: str = NOT_FOUND
    technical_skills: list[str] = field(default_factory=list)
    soft_skills: list[str] = field(default_factory=list)
    experience_entries: list[str] = field(default_factory=list)  # raw bullet/paragraph entries, verbatim
    education_entries: list[str] = field(default_factory=list)
    project_entries: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)

    missing_sections: list[str] = field(default_factory=list)  # canonical names that were NOT_FOUND/empty


def _clean_lines(raw: str) -> list[str]:
    lines = []
    for line in (raw or "").splitlines():
        stripped = _BULLET_PREFIX_RE.sub("", line).strip()
        if stripped:
            lines.append(stripped)
    return lines


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


def _normalize_skill_token(token: str) -> str:
    lowered = token.lower().strip()
    return _SKILL_ALIASES.get(lowered, lowered)


def _extract_technical_skills(extracted: ExtractedResume, full_text: str) -> list[str]:
    # Two sources, merged and deduped: (1) the shared SKILLS vocabulary
    # matched anywhere in the resume (same detector job matching uses,
    # so scores stay comparable), and (2) whatever the candidate's own
    # "Skills" section literally lists, comma/bullet-separated — kept
    # verbatim (normalized for aliasing/case only) so a real skill the
    # shared vocabulary doesn't yet know about isn't silently dropped.
    vocab_hits = [_normalize_skill_token(s) for s in detect_skills(full_text)]

    skills_section = extracted.sections.get("skills", "")
    section_tokens = []
    for line in _clean_lines(skills_section):
        for piece in re.split(r"[,|/]", line):
            piece = piece.strip()
            if piece and len(piece) <= 40:
                section_tokens.append(_normalize_skill_token(piece))

    return _dedupe_preserve_order(vocab_hits + section_tokens)


def _extract_soft_skills(extracted: ExtractedResume, full_text: str) -> list[str]:
    soft_section = extracted.sections.get("soft_skills", "")
    haystack = f"{soft_section}\n{full_text}".lower()
    return sorted({skill for skill in _SOFT_SKILLS if skill in haystack})


def normalize(extracted: ExtractedResume, full_text: str) -> NormalizedProfile:
    summary_text = extracted.sections.get("summary", "").strip() or NOT_FOUND

    profile = NormalizedProfile(
        name=extracted.name,
        email=extracted.email,
        phone=extracted.phone,
        location=extracted.location,
        github=extracted.github,
        linkedin=extracted.linkedin,
        portfolio=extracted.portfolio,
        summary=summary_text,
        technical_skills=_extract_technical_skills(extracted, full_text),
        soft_skills=_extract_soft_skills(extracted, full_text),
        experience_entries=_dedupe_preserve_order(_clean_lines(extracted.sections.get("experience", ""))),
        education_entries=_dedupe_preserve_order(_clean_lines(extracted.sections.get("education", ""))),
        project_entries=_dedupe_preserve_order(_clean_lines(extracted.sections.get("projects", ""))),
        certifications=_dedupe_preserve_order(_clean_lines(extracted.sections.get("certifications", ""))),
        achievements=_dedupe_preserve_order(_clean_lines(extracted.sections.get("achievements", ""))),
        languages=_dedupe_preserve_order(_clean_lines(extracted.sections.get("languages", ""))),
    )

    canonical_sections = {
        "summary": profile.summary != NOT_FOUND,
        "skills": bool(profile.technical_skills),
        "experience": bool(profile.experience_entries),
        "education": bool(profile.education_entries),
        "projects": bool(profile.project_entries),
        "certifications": bool(profile.certifications),
        "achievements": bool(profile.achievements),
        "languages": bool(profile.languages),
    }
    profile.missing_sections = [name for name, present in canonical_sections.items() if not present]

    return profile


def action_verb_count(entries: list[str]) -> int:
    text = " ".join(entries).lower()
    return sum(1 for verb in ACTION_VERBS if re.search(rf"\b{re.escape(verb)}\b", text))


def quantified_bullet_count(entries: list[str]) -> int:
    """Bullets that contain a number (%, $, or a bare count) — the
    closest deterministic proxy for "measurable achievement" without
    asking a model to judge which bullets "sound impactful"."""
    number_re = re.compile(r"\d")
    return sum(1 for entry in entries if number_re.search(entry))
