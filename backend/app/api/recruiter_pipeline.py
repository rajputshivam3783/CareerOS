"""V24.3 — Candidate Pipeline & Hiring Workflow: the endpoints that
are genuinely new on top of V18.2's board (GET .../pipeline) and
move-stage (PATCH /applicants/{id}/stage) endpoints, which stay in
app.api.recruiter unchanged in shape. Mounted under the same
"/api/v1/recruiter" prefix as that router (see app.api.routes) —
FastAPI supports more than one router sharing a prefix, so this isn't
a duplicate route table, just a second file for the new surface area.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.recruiter import _owned_applicant_or_404, _owned_job_or_404
from app.core.audit import log_audit
from app.core.constants import PIPELINE_STAGES
from app.core.security import require_recruiter
from app.db.session import get_db
from app.models.domain import Applicant, User
from app.recruiter_pipeline import service as pipeline_service

router = APIRouter(tags=["recruiter-pipeline"])


@router.get("/jobs/{job_id}/pipeline/stats")
def job_pipeline_stats(job_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Spec section 15: per-job stage counts, applications this week,
    and average time in stage, plus the last 20 stage changes."""
    _owned_job_or_404(db, job_id, recruiter)
    applicants = db.scalars(select(Applicant).where(Applicant.job_id == job_id)).all()
    return pipeline_service.pipeline_stats(db, job_id, applicants)


@router.get("/jobs/{job_id}/pipeline/conversion")
def job_pipeline_conversion(job_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Spec section 16: new->shortlisted->interview->offer->hired
    funnel, with zero-denominator steps reported as a null rate rather
    than a misleading 0%/100%."""
    _owned_job_or_404(db, job_id, recruiter)
    applicants = db.scalars(select(Applicant).where(Applicant.job_id == job_id)).all()
    return pipeline_service.conversion_metrics(db, job_id, applicants)


@router.get("/jobs/{job_id}/pipeline/stale")
def job_pipeline_stale(
    job_id: int,
    days: int = Query(default=pipeline_service.DEFAULT_STALE_THRESHOLD_DAYS, ge=0, le=90),
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    """Spec section 18: active candidates with no pipeline activity
    for `days` (default 7). Never labels anyone "likely to reject" —
    only last activity, days inactive, and a fixed suggested next
    action per stage."""
    _owned_job_or_404(db, job_id, recruiter)
    applicants = db.scalars(select(Applicant).where(Applicant.job_id == job_id)).all()
    return {"job_id": job_id, "threshold_days": days, "stale_candidates": pipeline_service.stale_candidates(db, job_id, applicants, threshold_days=days)}


@router.get("/applicants/{applicant_id}/pipeline-history")
def applicant_pipeline_history(applicant_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Spec section 7 / section 25 (GET .../pipeline-history):
    immutable, chronological stage-change history for one candidate.
    Separate from ApplicationStatusHistory (candidate-owned) — see
    RecruiterPipelineHistory's docstring."""
    applicant = _owned_applicant_or_404(db, applicant_id, recruiter)
    history = pipeline_service.pipeline_history(db, applicant.id)
    return {
        "applicant_id": applicant.id,
        "current_stage": applicant.pipeline_stage,
        "history": [
            {
                "id": h.id,
                "old_stage": h.old_stage,
                "new_stage": h.new_stage,
                "changed_by_user_id": h.changed_by_user_id,
                "changed_at": h.changed_at,
                "direction": h.direction,
                "reason": h.reason,
            }
            for h in history
        ],
    }


class BulkStageIn(BaseModel):
    applicant_ids: list[int] = Field(min_length=1, max_length=200)
    pipeline_stage: str
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("pipeline_stage")
    @classmethod
    def stage_must_be_known(cls, value: str) -> str:
        if value not in PIPELINE_STAGES:
            raise ValueError(f"pipeline_stage must be one of {PIPELINE_STAGES}")
        return value


@router.post("/applicants/bulk-stage")
def bulk_move_stage(payload: BulkStageIn, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Spec section 22: bulk stage move / bulk reject.

    Every id is ownership-checked and transition-checked *before* any
    write happens, so nothing fails silently and a bad id doesn't cost
    the recruiter the rest of a batch: the response always reports one
    row per requested id, `ok: true/false`. Each accepted move is then
    written and committed individually via
    app.recruiter_pipeline.service.change_stage (the same atomic
    validate/update/history/commit sequence the single-applicant PATCH
    endpoint uses) — this is "no id is left half-updated", not "the
    whole batch is one all-or-nothing database transaction"; if the
    process were killed partway through a very large batch, ids
    already applied would stay applied and the response for that
    request would never be returned, which is an explicit, documented
    limitation rather than a silent one (see
    docs/V24_3_CANDIDATE_PIPELINE.md, "Known limitations").
    """
    results: list[dict] = []
    to_apply: list[Applicant] = []
    for applicant_id in payload.applicant_ids:
        try:
            applicant = _owned_applicant_or_404(db, applicant_id, recruiter)
        except HTTPException:
            results.append({"applicant_id": applicant_id, "ok": False, "error": "not_found_or_unauthorized"})
            continue
        try:
            pipeline_service.validate_transition(applicant.pipeline_stage, payload.pipeline_stage)
        except pipeline_service.StageTransitionError as exc:
            results.append({"applicant_id": applicant_id, "ok": False, "error": str(exc)})
            continue
        to_apply.append(applicant)

    for applicant in to_apply:
        result = pipeline_service.change_stage(
            db, applicant, payload.pipeline_stage, actor_user_id=recruiter.id, reason=payload.reason
        )
        log_audit(
            db,
            action="bulk_move_applicant_stage",
            entity_type="applicant",
            entity_id=str(applicant.id),
            detail=f"{result.history.old_stage} -> {result.history.new_stage}",
        )
        results.append({"applicant_id": applicant.id, "ok": True, "pipeline_stage": result.applicant.pipeline_stage})
    # No trailing db.commit() here — change_stage() already committed
    # each accepted move individually (see its docstring / the
    # docstring above).

    succeeded = sum(1 for r in results if r["ok"])
    return {"requested": len(payload.applicant_ids), "succeeded": succeeded, "failed": len(results) - succeeded, "results": results}
