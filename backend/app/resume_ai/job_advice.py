"""Job-specific resume advice: missing/recommended keywords, skills to
highlight, projects/experience to highlight, sections to improve.

Same boundary as ``app.services.career_ai`` — this module never
decides anything itself. Everything it reports is already computed by
``job_match.py`` and ``skill_gap.py``; the optional AI call only
narrates those facts into readable prose, explicitly instructed to
introduce nothing new. With no provider configured, a structured
dict (no prose) is returned instead — still complete, just not
narrated in a sentence.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai import completion_service
from app.resume_ai.job_match import JobMatchResult
from app.resume_ai.normalization import NormalizedProfile
from app.resume_ai.skill_gap import SkillGapResult

_SYSTEM_PROMPT = (
    "You write a short (4-6 sentence) plain-language resume advice summary for a specific job application. "
    "Use ONLY the structured facts given to you below — do not invent skills, experience, employers, or numbers "
    "not present in the facts. Be specific and actionable: which real projects/experience lines to lead with, "
    "which missing keywords to genuinely add ONLY IF the candidate actually has that skill, and which resume "
    "sections need work. If a fact is absent, say so plainly rather than guessing."
)


def _structured_advice(
    profile: NormalizedProfile, match: JobMatchResult, gap: SkillGapResult
) -> dict:
    sections_to_improve = []
    if match.keywords.score < 60:
        sections_to_improve.append("Skills — add genuinely-held missing keywords listed below")
    if match.experience.score < 50:
        sections_to_improve.append("Experience — add more detail or align existing bullets to this role")
    if not profile.project_entries:
        sections_to_improve.append("Projects — consider adding relevant project work")

    return {
        "missing_keywords": gap.missing_skills,
        "recommended_keywords": gap.recommended_skills,
        "skills_to_highlight": match.matched_skills,
        "projects_to_highlight": profile.project_entries[:3],
        "experience_to_highlight": profile.experience_entries[:3],
        "sections_to_improve": sections_to_improve or ["No specific section flagged — overall alignment looks reasonable"],
    }


def build(
    db: Session, profile: NormalizedProfile, match: JobMatchResult, gap: SkillGapResult, *, user_id: int
) -> dict:
    structured = _structured_advice(profile, match, gap)

    facts = (
        f"Overall match: {match.overall}%. Skills {match.skills.score}%, Experience {match.experience.score}%, "
        f"Education {match.education.score}%, Keywords {match.keywords.score}%.\n"
        f"Matched skills: {match.matched_skills}\n"
        f"Missing skills (job wants, resume doesn't show): {gap.missing_skills}\n"
        f"Recommended skills to learn: {gap.recommended_skills}\n"
        f"Transferable skill bridges: {gap.transferable_skills}\n"
        f"Sections flagged for improvement: {structured['sections_to_improve']}\n"
        f"Top experience lines: {profile.experience_entries[:3]}\n"
        f"Top project lines: {profile.project_entries[:3]}\n"
    )

    try:
        result = completion_service.generate(
            db,
            operation="resume_ai.job_advice",
            system_prompt=_SYSTEM_PROMPT,
            user_message=facts,
            temperature=0.4,
            max_tokens=350,
            user_id=user_id,
        )
        return {**structured, "narrative": result.text.strip(), "source": "ai", "provider": result.provider, "model": result.model}
    except completion_service.CompletionError:
        return {**structured, "narrative": None, "source": "structured_only", "provider": None, "model": None}
