"""V22.4 — shared "extract a JSON object from a raw LLM response"
helper, factored out of the per-feature parse/validate functions in
narrative.py/followup.py/interview_prep.py so all three handle the
"model wrapped it in ```json fences anyway" case the same way
app.interview_ai.evaluation_engine already does.
"""

from __future__ import annotations

import json
import re


def extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def str_list(value, limit: int = 8, max_len: int = 300) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:max_len] for item in value[:limit] if str(item).strip()]
