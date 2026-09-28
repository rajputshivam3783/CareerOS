"""Suggests improvements to a candidate-supplied project description:
better phrasing, technical keyword surfacing, impact-oriented bullets,
and technology grouping — never inventing a technology the candidate
didn't mention in the project text they gave.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai import completion_service
from app.career_copilot.system_prompt import wrap_untrusted
from app.resume_ai.normalization import action_verb_count, quantified_bullet_count

_SYSTEM_PROMPT = (
    "You improve a resume PROJECT description. Rules you must follow exactly: "
    "1) Use ONLY the technologies and facts already stated in the project text given to you — "
    "NEVER invent a technology, library, framework, or outcome that isn't mentioned. "
    "2) Suggest better phrasing, a more impact-oriented bullet structure, and how to group the "
    "already-mentioned technologies more clearly. "
    "3) If there's no measurable outcome stated, say so explicitly rather than inventing one — you may "
    "suggest the candidate ADD a real number if they have one, but never supply a fabricated number yourself. "
    "4) Return 3-5 short bullet suggestions, one per line, no numbering, no extra commentary."
)


def _fallback_suggestions(project_text: str) -> list[str]:
    suggestions = []
    verbs = action_verb_count([project_text])
    quantified = quantified_bullet_count([project_text])

    if verbs == 0:
        suggestions.append("Start the description with a strong action verb (Built, Designed, Implemented, ...).")
    if quantified == 0:
        suggestions.append(
            "If you have a real measurable outcome (users, performance improvement, data volume), add it — "
            "don't state a number you can't back up."
        )
    if len(project_text.split()) < 15:
        suggestions.append("Expand the description — a single short sentence gives little to evaluate.")
    suggestions.append("Group the technologies you actually used into a short 'Tech: X, Y, Z' line for scanability.")
    suggestions.append("Make sure the description states what the project does and your specific role in it.")
    return suggestions[:5]


def improve(db: Session, project_text: str, *, user_id: int) -> dict:
    project_text = project_text.strip()
    fallback = _fallback_suggestions(project_text)

    try:
        result = completion_service.generate(
            db,
            operation="resume_ai.project_improve",
            system_prompt=_SYSTEM_PROMPT,
            user_message=wrap_untrusted("candidate-supplied project description", project_text),
            temperature=0.4,
            max_tokens=300,
            user_id=user_id,
        )
    except completion_service.CompletionError:
        return {"suggestions": fallback, "source": "template", "provider": None, "model": None}

    suggestions = [line.strip("-• \t") for line in result.text.splitlines() if line.strip()]
    if not suggestions:
        return {"suggestions": fallback, "source": "template", "provider": None, "model": None}
    return {"suggestions": suggestions[:5], "source": "ai", "provider": result.provider, "model": result.model}
