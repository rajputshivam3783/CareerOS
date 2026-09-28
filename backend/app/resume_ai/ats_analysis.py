"""ATS (Applicant Tracking System) analysis.

Same deterministic, no-model posture as scoring.py. "ATS readability"
claims here are the well-documented, vendor-agnostic risk factors
(multi-column layouts, missing standard sections, skills buried only
in prose rather than a dedicated list) — this does not claim to
emulate any specific vendor's actual parser, which this project has no
way to verify against.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.resume_ai.extraction import NOT_FOUND
from app.resume_ai.normalization import NormalizedProfile, action_verb_count, quantified_bullet_count


@dataclass
class ATSAnalysis:
    readability: str  # "good" | "fair" | "at_risk"
    structure: dict
    keyword_placement: dict
    formatting_risks: list[str]
    skill_visibility: dict
    job_title_alignment: dict | None
    action_verbs: dict
    achievement_statements: dict
    notes: list[str] = field(default_factory=list)


def analyze(
    profile: NormalizedProfile, *, has_tables_or_columns: bool | None, target_job_title: str | None = None
) -> ATSAnalysis:
    expected_sections = ["summary", "skills", "experience", "education"]
    structure = {
        "expected_sections": expected_sections,
        "present": [s for s in expected_sections if s not in profile.missing_sections],
        "missing": [s for s in expected_sections if s in profile.missing_sections],
    }

    formatting_risks = []
    if has_tables_or_columns is True:
        formatting_risks.append("Multi-column or table-based layout detected — some ATS parsers read columns out of order")
    elif has_tables_or_columns is None:
        formatting_risks.append("Table/column layout risk couldn't be determined for this file format (PDF layout isn't analyzed)")
    if profile.name == NOT_FOUND:
        formatting_risks.append("Candidate name wasn't detected on the first lines — ATS systems often key off this")
    if not formatting_risks:
        formatting_risks.append("No major formatting risks detected")

    # Keyword placement: are the detected technical skills also
    # reinforced in experience/project text, or only listed once in a
    # skills block? Recruiters and many ATS relevance rankings weight
    # a skill mentioned in context higher than a bare list entry.
    body_text = " ".join(profile.experience_entries + profile.project_entries).lower()
    reinforced = [s for s in profile.technical_skills if s in body_text]
    listed_only = [s for s in profile.technical_skills if s not in body_text]
    keyword_placement = {
        "reinforced_in_experience_or_projects": reinforced,
        "listed_only_in_skills_section": listed_only,
        "note": (
            "Skills only listed once are still detected by keyword-matching ATS, but showing them in context "
            "(a bullet that uses the skill) tends to rank higher with recruiters reviewing a shortlist."
            if listed_only
            else "Every detected skill also appears in experience or project descriptions."
        ),
    }

    skill_visibility = {
        "technical_skill_count": len(profile.technical_skills),
        "soft_skill_count": len(profile.soft_skills),
        "has_dedicated_skills_section": "skills" not in profile.missing_sections,
    }

    job_title_alignment = None
    if target_job_title:
        title_tokens = {t.lower() for t in target_job_title.split() if len(t) > 2}
        resume_text = " ".join(profile.experience_entries + [profile.summary]).lower()
        aligned_tokens = sorted(t for t in title_tokens if t in resume_text)
        job_title_alignment = {
            "target_title": target_job_title,
            "aligned_tokens": aligned_tokens,
            "aligned": bool(aligned_tokens),
            "note": (
                f"Resume text references {len(aligned_tokens)} of {len(title_tokens)} word(s) from the target job title."
                if title_tokens
                else "Target job title had no comparable words to check."
            ),
        }

    verbs_used = action_verb_count(profile.experience_entries)
    action_verbs = {
        "count_in_experience": verbs_used,
        "note": "Strong action verbs (Led, Built, Improved, ...) detected in experience bullets" if verbs_used else "No strong action verbs detected — consider starting bullets with one",
    }

    quantified = quantified_bullet_count(profile.experience_entries + profile.project_entries)
    total_bullets = len(profile.experience_entries) + len(profile.project_entries)
    achievement_statements = {
        "quantified_count": quantified,
        "total_bullets": total_bullets,
        "note": (
            f"{quantified} of {total_bullets} bullet(s) include a measurable number"
            if total_bullets
            else "No experience or project bullets to evaluate"
        ),
    }

    risk_signals = len(structure["missing"]) + (1 if has_tables_or_columns else 0) + (1 if not profile.technical_skills else 0)
    if risk_signals == 0:
        readability = "good"
    elif risk_signals <= 2:
        readability = "fair"
    else:
        readability = "at_risk"

    return ATSAnalysis(
        readability=readability,
        structure=structure,
        keyword_placement=keyword_placement,
        formatting_risks=formatting_risks,
        skill_visibility=skill_visibility,
        job_title_alignment=job_title_alignment,
        action_verbs=action_verbs,
        achievement_statements=achievement_statements,
        notes=[
            "This analysis checks well-documented, vendor-agnostic ATS risk factors — it does not emulate any "
            "specific ATS vendor's actual parsing behavior."
        ],
    )
