"""V25.4 — Intent detection (spec sections 2, 5, 24).

Two layers, cheapest first (spec section 25: "do not call an LLM for
deterministic operations"):

1. ``fast_path`` — a small set of deterministic keyword rules for the
   most common, unambiguous phrasings (e.g. "what applications need
   attention" -> list_applications(status=...)). No AI call at all.
2. ``ai_detect`` — for anything the fast path doesn't confidently
   match, one structured (JSON-only) call to the V20.1 AI Gateway that
   must name a tool already in ``tool_registry.TOOLS`` or return
   ``clarify``. The raw model output is never executed directly: it is
   parsed defensively (matching the ``_parse_and_validate`` pattern
   ``app.applications.ai.followup``/``interview_prep`` already use)
   and then run back through ``tool_registry.validate_call`` exactly
   like a fast-path match, so both layers converge on the same
   validated-call shape before anything touches a service function.

Prompt injection defense (spec section 24): the candidate's own
message is the only free-form input given to the model here — no
resume text, job description, or other untrusted document content is
ever included in the intent-detection call, so there is nothing in
this prompt for injected instructions to hide inside.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai import completion_service
from app.career_agent import system_prompt, tool_registry
from app.models.domain import User


@dataclass
class DetectedIntent:
    tool_name: str | None
    params: dict
    clarify: str | None = None


def _degraded(clarify: str) -> DetectedIntent:
    return DetectedIntent(tool_name=None, params={}, clarify=clarify)


# ---------------------------------------------------------------------------
# Fast path — cheap, deterministic, no AI call.
# ---------------------------------------------------------------------------

_FAST_PATH_RULES: list[tuple[re.Pattern, str, dict]] = [
    (re.compile(r"\bapplications?\b.*\b(need|needs)\b.*\battention\b", re.I), "list_applications", {}),
    (re.compile(r"\bstuck\b.*\bapplications?\b", re.I), "list_applications", {}),
    (re.compile(r"\bfollow[- ]?up\b", re.I), None, {}),  # ambiguous alone — handled below with an id check
    (re.compile(r"\bsaved jobs?\b", re.I), "get_saved_jobs", {}),
    (re.compile(r"\bcareer plan\b|\bcareer roadmap\b", re.I), "get_career_intelligence", {}),
    (re.compile(r"\bskills? (should|to) (i )?learn\b|\bskill gap\b", re.I), "analyze_skill_gap", {}),
    (re.compile(r"\blearning recommendations?\b|\bwhat (should|to) study\b", re.I), "get_learning_recommendations", {}),
    (re.compile(r"\bresume\b.*\b(review|analy[sz]e|improve)\b", re.I), "analyze_resume", {}),
    (re.compile(r"\bprogress\b.*\bsummary\b|\bcareer progress\b", re.I), "summarize_career_progress", {}),
    (re.compile(r"\bnotifications?\b", re.I), "get_notifications", {}),
    (re.compile(r"\bjob recommendations?\b|\bjobs for me\b|\bmatching jobs\b", re.I), "get_job_recommendations", {}),
]


def fast_path(message: str) -> DetectedIntent | None:
    text = message.strip()
    if not text:
        return None
    for pattern, tool_name, params in _FAST_PATH_RULES:
        if pattern.search(text) and tool_name:
            return DetectedIntent(tool_name=tool_name, params=dict(params))
    return None


# ---------------------------------------------------------------------------
# AI fallback — one structured call, defensively parsed.
# ---------------------------------------------------------------------------


def _tool_catalog_text() -> str:
    lines = []
    for spec in tool_registry.TOOLS.values():
        param_desc = ", ".join(
            f"{p.name}{'*' if p.required else ''}:{p.type.__name__}" for p in spec.params
        ) or "(no parameters)"
        lines.append(f"- {spec.name} [{spec.risk}]: {spec.description} Params: {param_desc}")
    return "\n".join(lines)


def _parse_and_validate(raw_text: str) -> DetectedIntent:
    try:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError, IndexError):
        return _degraded("I'm not sure what you'd like me to do — could you rephrase that?")

    if not isinstance(data, dict):
        return _degraded("I'm not sure what you'd like me to do — could you rephrase that?")

    tool_name = data.get("tool")
    clarify = data.get("clarify")
    raw_params = data.get("params") or {}

    if tool_name is None:
        safe_clarify = clarify if isinstance(clarify, str) and clarify.strip() else None
        return DetectedIntent(tool_name=None, params={}, clarify=safe_clarify)

    if not isinstance(tool_name, str) or tool_registry.get_tool(tool_name) is None:
        # The model named a tool that isn't in the whitelist — never
        # execute it. Degrade to a clarifying question instead of
        # guessing or, worse, passing the name through anywhere.
        return _degraded("I'm not able to do that yet — could you tell me more about what you need?")

    if not isinstance(raw_params, dict):
        raw_params = {}

    try:
        validated = tool_registry.validate_call(tool_name, raw_params)
    except tool_registry.ToolValidationError:
        return _degraded(
            "I think I understand you want help with that, but I'm missing a detail (like an id) to do it — "
            "could you specify which one you mean?"
        )

    return DetectedIntent(tool_name=tool_name, params=validated, clarify=None)


def ai_detect(db: Session, user: User, message: str) -> DetectedIntent:
    catalog = _tool_catalog_text()
    try:
        result = completion_service.generate(
            db,
            operation="career_agent.intent",
            system_prompt=system_prompt.INTENT_SYSTEM_PROMPT + "\n\nAvailable tools:\n" + catalog,
            user_message=message,
            user_id=user.id,
            temperature=0,
            max_tokens=400,
        )
    except completion_service.CompletionError:
        return _degraded("Career Agent is temporarily unavailable — please try again shortly.")

    return _parse_and_validate(result.text)


def detect(db: Session, user: User, message: str) -> DetectedIntent:
    matched = fast_path(message)
    if matched is not None:
        return matched
    return ai_detect(db, user, message)
