"""Deterministic, rule-triggered resume improvement suggestions.

Every suggestion follows the AI Explanations requirement structurally:
reason, impact, priority, suggested_action are all fixed at the point
the rule fires — never generated after the fact by a model asked to
"explain this score". No model call happens in this module at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.resume_ai.extraction import NOT_FOUND
from app.resume_ai.normalization import NormalizedProfile, action_verb_count, quantified_bullet_count


@dataclass
class Recommendation:
    area: str
    reason: str
    impact: str
    priority: str  # high | medium | low
    suggested_action: str


def generate(profile: NormalizedProfile) -> list[Recommendation]:
    recs: list[Recommendation] = []

    if profile.summary == NOT_FOUND:
        recs.append(
            Recommendation(
                area="Summary",
                reason="No summary/objective section was found",
                impact="Recruiters and ATS dashboards often surface the summary first — its absence means your "
                "positioning statement is missing entirely.",
                priority="high",
                suggested_action="Add a 2-3 sentence summary stating your target role and strongest, real "
                "qualifications. See POST /resume-ai/summary for a generated starting point.",
            )
        )

    quantified = quantified_bullet_count(profile.experience_entries)
    if profile.experience_entries and quantified == 0:
        recs.append(
            Recommendation(
                area="Achievements",
                reason="None of your experience bullets include a measurable number",
                impact="Quantified achievements ('reduced load time by 30%') are consistently rated more "
                "credible and specific than unquantified claims by recruiters and hiring managers.",
                priority="high",
                suggested_action="Add real numbers (%, counts, time saved, users affected) to at least your "
                "top 2-3 experience bullets — only where you actually have or can reasonably estimate the figure.",
            )
        )

    verbs = action_verb_count(profile.experience_entries)
    if profile.experience_entries and verbs < len(profile.experience_entries) / 2:
        recs.append(
            Recommendation(
                area="Bullet points",
                reason=f"Only {verbs} of {len(profile.experience_entries)} experience line(s) start with or "
                "contain a strong action verb",
                impact="Bullets that lead with a strong verb (Led, Built, Reduced, Automated) read as more "
                "active and results-oriented than passive descriptions.",
                priority="medium",
                suggested_action="Rewrite weaker bullets to start with a strong action verb. Try "
                "POST /resume-ai/bullet-improve on individual bullets.",
            )
        )

    if not profile.technical_skills:
        recs.append(
            Recommendation(
                area="Skills",
                reason="No recognized technical skills were detected anywhere in the resume",
                impact="Keyword-based ATS filtering and recruiter search both rely heavily on a visible skills "
                "list — without one, a qualified resume can be filtered out before a human sees it.",
                priority="high",
                suggested_action="Add a dedicated Skills section listing the real technologies/tools you've used.",
            )
        )
    elif len(profile.technical_skills) < 5:
        recs.append(
            Recommendation(
                area="Skills",
                reason=f"Only {len(profile.technical_skills)} technical skill(s) detected",
                impact="A thin skills list narrows which keyword searches and ATS filters your resume can match.",
                priority="medium",
                suggested_action="If genuinely applicable, list additional tools/technologies you've actually used.",
            )
        )

    if not profile.project_entries:
        recs.append(
            Recommendation(
                area="Projects",
                reason="No projects section found",
                impact="A projects section is especially valuable for candidates with limited work experience, "
                "or to show hands-on depth with specific technologies listed in your skills.",
                priority="medium" if profile.experience_entries else "high",
                suggested_action="Add 1-3 real projects with a short description and the technologies used.",
            )
        )

    if profile.email == NOT_FOUND or profile.phone == NOT_FOUND:
        recs.append(
            Recommendation(
                area="Contact information",
                reason="Email and/or phone number wasn't detected",
                impact="Missing contact information can prevent a recruiter or ATS from creating a candidate "
                "record at all.",
                priority="high",
                suggested_action="Make sure your email and phone number are clearly listed near the top of the resume.",
            )
        )

    if len(profile.missing_sections) > 3:
        recs.append(
            Recommendation(
                area="Structure",
                reason=f"{len(profile.missing_sections)} expected sections are missing or empty: "
                f"{', '.join(profile.missing_sections)}",
                impact="A resume with many missing standard sections reads as incomplete to both ATS parsing "
                "and human reviewers.",
                priority="medium",
                suggested_action="Add clearly-labeled section headers for each section you have real content for.",
            )
        )

    if not recs:
        recs.append(
            Recommendation(
                area="Overall",
                reason="No major structural issues detected by this analysis",
                impact="The resume covers the standard expected sections with measurable content.",
                priority="low",
                suggested_action="Consider a job-specific pass — try GET /resume-ai/job-advice/{job_id} against "
                "a role you're targeting.",
            )
        )

    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(recs, key=lambda r: priority_order[r.priority])
