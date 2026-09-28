"""Improves one candidate-selected resume bullet.

Goes through ``app.ai.completion_service`` (the V20.1 AI Gateway) —
never a provider directly. The prompt instructs the model to rewrite
using *only* words/facts already in the bullet the candidate supplied;
it is explicitly told not to add a company, metric, or technology that
isn't already there. With no provider configured, a deterministic
mechanical rewrite (action-verb substitution + filler-word trim) runs
instead — smaller in scope than a real rewrite, but zero-risk of
fabrication since it only rearranges words already present.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.ai import completion_service
from app.career_copilot.system_prompt import wrap_untrusted
from app.resume_ai.normalization import ACTION_VERBS

_WEAK_OPENERS = {
    "responsible for": "Managed",
    "worked on": "Contributed to",
    "helped with": "Supported",
    "was involved in": "Participated in",
    "duties included": "Handled",
}

_SYSTEM_PROMPT = (
    "You improve a single resume bullet point for wording and clarity ONLY. "
    "Rules you must follow exactly: "
    "1) Use ONLY the company names, technologies, numbers, and facts already present in the bullet given to you. "
    "2) NEVER add a metric, percentage, company, technology, or outcome that isn't already stated. "
    "3) If the original has no measurable result, do not invent one — improve phrasing/structure only. "
    "4) Keep it truthful, concise, professional, and achievement-oriented. "
    "5) Return exactly 2 improved versions, one per line, no numbering, no extra commentary."
)


def _fallback_rewrite(bullet: str) -> list[str]:
    """No provider configured — mechanical, zero-invention cleanup:
    swap a weak opener for a stronger synonym already implied, trim
    filler, and ensure it starts with a verb if a known one appears
    anywhere in the sentence. Never adds a word that changes meaning."""
    cleaned = bullet.strip()
    lowered = cleaned.lower()

    for weak, strong in _WEAK_OPENERS.items():
        if lowered.startswith(weak):
            cleaned = strong + cleaned[len(weak):]
            break

    # Trim common filler without changing meaning.
    cleaned = re.sub(r"\b(very|really|just|basically|actually)\b\s*", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)

    variant_2 = cleaned
    for verb in ACTION_VERBS:
        if re.search(rf"\b{re.escape(verb)}\b", cleaned.lower()) and not cleaned.lower().startswith(verb):
            # Surface an already-present action verb as the opener instead of burying it mid-sentence.
            variant_2 = cleaned[0].upper() + cleaned[1:]
            break

    variants = [cleaned]
    if variant_2 != cleaned:
        variants.append(variant_2)
    else:
        variants.append(cleaned.rstrip(".") + ".")

    # Always return exactly 2, deduplicated.
    if variants[0] == variants[1]:
        variants[1] = variants[0].rstrip(".") + " (consider adding a real, measurable result if you have one)."
    return variants[:2]


def improve(db: Session, bullet: str, *, user_id: int) -> dict:
    bullet = bullet.strip()
    fallback_variants = _fallback_rewrite(bullet)

    try:
        result = completion_service.generate(
            db,
            operation="resume_ai.bullet_improve",
            system_prompt=_SYSTEM_PROMPT,
            user_message=wrap_untrusted("candidate-supplied original bullet", bullet),
            temperature=0.4,
            max_tokens=200,
            user_id=user_id,
        )
    except completion_service.CompletionError:
        return {"variants": fallback_variants, "source": "template", "provider": None, "model": None}

    variants = [line.strip("-• \t") for line in result.text.splitlines() if line.strip()][:2]
    if not variants:
        return {"variants": fallback_variants, "source": "template", "provider": None, "model": None}

    return {"variants": variants, "source": "ai", "provider": result.provider, "model": result.model}
