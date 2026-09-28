"""Deterministic, rule-based resume scoring.

Every score here is a plain function of countable facts about the
resume (section presence, length, bullet counts, action-verb hits,
quantified-achievement hits, contact-info presence) with a fixed,
documented point allocation — never a model's opinion. This is what
"Do NOT produce arbitrary scores. Every score must have an
explanation." means structurally: each score function returns not
just a number but the list of reasons that produced it, and the same
inputs always produce the same score.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.resume_ai.extraction import NOT_FOUND
from app.resume_ai.normalization import NormalizedProfile, action_verb_count, quantified_bullet_count


@dataclass
class ScoreResult:
    score: int  # 0-100
    max_score: int = 100
    reasons: list[str] = field(default_factory=list)


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))


def contact_info_score(profile: NormalizedProfile) -> ScoreResult:
    points, reasons = 0, []
    checks = [
        (profile.name != NOT_FOUND, 25, "Name detected", "Name not detected — make sure it's the first line of the resume"),
        (profile.email != NOT_FOUND, 25, "Email address found", "No email address found"),
        (profile.phone != NOT_FOUND, 25, "Phone number found", "No phone number found"),
        (
            profile.linkedin != NOT_FOUND or profile.github != NOT_FOUND or profile.portfolio != NOT_FOUND,
            25,
            "At least one professional link found (LinkedIn/GitHub/portfolio)",
            "No LinkedIn, GitHub, or portfolio link found",
        ),
    ]
    for present, weight, good_reason, bad_reason in checks:
        if present:
            points += weight
            reasons.append(good_reason)
        else:
            reasons.append(bad_reason)
    return ScoreResult(score=_clamp(points), reasons=reasons)


def skills_score(profile: NormalizedProfile) -> ScoreResult:
    technical = len(profile.technical_skills)
    soft = len(profile.soft_skills)
    reasons = []

    # 8 points per recognized technical skill up to 10 skills (80 pts),
    # plus up to 20 for soft skills (5 each, up to 4) — technical
    # weighted higher since it's what job matching scores against.
    technical_points = min(80, technical * 8)
    soft_points = min(20, soft * 5)

    reasons.append(f"{technical} technical skill(s) recognized" if technical else "No recognized technical skills found")
    reasons.append(f"{soft} soft skill(s) explicitly stated" if soft else "No soft skills explicitly stated")
    if technical < 5:
        reasons.append("Fewer than 5 technical skills detected — consider adding more if genuinely applicable")

    return ScoreResult(score=_clamp(technical_points + soft_points), reasons=reasons)


def experience_score(profile: NormalizedProfile) -> ScoreResult:
    entries = profile.experience_entries
    reasons = []
    if not entries:
        return ScoreResult(score=0, reasons=["No experience section found or it's empty"])

    verbs = action_verb_count(entries)
    quantified = quantified_bullet_count(entries)

    length_points = min(40, len(entries) * 4)
    verb_points = min(30, verbs * 6)
    quant_points = min(30, quantified * 6)

    reasons.append(f"{len(entries)} experience line(s) found")
    reasons.append(f"{verbs} line(s) start with or contain a strong action verb" if verbs else "No strong action verbs detected in experience bullets")
    reasons.append(f"{quantified} line(s) include a measurable number" if quantified else "No quantified achievements (numbers, %, counts) found in experience")

    return ScoreResult(score=_clamp(length_points + verb_points + quant_points), reasons=reasons)


def education_score(profile: NormalizedProfile) -> ScoreResult:
    entries = profile.education_entries
    if not entries:
        return ScoreResult(score=0, reasons=["No education section found or it's empty"])
    points = min(100, 60 + len(entries) * 20)
    return ScoreResult(score=_clamp(points), reasons=[f"{len(entries)} education entry/entries found"])


def project_score(profile: NormalizedProfile) -> ScoreResult:
    entries = profile.project_entries
    if not entries:
        return ScoreResult(score=0, reasons=["No projects section found or it's empty"])
    verbs = action_verb_count(entries)
    reasons = [f"{len(entries)} project line(s) found"]
    length_points = min(60, len(entries) * 10)
    verb_points = min(40, verbs * 10)
    if verbs == 0:
        reasons.append("Project descriptions don't use strong action verbs")
    return ScoreResult(score=_clamp(length_points + verb_points), reasons=reasons)


def keyword_coverage_score(profile: NormalizedProfile, target_keywords: list[str] | None = None) -> ScoreResult:
    """Without a target job, this measures general keyword breadth
    (technical skill count against a reasonable baseline of 12). With
    a target job's keyword list supplied, it measures actual coverage
    of those specific keywords — see job_match.py, which calls this
    with the job's own vocabulary for the job-specific version."""
    if target_keywords:
        found = [k for k in target_keywords if k in profile.technical_skills]
        pct = (len(found) / len(target_keywords)) * 100 if target_keywords else 0
        return ScoreResult(
            score=_clamp(pct),
            reasons=[f"{len(found)} of {len(target_keywords)} target keyword(s) found: {', '.join(found) or 'none'}"],
        )

    baseline = 12
    pct = (len(profile.technical_skills) / baseline) * 100
    return ScoreResult(
        score=_clamp(pct),
        reasons=[f"{len(profile.technical_skills)} technical keyword(s) detected against a general baseline of {baseline}"],
    )


