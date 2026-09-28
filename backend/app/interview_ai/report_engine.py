"""V20.4 — Interview report engine.

Numeric scores are a **pure, deterministic aggregation** of every
MockInterviewEvaluation already shown to the candidate during the
session (`aggregate_scores` — plain averages, no AI, fully
unit-testable) — the report can never disagree with the per-question
breakdown it summarizes, and "Do NOT generate arbitrary scores"
applies here exactly as it does in evaluation_engine.py.

Only the narrative text (`summary`, `communication_feedback`,
`recommended_topics`, `next_steps`) is AI-generated, and the prompt
hands the model the aggregated numbers/lists directly with an explicit
instruction not to introduce new scores or facts — it narrates, it
doesn't judge.

Skill-gap integration (V20.2): when the session has a job, missing/weak
skills from `app.resume_ai.skill_gap` are merged into `technical_gaps`
alongside per-answer weaknesses on technical questions — see
SKILL_GAP_INTEGRATION note in AI_INTERVIEW_ARCHITECTURE.md.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.ai import completion_service
from app.career_copilot.system_prompt import wrap_untrusted
from app.interview_ai.context_builder import InterviewContext
from app.models.domain import MockInterviewEvaluation, MockInterviewQuestion

_TECHNICAL_CATEGORIES = {
    "programming", "dsa", "oop", "dbms", "os", "computer_networks", "system_design",
    "cloud", "sql", "data_science", "machine_learning", "coding", "job_requirement", "resume_project",
}


def aggregate_scores(rows: list[tuple[MockInterviewQuestion, MockInterviewEvaluation]]) -> dict:
    """`rows` = [(question, evaluation), ...] for every answered
    question in the session, in order. Pure function — no I/O, no AI."""
    if not rows:
        return {"overall_score": 0, "technical_score": 0, "communication_score": 0,
                "problem_solving_score": 0, "role_fit_score": 0, "confidence_score": 0}

    def avg(values: list[int]) -> int:
        return round(sum(values) / len(values)) if values else 0

    overall = avg([e.overall_score for _, e in rows])
    technical = avg([round((e.correctness_score + e.technical_depth_score) / 2) for _, e in rows])
    communication = avg([round((e.clarity_score + e.communication_score + e.structure_score) / 3) for _, e in rows])
    problem_solving = avg([round((e.completeness_score + e.correctness_score) / 2) for _, e in rows])
    role_fit = avg([e.relevance_score for _, e in rows])
    confidence = avg([e.confidence_score for _, e in rows])

    return {
        "overall_score": overall, "technical_score": technical, "communication_score": communication,
        "problem_solving_score": problem_solving, "role_fit_score": role_fit, "confidence_score": confidence,
    }


def collect_technical_gaps(rows: list[tuple[MockInterviewQuestion, MockInterviewEvaluation]], ctx: InterviewContext) -> list[str]:
    gaps: list[str] = []
    for question, evaluation in rows:
        if question.category in _TECHNICAL_CATEGORIES and evaluation.overall_score < 60:
            gaps.extend(json.loads(evaluation.missing_json or "[]")[:2])
    if ctx.skill_gap:
        gaps.extend(f"{skill} (required by target job, not on resume)" for skill in ctx.skill_gap.missing_skills[:5])
    # de-dupe while preserving order
    seen = set()
    out = []
    for g in gaps:
        if g not in seen:
            seen.add(g)
            out.append(g)
    return out[:10]


_SYSTEM_PROMPT = """You are writing the narrative sections of a completed mock interview report. You are given \
the FINAL, ALREADY-COMPUTED aggregate scores and lists of strengths/weaknesses/gaps collected during the \
interview — these are facts, not for you to re-judge or contradict. Do not introduce a new score, and do not \
claim anything about the candidate that isn't in the given data.

Write:
- summary: 3-5 sentences overall summary of how the interview went, referencing the actual scores/topics given.
- communication_feedback: 2-3 sentences specifically about communication style/clarity, grounded in the given data.
- recommended_topics: a list of specific topics to study next, grounded in the technical_gaps given.
- next_steps: a short list of concrete next actions for interview preparation.

Respond with ONLY a JSON object: {"summary": "...", "communication_feedback": "...", "recommended_topics": ["..."], "next_steps": ["..."]}"""


def _fallback_narrative(aggregates: dict, strengths: list[str], weaknesses: list[str], gaps: list[str]) -> dict:
    return {
        "summary": (
            f"Overall score: {aggregates['overall_score']}/100 across this session. "
            f"Technical: {aggregates['technical_score']}, Communication: {aggregates['communication_score']}, "
            f"Problem solving: {aggregates['problem_solving_score']}, Role fit: {aggregates['role_fit_score']}. "
            "(AI narrative unavailable — this summary was generated deterministically from your scores.)"
        ),
        "communication_feedback": f"Communication score: {aggregates['communication_score']}/100.",
        "recommended_topics": gaps[:5] or ["No specific gaps identified from this session."],
        "next_steps": ["Review the question-by-question feedback below.", "Retake this interview type once you've addressed the noted gaps."],
    }


def generate_report_narrative(
    db: Session, *, aggregates: dict, strengths: list[str], weaknesses: list[str], technical_gaps: list[str], user_id: int,
) -> dict:
    facts = (
        f"Aggregate scores: {json.dumps(aggregates)}\n"
        f"Collected strengths: {strengths[:10]}\n"
        f"Collected weaknesses: {weaknesses[:10]}\n"
        f"Technical gaps: {technical_gaps}"
    )
    try:
        result = completion_service.generate(
            db, operation="interview_ai.report", system_prompt=_SYSTEM_PROMPT,
            user_message=wrap_untrusted("computed interview aggregates (facts, do not contradict)", facts),
            user_id=user_id, max_tokens=600, temperature=0.4,
        )
        import re
        text = result.text.strip()
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        data = json.loads(text)
        if not all(k in data for k in ("summary", "communication_feedback", "recommended_topics", "next_steps")):
            raise ValueError("missing keys")
        return {
            "summary": str(data["summary"])[:2000],
            "communication_feedback": str(data["communication_feedback"])[:1000],
            "recommended_topics": [str(t)[:200] for t in data["recommended_topics"]][:10],
            "next_steps": [str(t)[:200] for t in data["next_steps"]][:10],
        }
    except (completion_service.CompletionError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return _fallback_narrative(aggregates, strengths, weaknesses, technical_gaps)
