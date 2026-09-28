"""V6 Career AI — a natural-language narration layer.

Important boundary: this never decides eligibility or computes the
match score itself — it only narrates numbers and reasons that
eligibility()/match_score()/skill_gap() already produced
deterministically. The optional LLM call is instructed to use only the
facts it's given, so a wrong or hallucinated eligibility claim can't
originate here even if the model tries to "helpfully" embellish.

Fully optional: with no API key configured, `generate_advice` returns
a clear template-built summary from the same data, so "Career AI"
still works out of the box with zero external dependencies at runtime
— only richer, more natural phrasing needs the key.
"""

import logging

from app.core.config import settings
from app.models.domain import Job, Profile

logger = logging.getLogger("careeros.career_ai")


def _fallback_advice(job: Job, eligibility_result: dict, match_result: dict, skill_gap_result: dict) -> str:
    lines = []

    verdict = eligibility_result.get("eligible")
    if verdict is True:
        lines.append(f"You look eligible for {job.title} at {job.organization} based on your profile.")
    elif verdict is False:
        lines.append(
            f"Your profile doesn't currently match the stated eligibility for {job.title} — "
            "review the reasons below before applying."
        )
    else:
        lines.append(
            f"Eligibility for {job.title} couldn't be fully confirmed from your profile — "
            "check the official notification for the exact criteria."
        )

    lines.append(f"Match score: {match_result.get('score')}/100.")

    learn = skill_gap_result.get("learn") or []
    if learn:
        lines.append("Skills worth building for this role: " + ", ".join(learn[:5]) + ".")
    else:
        lines.append("No major skill gaps detected against the listed requirements.")

    return " ".join(lines)


def generate_advice(
    job: Job,
    profile: Profile | None,
    eligibility_result: dict,
    match_result: dict,
    skill_gap_result: dict,
) -> dict:
    fallback = _fallback_advice(job, eligibility_result, match_result, skill_gap_result)

    if not settings.career_ai_anthropic_api_key:
        return {"advice": fallback, "source": "template"}

    try:
        import anthropic

        client = anthropic.Anthropic(
            api_key=settings.career_ai_anthropic_api_key,
            timeout=settings.career_ai_timeout_seconds,
        )
        prompt = (
            "You are a career guidance assistant for an Indian job platform. Using ONLY the "
            "structured facts below — do not invent eligibility criteria, dates, or numbers not "
            "present here — write a short, encouraging, 3-4 sentence plain-language summary for "
            "the candidate. If the eligibility verdict is None, be explicit that it's unclear and "
            "must be confirmed against the official notification; never state a firm yes/no the "
            "data doesn't support.\n\n"
            f"Job: {job.title} at {job.organization} ({job.job_type})\n"
            f"Eligibility verdict: {eligibility_result.get('eligible')}\n"
            f"Eligibility reasons: {eligibility_result.get('reasons')}\n"
            f"Match score: {match_result.get('score')}/100\n"
            f"Matched skills: {match_result.get('matched_skills')}\n"
            f"Skills to learn: {skill_gap_result.get('learn')}\n"
        )
        response = client.messages.create(
            model=settings.career_ai_model,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text").strip()
        return {"advice": text or fallback, "source": "anthropic"}
    except Exception:
        logger.exception("Career AI narrative call failed — falling back to template summary")
        return {
            "advice": fallback,
            "source": "template",
            "note": "AI narrative temporarily unavailable; showing a rule-based summary instead.",
        }