def achievement_strength_score(profile: NormalizedProfile) -> ScoreResult:
    all_entries = profile.experience_entries + profile.project_entries + profile.achievements
    if not all_entries:
        return ScoreResult(score=0, reasons=["No experience, project, or achievement lines to evaluate"])
    quantified = quantified_bullet_count(all_entries)
    pct = (quantified / len(all_entries)) * 100
    reasons = [f"{quantified} of {len(all_entries)} achievement-bearing line(s) include a measurable number"]
    if pct < 30:
        reasons.append("Fewer than 30% of lines are quantified — adding numbers/percentages strengthens impact")
    return ScoreResult(score=_clamp(pct), reasons=reasons)


def content_quality_score(profile: NormalizedProfile) -> ScoreResult:
    """Rolls up structural completeness: how many of the expected
    sections are actually present and non-empty."""
    expected = ["summary", "skills", "experience", "education", "projects", "certifications", "achievements", "languages"]
    present = len(expected) - len(profile.missing_sections)
    pct = (present / len(expected)) * 100
    return ScoreResult(
        score=_clamp(pct),
        reasons=[f"{present} of {len(expected)} expected resume sections present: missing {profile.missing_sections or 'none'}"],
    )


def ats_compatibility_score(profile: NormalizedProfile, has_tables_or_columns: bool | None) -> ScoreResult:
    """A conservative subset of full ATS analysis (see ats_analysis.py)
    — the single headline number. Penalizes table/column layouts
    (common ATS parsing failure point), missing contact info, and a
    missing skills section, since those three are the most reliable,
    well-documented ATS risk factors that can be checked without
    guessing at a specific vendor's parser behavior. ``None`` (layout
    risk couldn't be determined for this file format) is treated as
    neutral — no penalty, no credit — rather than assumed safe.
    """
    reasons = []
    points = 100

    if has_tables_or_columns is True:
        points -= 25
        reasons.append("Resume uses tables/columns — some ATS parsers misread multi-column layouts")
    elif has_tables_or_columns is False:
        reasons.append("No table/multi-column layout detected")
    else:
        reasons.append("Table/column layout risk could not be determined for this file format")

    if profile.email == NOT_FOUND or profile.phone == NOT_FOUND:
        points -= 20
        reasons.append("Missing email or phone — many ATS systems require both to create a candidate record")
    else:
        reasons.append("Email and phone both present")

    if not profile.technical_skills:
        points -= 20
        reasons.append("No dedicated, parseable skills detected — ATS keyword matching relies on this")
    else:
        reasons.append(f"{len(profile.technical_skills)} parseable skill keyword(s) detected")

    if profile.summary == NOT_FOUND:
        points -= 10
        reasons.append("No summary/objective section — many ATS-adjacent recruiter dashboards surface this first")

    return ScoreResult(score=_clamp(points), reasons=reasons)


def resume_quality_score(component_scores: dict[str, ScoreResult]) -> ScoreResult:
    """The single headline number: a weighted blend of every other
    score. Weights sum to 1.0 and are fixed/documented here, not
    tuned per-resume, so the same component scores always produce the
    same overall number."""
    weights = {
        "content_quality": 0.15,
        "ats_compatibility": 0.15,
        "skills": 0.20,
        "experience": 0.25,
        "education": 0.10,
        "project": 0.10,
        "achievement_strength": 0.05,
    }
    total = sum(component_scores[key].score * weight for key, weight in weights.items() if key in component_scores)
    reasons = [f"Weighted blend of {len(weights)} component scores: " + ", ".join(f"{k} {int(w * 100)}%" for k, w in weights.items())]
    return ScoreResult(score=_clamp(total), reasons=reasons)
