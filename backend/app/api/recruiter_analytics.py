"""V24.4 — Recruiter Analytics & AI Hiring Intelligence.

Deterministic endpoints (overview/pipeline/applications-over-time/
time-in-stage/jobs/stale-candidates) call straight into
``app.recruiter_analytics.service`` and never touch the AI layer. The
three ``ai/*`` endpoints build a small, already-structured facts dict
from that same service layer and hand it to
``app.recruiter_analytics.ai`` — the model never sees a raw resume,
note, or job description, and never computes a number itself. See
docs/V24_4_RECRUITER_ANALYTICS_AI.md.

Every endpoint requires ``require_recruiter`` and re-derives ownership
from ``team_owner_ids``/``_owned_job_or_404`` — the same functions
V24.1-V24.3 already use — never from a client-supplied id.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.recruiter import _owned_job_or_404
from app.api.recruiter_candidates import _authorized_candidate_ids
from app.core.audit import log_audit
from app.core.rate_limit import enforce_rate_limit
from app.core.security import require_recruiter
from app.core.team_access import team_owner_ids
from app.db.session import get_db
from app.models.domain import User
from app.recruiter_analytics import ai as analytics_ai
from app.recruiter_analytics import service as analytics_service
from app.recruiter_pipeline.service import DEFAULT_STALE_THRESHOLD_DAYS

router = APIRouter()

MAX_STALE_THRESHOLD_DAYS = 365
MAX_COMPARE_CANDIDATES = 8


@router.get("/analytics/overview")
def overview(
    stale_threshold_days: int = Query(default=DEFAULT_STALE_THRESHOLD_DAYS, ge=1, le=MAX_STALE_THRESHOLD_DAYS),
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    return analytics_service.overview(db, team_owner_ids(db, recruiter), stale_threshold_days=stale_threshold_days)


@router.get("/analytics/pipeline")
def pipeline(job_id: int | None = Query(default=None), recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    owner_ids = team_owner_ids(db, recruiter)
    if job_id is not None:
        _owned_job_or_404(db, job_id, recruiter)  # 404s for another recruiter's job
    return {
        "funnel": analytics_service.funnel(db, owner_ids, job_id=job_id),
        **analytics_service.time_and_bottleneck_analytics(db, owner_ids, job_id=job_id),
    }


@router.get("/analytics/applications-over-time")
def applications_over_time(
    days: int = Query(default=30, ge=1, le=365),
    job_id: int | None = Query(default=None),
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    owner_ids = team_owner_ids(db, recruiter)
    if job_id is not None:
        _owned_job_or_404(db, job_id, recruiter)
    return analytics_service.applications_over_time(db, owner_ids, days=days, job_id=job_id)


@router.get("/analytics/time-in-stage")
def time_in_stage(job_id: int | None = Query(default=None), recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    owner_ids = team_owner_ids(db, recruiter)
    if job_id is not None:
        _owned_job_or_404(db, job_id, recruiter)
    return analytics_service.time_and_bottleneck_analytics(db, owner_ids, job_id=job_id)


@router.get("/analytics/stale-candidates")
def stale_candidates(
    threshold_days: int = Query(default=DEFAULT_STALE_THRESHOLD_DAYS, ge=1, le=MAX_STALE_THRESHOLD_DAYS),
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    return {"threshold_days": threshold_days, "candidates": analytics_service.stale_candidates_all(db, team_owner_ids(db, recruiter), threshold_days=threshold_days)}


@router.get("/analytics/jobs/{job_id}")
def job_analytics(job_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    job = _owned_job_or_404(db, job_id, recruiter)
    return analytics_service.job_performance(db, job)


@router.get("/analytics/jobs/{job_id}/candidates")
def job_candidate_match_analytics(job_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    job = _owned_job_or_404(db, job_id, recruiter)
    return analytics_service.candidate_match_analytics(db, recruiter, job)


# ---------------------------------------------------------------------------
# AI endpoints — grounded, cached, rate-limited. See app.recruiter_analytics.ai
# module docstring for the fairness/no-hallucination/no-injection design.
# ---------------------------------------------------------------------------


class AIRequestIn(BaseModel):
    force: bool = False


@router.post("/analytics/ai/pipeline-summary")
def ai_pipeline_summary(payload: AIRequestIn, request: Request, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    enforce_rate_limit(request, "recruiter-analytics-ai", limit=20, window=60)
    owner_ids = team_owner_ids(db, recruiter)

    overview_facts = analytics_service.overview(db, owner_ids)
    time_facts = analytics_service.time_and_bottleneck_analytics(db, owner_ids)
    funnel_facts = analytics_service.funnel(db, owner_ids)
    stale = analytics_service.stale_candidates_all(db, owner_ids)[:5]

    facts = {
        "overview": overview_facts,
        "time_and_bottlenecks": time_facts,
        "funnel": funnel_facts,
        # Deliberately no candidate name — only what's needed to point
        # the recruiter at a specific applicant record themselves.
        "stalest_candidates": [{"applicant_id": s["applicant_id"], "job_id": s["job_id"], "stage": s["pipeline_stage"], "days_inactive": s["days_inactive"]} for s in stale],
    }
    content, from_cache = analytics_ai.pipeline_summary(db, recruiter_id=recruiter.id, facts=facts, force=payload.force)
    log_audit(db, action="recruiter_ai_pipeline_summary", entity_type="user", entity_id=str(recruiter.id))
    return {"facts": facts, "ai": content, "from_cache": from_cache}


class CandidateComparisonIn(BaseModel):
    job_id: int
    candidate_ids: list[int] = Field(min_length=2, max_length=MAX_COMPARE_CANDIDATES)
    force: bool = False


@router.post("/analytics/ai/candidate-comparison")
def ai_candidate_comparison(payload: CandidateComparisonIn, request: Request, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    enforce_rate_limit(request, "recruiter-analytics-ai", limit=20, window=60)
    job = _owned_job_or_404(db, payload.job_id, recruiter)

    # Authorization for candidate comparison reuses V24.2's own
    # discovery-pool check — a candidate can only be compared if this
    # recruiter is already authorized to see them (applied to this job/
    # team's jobs, or opted in to discovery). Never trust a client-
    # supplied candidate id without this check.
    authorized_ids = _authorized_candidate_ids(db, recruiter, job_id=payload.job_id)
    unauthorized = [cid for cid in payload.candidate_ids if cid not in authorized_ids]
    if unauthorized:
        raise HTTPException(404, "One or more candidates were not found")

    comparison = analytics_service.compare_candidates(db, recruiter, job, payload.candidate_ids)
    facts = {"job_id": job.id, "job_title": job.title, "candidate_ids": payload.candidate_ids, "candidates": comparison}
    content, from_cache = analytics_ai.candidate_comparison(
        db, recruiter_id=recruiter.id, job_id=job.id, candidate_ids=payload.candidate_ids, facts=facts, force=payload.force
    )
    log_audit(db, action="recruiter_ai_candidate_comparison", entity_type="job", entity_id=str(job.id))
    return {"facts": facts, "ai": content, "from_cache": from_cache}


class JobInsightsIn(BaseModel):
    force: bool = False


@router.post("/analytics/ai/job-insights/{job_id}")
def ai_job_insights(job_id: int, payload: JobInsightsIn, request: Request, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    enforce_rate_limit(request, "recruiter-analytics-ai", limit=20, window=60)
    job = _owned_job_or_404(db, job_id, recruiter)

    performance = analytics_service.job_performance(db, job)
    match = analytics_service.candidate_match_analytics(db, recruiter, job)
    facts = {
        "job_id": job.id,
        "job_title": job.title,
        "job_has_skills_listed": bool(job.skills and job.skills.strip()),
        "job_has_salary_listed": bool(job.salary and job.salary.strip()),
        "job_has_deadline": job.deadline is not None,
        "performance": {k: v for k, v in performance.items() if k not in ("applications_over_time", "funnel")},
        "candidate_pool_size": match["candidates_scored"],
        "match_distribution": match["distribution"],
        "average_skill_coverage_pct": match["average_skill_coverage_pct"],
        "most_commonly_missing_skills": match["most_commonly_missing_skills"],
    }
    content, from_cache = analytics_ai.job_insights(db, recruiter_id=recruiter.id, job_id=job.id, facts=facts, force=payload.force)
    log_audit(db, action="recruiter_ai_job_insights", entity_type="job", entity_id=str(job.id))
    return {"facts": facts, "ai": content, "from_cache": from_cache}
