"""V20.4 — AI Interview & Mock Interview System API.

Reuses, never rewrites: `current_user`/`admin_guard` (app.core.security
/ app.api.admin), `get_public_job` (app.api.platform),
`enforce_rate_limit` (app.core.rate_limit), `app.ai.observability` for
the admin usage view — same conventions app.api.career_copilot already
established.

Authorization: every endpoint here operates only on the calling user's
own sessions — `_owned_session` 404s (not 403, so a session's mere
existence isn't leaked to another user) on any id that isn't both
found and owned by the caller. There is no endpoint anywhere that
accepts another user's id. Raw answer text/evaluations are never
exposed to a recruiter through this router — see AI_INTERVIEW_PRIVACY.md.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import observability
from app.api.admin import guard as admin_guard
from app.api.platform import get_public_job
from app.core.rate_limit import enforce_rate_limit
from app.core.security import current_user
from app.db.session import get_db
from app.interview_ai import (
    context_builder, copilot_bridge, evaluation_engine, followup_engine,
    question_engine, report_engine, sandbox, state_machine,
)
from app.models.domain import (
    MockInterviewAnswer, MockInterviewCodingSubmission, MockInterviewEvaluation,
    MockInterviewQuestion, MockInterviewReport, MockInterviewSession, User,
)

router = APIRouter()

INTERVIEW_TYPES = {
    "technical", "hr", "behavioral", "resume_based", "job_specific",
    "coding", "data_science", "system_design", "mixed", "custom",
}


def _owned_session(db: Session, session_id: int, u: User) -> MockInterviewSession:
    session = db.get(MockInterviewSession, session_id)
    if not session or session.user_id != u.id:
        raise HTTPException(404, "Interview session not found")
    return session


def _session_out(s: MockInterviewSession) -> dict:
    return {
        "id": s.id, "job_id": s.job_id, "interview_type": s.interview_type, "target_role": s.target_role,
        "experience_level": s.experience_level, "difficulty": s.difficulty, "duration_minutes": s.duration_minutes,
        "planned_question_count": s.planned_question_count, "focus_skills": s.focus_skills,
        "programming_language": s.programming_language, "status": s.status,
        "current_question_index": s.current_question_index, "current_difficulty": s.current_difficulty,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "paused_at": s.paused_at.isoformat() if s.paused_at else None,
        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
        "created_at": s.created_at.isoformat(),
    }


def _question_out(q: MockInterviewQuestion, answer: MockInterviewAnswer | None = None, evaluation: MockInterviewEvaluation | None = None) -> dict:
    out = {
        "id": q.id, "sequence": q.sequence, "category": q.category, "difficulty": q.difficulty,
        "question_text": q.question_text, "is_followup": q.parent_question_id is not None,
        "source": q.source, "source_detail": q.source_detail, "asked_at": q.asked_at.isoformat(),
    }
    if answer:
        out["answer"] = {"answer_text": answer.answer_text, "skipped": answer.skipped, "submitted_at": answer.submitted_at.isoformat()}
    if evaluation:
        out["evaluation"] = _evaluation_out(evaluation)
    return out


def _evaluation_out(e: MockInterviewEvaluation) -> dict:
    return {
        "overall_score": e.overall_score,
        "scores": {
            "correctness": e.correctness_score, "technical_depth": e.technical_depth_score,
            "relevance": e.relevance_score, "clarity": e.clarity_score, "communication": e.communication_score,
            "structure": e.structure_score, "confidence": e.confidence_score, "completeness": e.completeness_score,
        },
        "explanation": e.explanation,
        "strengths": json.loads(e.strengths_json), "weaknesses": json.loads(e.weaknesses_json),
        "missing": json.loads(e.missing_json), "improvement_tips": json.loads(e.improvement_tips_json),
        "stronger_example": e.stronger_example, "triggered_followup": e.triggered_followup,
        "difficulty_adjustment": e.difficulty_adjustment, "degraded": e.degraded,
    }


def _report_out(r: MockInterviewReport) -> dict:
    return {
        "id": r.id, "session_id": r.session_id, "overall_score": r.overall_score, "technical_score": r.technical_score,
        "communication_score": r.communication_score, "problem_solving_score": r.problem_solving_score,
        "role_fit_score": r.role_fit_score, "confidence_score": r.confidence_score,
        "strengths": json.loads(r.strengths_json), "weaknesses": json.loads(r.weaknesses_json),
        "technical_gaps": json.loads(r.technical_gaps_json), "communication_feedback": r.communication_feedback,
        "recommended_topics": json.loads(r.recommended_topics_json), "summary": r.summary,
        "next_steps": json.loads(r.next_steps_json), "questions_answered": r.questions_answered,
        "questions_skipped": r.questions_skipped, "generated_at": r.generated_at.isoformat(),
    }


# =============================================================================
# Setup / history
# =============================================================================

class SessionCreateIn(BaseModel):
    interview_type: str = Field(pattern="^(" + "|".join(sorted(INTERVIEW_TYPES)) + ")$")
    job_id: int | None = None
    target_role: str | None = Field(default=None, max_length=160)
    experience_level: str | None = Field(default=None, max_length=40)
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard|adaptive)$")
    duration_minutes: int = Field(default=30, ge=5, le=120)
    planned_question_count: int = Field(default=8, ge=1, le=30)
    focus_skills: str | None = None
    programming_language: str | None = Field(default=None, max_length=40)


@router.post("/interview/sessions", status_code=201)
def create_session(payload: SessionCreateIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if payload.job_id:
        get_public_job(payload.job_id, db)  # 404s if the job doesn't exist or isn't published — never a fabricated job
    if payload.interview_type == "job_specific" and not payload.job_id:
        raise HTTPException(422, "job_id is required for interview_type=job_specific")

    start_difficulty = "medium" if payload.difficulty == "adaptive" else payload.difficulty
    session = MockInterviewSession(
        user_id=u.id, job_id=payload.job_id, interview_type=payload.interview_type,
        target_role=payload.target_role, experience_level=payload.experience_level,
        difficulty=payload.difficulty, duration_minutes=payload.duration_minutes,
        planned_question_count=payload.planned_question_count, focus_skills=payload.focus_skills,
        programming_language=payload.programming_language, current_difficulty=start_difficulty,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    state_machine.transition(session, "mark_ready")
    db.commit()
    return _session_out(session)


@router.get("/interview/sessions")
def list_sessions(u: User = Depends(current_user), db: Session = Depends(get_db)):
    sessions = db.scalars(
        select(MockInterviewSession).where(MockInterviewSession.user_id == u.id).order_by(MockInterviewSession.id.desc())
    ).all()
    return {"sessions": [_session_out(s) for s in sessions]}


@router.get("/interview/history")
def interview_history(u: User = Depends(current_user), db: Session = Depends(get_db)):
    """Past interviews with their final scores, plus a simple
    improvement-over-time signal (score trend) and aggregated
    weak/strong topics across every completed session — computed
    directly from stored reports/evaluations, no AI call."""
    reports = db.execute(
        select(MockInterviewReport, MockInterviewSession)
        .join(MockInterviewSession, MockInterviewSession.id == MockInterviewReport.session_id)
        .where(MockInterviewSession.user_id == u.id)
        .order_by(MockInterviewReport.generated_at)
    ).all()

    topic_scores: dict[str, list[int]] = {}
    for _, sess in reports:
        rows = db.execute(
            select(MockInterviewQuestion, MockInterviewEvaluation)
            .join(MockInterviewAnswer, MockInterviewAnswer.question_id == MockInterviewQuestion.id)
            .join(MockInterviewEvaluation, MockInterviewEvaluation.answer_id == MockInterviewAnswer.id)
            .where(MockInterviewQuestion.session_id == sess.id)
        ).all()
        for q, e in rows:
            topic_scores.setdefault(q.category, []).append(e.overall_score)

    topic_averages = {topic: round(sum(scores) / len(scores)) for topic, scores in topic_scores.items()}
    strong_topics = sorted((t for t, s in topic_averages.items() if s >= 70), key=lambda t: -topic_averages[t])
    weak_topics = sorted((t for t, s in topic_averages.items() if s < 50), key=lambda t: topic_averages[t])

    return {
        "past_interviews": [
            {"session_id": sess.id, "interview_type": sess.interview_type, "overall_score": r.overall_score,
             "completed_at": sess.completed_at.isoformat() if sess.completed_at else None}
            for r, sess in reports
        ],
        "score_trend": [r.overall_score for r, _ in reports],
        "strong_topics": strong_topics[:10],
        "weak_topics": weak_topics[:10],
        "topic_averages": topic_averages,
    }


# =============================================================================
# Session lifecycle: start / pause / resume / restart / cancel
# =============================================================================

def _transition_or_409(db: Session, session: MockInterviewSession, action: str) -> MockInterviewSession:
    try:
        state_machine.transition(session, action)
    except state_machine.IllegalTransitionError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return session


@router.post("/interview/sessions/{session_id}/start")
def start_session(session_id: int, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    enforce_rate_limit(request, "interview-ai-generate", limit=20, window=60)
    session = _owned_session(db, session_id, u)
    _transition_or_409(db, session, "start")
    question = _create_next_question(db, session, u)
    return {"session": _session_out(session), "question": _question_out(question)}


@router.post("/interview/sessions/{session_id}/pause")
def pause_session(session_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    session = _owned_session(db, session_id, u)
    _transition_or_409(db, session, "pause")
    return _session_out(session)


@router.post("/interview/sessions/{session_id}/resume")
def resume_session(session_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    session = _owned_session(db, session_id, u)
    _transition_or_409(db, session, "resume")
    return _session_out(session)


@router.post("/interview/sessions/{session_id}/cancel")
def cancel_session(session_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    session = _owned_session(db, session_id, u)
    _transition_or_409(db, session, "cancel")
    return _session_out(session)


@router.post("/interview/sessions/{session_id}/restart", status_code=201)
def restart_session(session_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    """Restart = a fresh session with the same configuration; the
    original session (and its history/report, if any) is left
    untouched — see state_machine.restart_config."""
    original = _owned_session(db, session_id, u)
    fresh = MockInterviewSession(**state_machine.restart_config(original))
    db.add(fresh)
    db.commit()
    db.refresh(fresh)
    state_machine.transition(fresh, "mark_ready")
    db.commit()
    return _session_out(fresh)


# =============================================================================
# Questions / answers
# =============================================================================

def _create_next_question(db: Session, session: MockInterviewSession, u: User) -> MockInterviewQuestion:
    ctx = context_builder.build(db, session)
    already_asked = set(
        db.scalars(select(MockInterviewQuestion.question_text).where(MockInterviewQuestion.session_id == session.id))
    )
    picked = question_engine.generate_next_question(db, session, ctx, already_asked_text=already_asked, user_id=u.id)
    question = MockInterviewQuestion(
        session_id=session.id, sequence=session.current_question_index,
        category=picked["category"], difficulty=picked["difficulty"], question_text=picked["question_text"],
        source=picked["source"], source_detail=picked["source_detail"],
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


@router.get("/interview/sessions/{session_id}/current-question")
def get_current_question(session_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    session = _owned_session(db, session_id, u)
    question = db.scalar(
        select(MockInterviewQuestion).where(MockInterviewQuestion.session_id == session.id).order_by(MockInterviewQuestion.id.desc())
    )
    if not question:
        raise HTTPException(404, "No question has been asked yet — start the session first")
    return _question_out(question)


class AnswerIn(BaseModel):
    answer_text: str = Field(min_length=0, max_length=8000)
    skip: bool = False


@router.post("/interview/sessions/{session_id}/answer")
def submit_answer(session_id: int, payload: AnswerIn, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    enforce_rate_limit(request, "interview-ai-generate", limit=20, window=60)
    session = _owned_session(db, session_id, u)
    if session.status != "in_progress":
        raise HTTPException(409, f"Cannot submit an answer while the session is {session.status!r}")

    question = db.scalar(
        select(MockInterviewQuestion).where(MockInterviewQuestion.session_id == session.id).order_by(MockInterviewQuestion.id.desc())
    )
    if not question:
        raise HTTPException(409, "No active question for this session")

    existing = db.scalar(select(MockInterviewAnswer).where(MockInterviewAnswer.question_id == question.id))
    if existing:
        existing.answer_text = payload.answer_text
        existing.skipped = payload.skip
        answer = existing
    else:
        answer = MockInterviewAnswer(question_id=question.id, answer_text=payload.answer_text, skipped=payload.skip)
        db.add(answer)
    db.commit()
    db.refresh(answer)

    if payload.skip:
        evaluation = MockInterviewEvaluation(
            answer_id=answer.id, overall_score=0, correctness_score=0, technical_depth_score=0, relevance_score=0,
            clarity_score=0, communication_score=0, structure_score=0, confidence_score=0, completeness_score=0,
            explanation="Question skipped.", degraded=True,
        )
    else:
        ctx = context_builder.build(db, session)
        result = evaluation_engine.evaluate_answer(
            db, question_text=question.question_text, question_category=question.category,
            difficulty=question.difficulty, answer_text=payload.answer_text, ctx=ctx, user_id=u.id,
        )
        wants_followup = (not payload.skip) and followup_engine.should_follow_up(result.overall, question)
        next_difficulty = question_engine.next_difficulty(session.current_difficulty, result.overall)
        evaluation = MockInterviewEvaluation(
            answer_id=answer.id, overall_score=result.overall, correctness_score=result.scores["correctness"],
            technical_depth_score=result.scores["technical_depth"], relevance_score=result.scores["relevance"],
            clarity_score=result.scores["clarity"], communication_score=result.scores["communication"],
            structure_score=result.scores["structure"], confidence_score=result.scores["confidence"],
            completeness_score=result.scores["completeness"], explanation=result.explanation,
            strengths_json=json.dumps(result.strengths), weaknesses_json=json.dumps(result.weaknesses),
            missing_json=json.dumps(result.missing), improvement_tips_json=json.dumps(result.improvement_tips),
            stronger_example=result.stronger_example, triggered_followup=wants_followup,
            difficulty_adjustment=("increase" if next_difficulty != session.current_difficulty and result.overall >= 80
                                    else "decrease" if next_difficulty != session.current_difficulty else "same"),
            provider=result.provider, model=result.model, degraded=result.degraded,
        )
        session.current_difficulty = next_difficulty
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)

    reached_planned_count = (session.current_question_index + 1) >= session.planned_question_count
    response: dict = {"answer_saved": True, "evaluation": _evaluation_out(evaluation)}

    if evaluation.triggered_followup:
        followup_text = followup_engine.generate_followup_text(
            db, original_question=question.question_text, answer_text=payload.answer_text, user_id=u.id
        )
        followup = MockInterviewQuestion(
            session_id=session.id, sequence=session.current_question_index, category=question.category,
            difficulty=question.difficulty, question_text=followup_text, parent_question_id=question.id,
            source="ai_generated" if not evaluation.degraded else "question_bank",
        )
        db.add(followup)
        db.commit()
        db.refresh(followup)
        response["next_question"] = _question_out(followup)
        return response

    session.current_question_index += 1
    if reached_planned_count:
        report = _finalize_session(db, session, u)
        response["session"] = _session_out(session)
        response["report"] = _report_out(report)
        return response

    db.commit()
    next_question = _create_next_question(db, session, u)
    response["next_question"] = _question_out(next_question)
    return response


# =============================================================================
# Coding submissions
# =============================================================================

class CodingSubmitIn(BaseModel):
    language: str = Field(max_length=40)
    code_text: str = Field(min_length=0, max_length=20000)


@router.post("/interview/sessions/{session_id}/coding-submit")
def submit_code(session_id: int, payload: CodingSubmitIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    session = _owned_session(db, session_id, u)
    if session.interview_type != "coding":
        raise HTTPException(422, "This session is not a coding interview")
    question = db.scalar(
        select(MockInterviewQuestion).where(MockInterviewQuestion.session_id == session.id).order_by(MockInterviewQuestion.id.desc())
    )
    if not question:
        raise HTTPException(409, "No active question for this session")

    result = sandbox.get_sandbox().run(language=payload.language, code=payload.code_text)
    existing = db.scalar(select(MockInterviewCodingSubmission).where(MockInterviewCodingSubmission.question_id == question.id))
    if existing:
        existing.language, existing.code_text = payload.language, payload.code_text
        existing.sandbox_status, existing.sandbox_message = result.status, result.message
        submission = existing
    else:
        submission = MockInterviewCodingSubmission(
            question_id=question.id, language=payload.language, code_text=payload.code_text,
            sandbox_status=result.status, sandbox_message=result.message,
        )
        db.add(submission)
    db.commit()
    db.refresh(submission)
    return {
        "sandbox_status": submission.sandbox_status, "sandbox_message": submission.sandbox_message,
        "note": "Submit this code as your answer via POST /interview/sessions/{id}/answer to receive a full evaluation.",
    }


# =============================================================================
# Report
# =============================================================================

def _finalize_session(db: Session, session: MockInterviewSession, u: User) -> MockInterviewReport:
    rows = db.execute(
        select(MockInterviewQuestion, MockInterviewEvaluation)
        .join(MockInterviewAnswer, MockInterviewAnswer.question_id == MockInterviewQuestion.id)
        .join(MockInterviewEvaluation, MockInterviewEvaluation.answer_id == MockInterviewAnswer.id)
        .where(MockInterviewQuestion.session_id == session.id)
        .order_by(MockInterviewQuestion.sequence)
    ).all()

    ctx = context_builder.build(db, session)
    aggregates = report_engine.aggregate_scores(rows)
    strengths = [s for _, e in rows for s in json.loads(e.strengths_json)]
    weaknesses = [w for _, e in rows for w in json.loads(e.weaknesses_json)]
    technical_gaps = report_engine.collect_technical_gaps(rows, ctx)
    narrative = report_engine.generate_report_narrative(
        db, aggregates=aggregates, strengths=strengths, weaknesses=weaknesses, technical_gaps=technical_gaps, user_id=u.id
    )

    _transition_or_409(db, session, "complete")

    report = MockInterviewReport(
        session_id=session.id, **aggregates,
        strengths_json=json.dumps(sorted(set(strengths))[:10]), weaknesses_json=json.dumps(sorted(set(weaknesses))[:10]),
        technical_gaps_json=json.dumps(technical_gaps), communication_feedback=narrative["communication_feedback"],
        recommended_topics_json=json.dumps(narrative["recommended_topics"]), summary=narrative["summary"],
        next_steps_json=json.dumps(narrative["next_steps"]),
        questions_answered=sum(1 for _, a in [(q, db.scalar(select(MockInterviewAnswer).where(MockInterviewAnswer.question_id == q.id))) for q, _ in rows] if a and not a.skipped),
        questions_skipped=sum(1 for _, a in [(q, db.scalar(select(MockInterviewAnswer).where(MockInterviewAnswer.question_id == q.id))) for q, _ in rows] if a and a.skipped),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


@router.get("/interview/sessions/{session_id}/report")
def get_report(session_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    session = _owned_session(db, session_id, u)
    report = db.scalar(select(MockInterviewReport).where(MockInterviewReport.session_id == session.id))
    if not report:
        raise HTTPException(404, "Report not available yet — this session isn't completed")
    return _report_out(report)


@router.get("/interview/sessions/{session_id}/questions")
def list_questions(session_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    session = _owned_session(db, session_id, u)
    rows = db.execute(
        select(MockInterviewQuestion, MockInterviewAnswer, MockInterviewEvaluation)
        .outerjoin(MockInterviewAnswer, MockInterviewAnswer.question_id == MockInterviewQuestion.id)
        .outerjoin(MockInterviewEvaluation, MockInterviewEvaluation.answer_id == MockInterviewAnswer.id)
        .where(MockInterviewQuestion.session_id == session.id)
        .order_by(MockInterviewQuestion.id)
    ).all()
    return {"questions": [_question_out(q, a, e) for q, a, e in rows]}


@router.post("/interview/sessions/{session_id}/report/explain")
def explain_report(session_id: int, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    """Career Copilot integration — explains an already-generated
    report and suggests preparation steps. See
    app.interview_ai.copilot_bridge's docstring for why this reuses
    the Copilot's system prompt rather than being a second engine."""
    enforce_rate_limit(request, "interview-ai-generate", limit=20, window=60)
    session = _owned_session(db, session_id, u)
    report = db.scalar(select(MockInterviewReport).where(MockInterviewReport.session_id == session.id))
    if not report:
        raise HTTPException(404, "Report not available yet — this session isn't completed")
    explanation = copilot_bridge.explain_report(db, report, user_id=u.id)
    return {"explanation": explanation}


# =============================================================================
# Admin — AI usage (reuses V20.1 observability, filtered to interview_ai operations)
# =============================================================================

@router.get("/interview/usage", dependencies=[Depends(admin_guard)])
def interview_usage(since_hours: int = Query(default=24, ge=1, le=24 * 30), db: Session = Depends(get_db)):
    summary = observability.usage_summary(db, since_hours=since_hours)
    logs = observability.recent_logs(db, limit=100)
    interview_logs = [row for row in logs if (row.operation or "").startswith("interview_ai.")]
    return {
        "since_hours": since_hours,
        "overall_ai_usage": summary,
        "recent_interview_ai_calls": [
            {"operation": row.operation, "provider": row.provider, "model": row.model, "success": row.success,
             "used_fallback": row.used_fallback, "latency_ms": row.latency_ms, "created_at": row.created_at.isoformat()}
            for row in interview_logs
        ],
    }
