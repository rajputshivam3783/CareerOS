"""V20.4 — Career Copilot integration for interview reports.

Deliberately NOT a second career-recommendation engine, and does not
modify `app.career_copilot` (on the V20.4 "DO NOT TOUCH" list as V20.3
Career Copilot): this module reuses the Copilot's own
`system_prompt.SYSTEM_PROMPT` (the same grounding/hallucination-
prevention rules every Copilot chat turn already follows) and the same
`app.ai.completion_service` entry point every other AI feature in this
codebase calls, to answer exactly one question — "explain this
interview report and suggest preparation steps" — from data this
module computed itself (the report), never a new recommendation
surface.

If a real "hand this off to the live Copilot conversation" integration
is wanted later (e.g. so the explanation lives in the candidate's
existing Copilot chat thread rather than a one-off call), that's a
frontend routing choice — link to `/career-copilot?context=interview_report_id`
— not a reason to duplicate the assistant/context-engine machinery here.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.ai import completion_service
from app.career_copilot.system_prompt import SYSTEM_PROMPT as COPILOT_SYSTEM_PROMPT
from app.career_copilot.system_prompt import wrap_untrusted
from app.models.domain import MockInterviewReport

_EXPLAIN_INSTRUCTION = """\n\nADDITIONAL TASK FOR THIS TURN: The candidate just completed a mock interview. You are given their \
already-computed, final report data below as facts — do not re-score or contradict it. Explain the report in \
plain language (what the scores mean, their real strengths and weaknesses) and suggest concrete next \
preparation steps, grounded only in the report data given."""


def explain_report(db: Session, report: MockInterviewReport, *, user_id: int) -> str:
    facts = {
        "overall_score": report.overall_score, "technical_score": report.technical_score,
        "communication_score": report.communication_score, "problem_solving_score": report.problem_solving_score,
        "role_fit_score": report.role_fit_score, "confidence_score": report.confidence_score,
        "strengths": json.loads(report.strengths_json or "[]"), "weaknesses": json.loads(report.weaknesses_json or "[]"),
        "technical_gaps": json.loads(report.technical_gaps_json or "[]"),
        "recommended_topics": json.loads(report.recommended_topics_json or "[]"),
    }
    try:
        result = completion_service.generate(
            db, operation="interview_ai.copilot_explain",
            system_prompt=COPILOT_SYSTEM_PROMPT + _EXPLAIN_INSTRUCTION,
            user_message=wrap_untrusted("interview report data (facts)", json.dumps(facts)),
            user_id=user_id, max_tokens=600,
        )
        return result.text
    except completion_service.CompletionError:
        return (
            f"Your overall score was {report.overall_score}/100. Strengths: "
            f"{', '.join(facts['strengths'][:5]) or 'see the detailed report'}. Areas to work on: "
            f"{', '.join(facts['weaknesses'][:5]) or 'see the detailed report'}. "
            "(AI explanation is temporarily unavailable — this is a plain summary of your own report data.)"
        )
