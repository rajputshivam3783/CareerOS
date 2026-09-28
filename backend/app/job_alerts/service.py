"""V23.3 — JobAlert CRUD. The one place that reads/writes the
``job_alerts`` table, same "one service owns one table" convention as
app.notifications.service/app.email.service.

SECURITY (spec section 25): every function here takes ``user_id`` from
the caller (always the verified JWT at the API layer — see
app.api.job_alerts) and re-checks it against the row's own user_id
before returning/mutating anything, so a candidate can never read,
edit, enable/disable, or delete another candidate's alert (IDOR
protection) — same ownership pattern as
app.notifications.service._get_owned.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.job_alerts import matching
from app.job_alerts.schemas import JobAlertCreateIn, JobAlertUpdateIn
from app.models.domain import Job, JobAlert, JobAlertDelivery, JobAlertRun, User

PREVIEW_LIMIT = 10
MATCHES_LIMIT = 50


class JobAlertError(Exception):
    pass


class JobAlertNotFound(JobAlertError):
    pass


def _get_owned(db: Session, user_id: int, alert_id: int) -> JobAlert:
    alert = db.get(JobAlert, alert_id)
    if alert is None or alert.user_id != user_id:
        raise JobAlertNotFound(f"Job alert {alert_id} not found")
    return alert


def create_alert(db: Session, user_id: int, payload: JobAlertCreateIn) -> JobAlert:
    alert = JobAlert(user_id=user_id, **payload.model_dump())
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def update_alert(db: Session, user_id: int, alert_id: int, payload: JobAlertUpdateIn) -> JobAlert:
    alert = _get_owned(db, user_id, alert_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(alert, field, value)
    alert.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(alert)
    return alert


def set_enabled(db: Session, user_id: int, alert_id: int, enabled: bool) -> JobAlert:
    alert = _get_owned(db, user_id, alert_id)
    alert.enabled = enabled
    alert.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(alert)
    return alert


def delete_alert(db: Session, user_id: int, alert_id: int) -> None:
    alert = _get_owned(db, user_id, alert_id)
    db.delete(alert)
    db.commit()


def get_alert(db: Session, user_id: int, alert_id: int) -> JobAlert:
    return _get_owned(db, user_id, alert_id)


def list_alerts(db: Session, user_id: int) -> list[JobAlert]:
    return list(
        db.scalars(select(JobAlert).where(JobAlert.user_id == user_id).order_by(JobAlert.created_at.desc())).all()
    )


def list_runs(db: Session, user_id: int, alert_id: int, *, limit: int = 20) -> list[JobAlertRun]:
    _get_owned(db, user_id, alert_id)  # ownership check — 404s before ever touching JobAlertRun
    return list(
        db.scalars(
            select(JobAlertRun)
            .where(JobAlertRun.job_alert_id == alert_id)
            .order_by(JobAlertRun.started_at.desc())
            .limit(limit)
        ).all()
    )


def _matches_to_out(db: Session, alert: JobAlert, candidates: list[matching.MatchCandidate]) -> list[dict]:
    delivered_job_ids = set(
        db.scalars(
            select(JobAlertDelivery.job_id).where(
                JobAlertDelivery.job_alert_id == alert.id, JobAlertDelivery.channel == "IN_APP"
            )
        ).all()
    )
    out = []
    for c in candidates:
        job = db.get(Job, c.job_id)
        if job is None:
            continue
        out.append(
            {
                "job_id": job.id,
                "title": job.title,
                "organization": job.organization,
                "location": job.location,
                "job_type": job.job_type,
                "employment_type": job.employment_type,
                "salary": job.salary,
                "posted_date": job.start_date.isoformat() if job.start_date else None,
                "relevance_score": c.relevance_score,
                "match_reasons": c.match_reasons,
                "already_delivered": job.id in delivered_job_ids,
            }
        )
    return out


def preview_alert(db: Session, user_id: int, payload: JobAlertCreateIn) -> list[dict]:
    """spec section 5: "Show a preview: Example jobs that match this
    alert. Use real existing jobs where available. Do not fabricate
    jobs." Builds a transient, unsaved JobAlert from the create-form
    payload and runs the read-only matching pipeline against it —
    nothing is persisted (no JobAlert/JobAlertRun/JobAlertDelivery row
    is written)."""
    user = db.get(User, user_id)
    if user is None:
        raise JobAlertNotFound("User not found")
    transient = JobAlert(user_id=user_id, created_at=datetime.utcnow(), **payload.model_dump())
    candidates, _scanned = matching.find_matches(db, transient, user, since=None, limit=PREVIEW_LIMIT)
    return _matches_to_out(db, transient, candidates)


def get_matches(db: Session, user_id: int, alert_id: int) -> list[dict]:
    """spec section 18: GET .../matches — current jobs matching a
    saved alert's criteria right now (not restricted to "since last
    run" — that restriction is specific to delivery runs, see
    app.job_alerts.matching.find_matches' docstring)."""
    alert = _get_owned(db, user_id, alert_id)
    user = db.get(User, user_id)
    candidates, _scanned = matching.find_matches(db, alert, user, since=None, limit=MATCHES_LIMIT)
    return _matches_to_out(db, alert, candidates)
