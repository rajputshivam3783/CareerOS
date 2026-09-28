"""V22.4 — AI Application Intelligence & Follow-ups API.

Reuses, never rewrites: `current_user` (app.core.security),
`enforce_rate_limit` (app.core.rate_limit — same convention
app.api.career_copilot/app.api.interview_ai already use),
`app.applications.service.get_application` for ownership (same 404-
not-403 convention as app/api/application_workspace.py), and the
V20.1 AI Gateway via app.applications.ai.* (which itself only ever
calls app.ai.completion_service, never a provider directly).

Every AI-generating endpoint here degrades gracefully (see
app.applications.ai.narrative/followup/interview_prep — none of them
raise on provider failure, all return a `degraded: true` payload) —
so a provider outage never breaks the application workspace, only
this feature. The deterministic endpoints (action-plan, risks, and the
signal fields inside /overview) never touch an LLM at all and are
always available. Nothing here can change an application's status,
send an email, delete anything, or otherwise act without the
candidate's explicit follow-up action elsewhere in the app (per spec
section 15) — this router only ever returns suggestions.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications import service
from app.applications.ai import cache, context, followup, interview_prep, narrative
from app.applications.ai.followup import TONES
from app.applications.ai.signals import ApplicationSignals, compute_signals
from app.core.rate_limit import enforce_rate_limit
from app.core.security import current_user
from app.db.session import get_db
from app.models.domain import Application, ApplicationInterview

router = APIRouter()


def _not_found(exc: Exception):
    raise HTTPException(404, str(exc)) from exc


def _owned_application(db: Session, user_id: int, application_id: int) -> Application:
    try:
        return service.get_application(db, user_id, application_id)
    except service.ApplicationNotFoundError as exc:
        _not_found(exc)


def _signals_out(s: ApplicationSignals) -> dict:
    return {
        "health": {"score": s.health.score, "label": s.health.label, "reasons": s.health.reasons},
        "priority": s.priority,
        "next_best_action": {"action": s.next_action.action, "reason": s.next_action.reason, "timing": s.next_action.timing},
        "follow_up": {"timing": s.follow_up_timing, "reason": s.follow_up_reason},
        "risks": [
            {"risk": r.risk, "severity": r.severity, "reason": r.reason, "recommended_action": r.recommended_action}
            for r in s.risks
        ],
        "action_plan": [
            {"bucket": i.bucket, "title": i.title, "priority": i.priority, "reason": i.reason, "due_date": i.due_date}
            for i in s.action_plan
        ],
        "signals": {
            "days_since_last_activity": s.days_since_last_activity,
            "deadline_days_left": s.deadline_days_left,
            "overdue_task_count": s.overdue_task_count,
            "has_upcoming_interview": s.upcoming_interview is not None,
        },
    }


# ---------------------------------------------------------------------------
# Overview — always deterministic + best-effort last-cached narrative.
# Never calls the LLM itself (use POST /analyze to generate/refresh).
# ---------------------------------------------------------------------------


@router.get("/applications/{application_id}/ai/overview")
def get_overview(application_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    application = _owned_application(db, u.id, application_id)
    signals = compute_signals(db, application)

    out = _signals_out(signals)
    context_key = cache.make_context_key(narrative.KIND, signals.fingerprint())
    cached = cache.get_cached(db, application_id=application_id, kind=narrative.KIND, context_key=context_key)
    out["narrative"] = cache.content_of(cached) if cached else None
    out["narrative_generated_at"] = cached.created_at.isoformat() if cached else None
    return out


# ---------------------------------------------------------------------------
# Analyze — explicit "Refresh AI Analysis"
# ---------------------------------------------------------------------------


class AnalyzeIn(BaseModel):
    force: bool = False


@router.post("/applications/{application_id}/ai/analyze")
def analyze(application_id: int, payload: AnalyzeIn, request: Request, u=Depends(current_user), db: Session = Depends(get_db)):
    application = _owned_application(db, u.id, application_id)
    enforce_rate_limit(request, "application-ai-generate", limit=20, window=60)

    signals = compute_signals(db, application)
    ctx = context.build(db, application, signals)
    result, from_cache = narrative.generate(db, ctx, user_id=u.id, force=payload.force)

    out = _signals_out(signals)
    out["narrative"] = result
    out["from_cache"] = from_cache
    return out


# ---------------------------------------------------------------------------
# Follow-up draft
# ---------------------------------------------------------------------------


class FollowUpIn(BaseModel):
    tone: str = Field(default="PROFESSIONAL", description=f"One of {TONES}")
    force: bool = False


@router.post("/applications/{application_id}/ai/follow-up")
def generate_follow_up(application_id: int, payload: FollowUpIn, request: Request, u=Depends(current_user), db: Session = Depends(get_db)):
    application = _owned_application(db, u.id, application_id)
    enforce_rate_limit(request, "application-ai-generate", limit=20, window=60)

    signals = compute_signals(db, application)
    ctx = context.build(db, application, signals)
    result, from_cache = followup.generate(db, ctx, user_id=u.id, tone=payload.tone, force=payload.force)
    return {**result, "tone": payload.tone.upper() if payload.tone.upper() in TONES else "PROFESSIONAL", "from_cache": from_cache}


# ---------------------------------------------------------------------------
# Interview preparation
# ---------------------------------------------------------------------------


class InterviewPrepIn(BaseModel):
    interview_id: int | None = None
    force: bool = False


@router.post("/applications/{application_id}/ai/interview-prep")
def generate_interview_prep(application_id: int, payload: InterviewPrepIn, request: Request, u=Depends(current_user), db: Session = Depends(get_db)):
    application = _owned_application(db, u.id, application_id)
    enforce_rate_limit(request, "application-ai-generate", limit=20, window=60)

    signals = compute_signals(db, application)

    interview: ApplicationInterview | None = None
    if payload.interview_id is not None:
        interview = db.get(ApplicationInterview, payload.interview_id)
        if not interview or interview.application_id != application_id:
            raise HTTPException(404, "Interview not found")
    else:
        interview = signals.upcoming_interview
        if interview is None:
            interview = db.scalar(
                select(ApplicationInterview)
                .where(ApplicationInterview.application_id == application_id)
                .order_by(ApplicationInterview.created_at.desc())
                .limit(1)
            )
    if interview is None:
        raise HTTPException(400, "No interview found for this application. Add an interview first.")

    ctx = context.build(db, application, signals)
    result, from_cache = interview_prep.generate(db, ctx, interview, user_id=u.id, force=payload.force)
    return {**result, "interview_id": interview.id, "from_cache": from_cache}


# ---------------------------------------------------------------------------
# Action plan & risks — deterministic, no LLM, no rate limit needed.
# ---------------------------------------------------------------------------


@router.post("/applications/{application_id}/ai/action-plan")
def get_action_plan(application_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    application = _owned_application(db, u.id, application_id)
    signals = compute_signals(db, application)
    return {"action_plan": _signals_out(signals)["action_plan"]}


@router.post("/applications/{application_id}/ai/risks")
def get_risks(application_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    application = _owned_application(db, u.id, application_id)
    signals = compute_signals(db, application)
    return {"risks": _signals_out(signals)["risks"]}
