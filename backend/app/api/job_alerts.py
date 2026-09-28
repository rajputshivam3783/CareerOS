"""V23.3 — Smart Job Alerts & Personalized Job Notifications API.

Routes exactly as spec section 18 (POST/GET/PATCH/DELETE /job-alerts,
enable/disable, matches, history, preview), under /api/v1 like every
other router (see app.api.routes). Every route resolves the acting
user from ``current_user`` (verified JWT) and every service call is
ownership-scoped by that user's id — see app.job_alerts.service's
module docstring.

V23.5 (docs/V23_BUG_REPORT.md): the three endpoints that actually run
the matching pipeline — POST .../run-now (a real delivery run, plus
notification/email side effects), POST /preview, and GET .../preview
(both preview variants score real candidates via
app.recommendations/app.search.ranking, personalized previews
especially) — had no cost control: an ordinary authenticated candidate
could call any of them in a tight loop with no limit. Rate-limited
here with the same `enforce_rate_limit` (app.core.rate_limit — same
convention as app.api.application_ai's generate endpoints) rather than
inventing a second throttling mechanism.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.rate_limit import enforce_rate_limit
from app.core.security import current_user
from app.db.session import get_db
from app.job_alerts import execution, service
from app.job_alerts.schemas import JobAlertCreateIn, JobAlertOut, JobAlertUpdateIn
from app.models.domain import JobAlert

router = APIRouter(prefix="/job-alerts", tags=["V23.3 Smart Job Alerts"])


def _out(alert: JobAlert) -> JobAlertOut:
    return JobAlertOut.model_validate(alert)


@router.post("", status_code=201)
def create_job_alert(payload: JobAlertCreateIn, u=Depends(current_user), db: Session = Depends(get_db)):
    alert = service.create_alert(db, u.id, payload)
    return _out(alert)


@router.get("")
def list_job_alerts(u=Depends(current_user), db: Session = Depends(get_db)):
    return [_out(a) for a in service.list_alerts(db, u.id)]


@router.get("/{alert_id}")
def get_job_alert(alert_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        return _out(service.get_alert(db, u.id, alert_id))
    except service.JobAlertNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.patch("/{alert_id}")
def update_job_alert(alert_id: int, payload: JobAlertUpdateIn, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        return _out(service.update_alert(db, u.id, alert_id, payload))
    except service.JobAlertNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.delete("/{alert_id}", status_code=204)
def delete_job_alert(alert_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        service.delete_alert(db, u.id, alert_id)
    except service.JobAlertNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{alert_id}/enable")
def enable_job_alert(alert_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        return _out(service.set_enabled(db, u.id, alert_id, True))
    except service.JobAlertNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{alert_id}/disable")
def disable_job_alert(alert_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        return _out(service.set_enabled(db, u.id, alert_id, False))
    except service.JobAlertNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{alert_id}/matches")
def get_job_alert_matches(alert_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        return {"items": service.get_matches(db, u.id, alert_id)}
    except service.JobAlertNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{alert_id}/history")
def get_job_alert_history(alert_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        runs = service.list_runs(db, u.id, alert_id)
    except service.JobAlertNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "items": [
            {
                "id": r.id,
                "started_at": r.started_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "status": r.status,
                "candidates_scanned": r.candidates_scanned,
                "jobs_matched": r.jobs_matched,
                "notifications_created": r.notifications_created,
                "emails_queued": r.emails_queued,
                "error_summary": r.error_summary,
            }
            for r in runs
        ]
    }


@router.get("/{alert_id}/preview")
def preview_saved_job_alert(alert_id: int, request: Request, u=Depends(current_user), db: Session = Depends(get_db)):
    """Preview using an already-saved alert's current criteria —
    distinct from POST .../preview below, which previews unsaved
    create-form criteria before the alert exists."""
    enforce_rate_limit(request, "job-alert-preview", limit=20, window=60)
    try:
        return {"items": service.get_matches(db, u.id, alert_id)}
    except service.JobAlertNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/preview")
def preview_new_job_alert(payload: JobAlertCreateIn, request: Request, u=Depends(current_user), db: Session = Depends(get_db)):
    """spec section 5 — live preview from the alert creation form,
    before the alert is saved. Same JobAlertCreateIn shape as POST
    /job-alerts so the frontend can preview exactly what it's about to
    submit."""
    enforce_rate_limit(request, "job-alert-preview", limit=20, window=60)
    return {"items": service.preview_alert(db, u.id, payload)}


@router.post("/{alert_id}/run-now")
def run_job_alert_now(alert_id: int, request: Request, u=Depends(current_user), db: Session = Depends(get_db)):
    """Manual "Run now" — same execution.run_alert the scheduler
    calls, so behavior is identical to a scheduled run (delivers real
    notifications/emails and records real JobAlertDelivery rows, not a
    dry preview — see POST .../preview for the non-delivering version)."""
    enforce_rate_limit(request, "job-alert-run-now", limit=30, window=60)
    try:
        alert = service.get_alert(db, u.id, alert_id)
    except service.JobAlertNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    run = execution.run_alert(db, alert)
    return {
        "id": run.id,
        "status": run.status,
        "jobs_matched": run.jobs_matched,
        "notifications_created": run.notifications_created,
        "emails_queued": run.emails_queued,
        "error_summary": run.error_summary,
    }
