"""V25.5 — read/write helpers for ``FailedJobRecord``.

Kept deliberately tiny and dependency-free (just the ORM model and a
DB session) so any background call site — the scheduler today,
notification/email/ingestion/Career Agent code later — can adopt it
without importing anything AI- or scheduler-specific. Every function
commits its own transaction so a failure here can never roll back the
caller's own (already-committed-or-not) work.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.reliability.models import FailedJobRecord

log = logging.getLogger("careeros.reliability")

_MAX_REASON_CHARS = 2000


def record_failure(
    db: Session,
    *,
    job_name: str,
    error: str,
    idempotency_key: str = "",
    retries_exhausted: bool = False,
    backoff_seconds: int = 60,
) -> FailedJobRecord:
    """Upsert a failure row for (job_name, idempotency_key).

    ``retries_exhausted=True`` marks the row ``failed`` (no further
    automatic retry expected — visible in the dead-letter list until
    an operator investigates); otherwise it stays ``pending_retry``
    with ``next_retry_at`` set so the dashboard can show what's about
    to be retried versus what's given up.
    """
    existing = db.scalar(
        select(FailedJobRecord).where(
            FailedJobRecord.job_name == job_name,
            FailedJobRecord.idempotency_key == idempotency_key,
            FailedJobRecord.status == "pending_retry",
        )
    )
    now = datetime.utcnow()
    reason = (error or "")[:_MAX_REASON_CHARS]
    if existing is not None:
        existing.retry_count += 1
        existing.last_attempt_at = now
        existing.failure_reason = reason
        existing.status = "failed" if retries_exhausted else "pending_retry"
        existing.next_retry_at = None if retries_exhausted else now + timedelta(seconds=backoff_seconds)
        record = existing
    else:
        record = FailedJobRecord(
            job_name=job_name,
            idempotency_key=idempotency_key,
            status="failed" if retries_exhausted else "pending_retry",
            failure_reason=reason,
            retry_count=1,
            first_failed_at=now,
            last_attempt_at=now,
            next_retry_at=None if retries_exhausted else now + timedelta(seconds=backoff_seconds),
        )
        db.add(record)
    try:
        db.commit()
        db.refresh(record)
    except Exception:
        # Dead-letter bookkeeping must never be the reason the actual
        # job failure is lost/masked — log and move on.
        db.rollback()
        log.exception("Failed to persist FailedJobRecord for job_name=%r", job_name)
    return record


def record_recovery(db: Session, *, job_name: str, idempotency_key: str = "") -> None:
    """Mark any open (pending_retry) row for this work item resolved.

    Called after a retried unit of work finally succeeds, so it drops
    off the "currently failing" view instead of lingering forever.
    """
    open_records = db.scalars(
        select(FailedJobRecord).where(
            FailedJobRecord.job_name == job_name,
            FailedJobRecord.idempotency_key == idempotency_key,
            FailedJobRecord.status == "pending_retry",
        )
    ).all()
    if not open_records:
        return
    now = datetime.utcnow()
    for record in open_records:
        record.status = "recovered"
        record.resolved_at = now
    try:
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Failed to persist recovery for job_name=%r", job_name)


def summarize(db: Session, *, since: datetime | None = None) -> dict:
    """Aggregate counts for the observability dashboard.

    Deliberately just counts/small samples, never full failure_reason
    text for more than the most recent few rows — this feeds an
    admin-only dashboard, not a log viewer.
    """
    query = select(FailedJobRecord)
    if since is not None:
        query = query.where(FailedJobRecord.last_attempt_at >= since)
    records = db.scalars(query).all()

    by_status: dict[str, int] = {}
    by_job: dict[str, int] = {}
    for r in records:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        if r.status != "recovered":
            by_job[r.job_name] = by_job.get(r.job_name, 0) + 1

    recent_failed = db.scalars(
        select(FailedJobRecord)
        .where(FailedJobRecord.status.in_(["failed", "pending_retry"]))
        .order_by(FailedJobRecord.last_attempt_at.desc())
        .limit(20)
    ).all()

    return {
        "counts_by_status": by_status,
        "open_counts_by_job": by_job,
        "recent_failures": [
            {
                "job_name": r.job_name,
                "idempotency_key": r.idempotency_key,
                "status": r.status,
                "retry_count": r.retry_count,
                "last_attempt_at": r.last_attempt_at.isoformat(),
                "next_retry_at": r.next_retry_at.isoformat() if r.next_retry_at else None,
            }
            for r in recent_failed
        ],
    }
