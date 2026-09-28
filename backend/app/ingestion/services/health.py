"""V19.2 — Source health tracking.

Reads/writes the health columns added to ``SourceRegistry`` (see
migrations/v19_2_source_adapter_framework.sql): last_run_at (V19.1,
unchanged), last_success_at (V19.1, unchanged), last_failure_at,
last_latency_ms, availability_pct, retry_count. Availability is a
simple rolling percentage over the most recent ``IngestionRun`` rows
for that source, recomputed on every run rather than stored as a
separately-drifting counter.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import IngestionRun, SourceRegistry

ROLLING_WINDOW = 20  # most recent runs considered for availability_pct


def get_health(db: Session, source_name: str) -> dict:
    row = db.scalar(select(SourceRegistry).where(SourceRegistry.source_name == source_name))
    if not row:
        return {
            "source_name": source_name,
            "registered": False,
            "status": "unregistered",
        }
    return {
        "source_name": row.source_name,
        "registered": True,
        "status": row.status,
        "circuit_state": row.circuit_state,
        "last_run_at": row.last_run_at,
        "last_success_at": row.last_success_at,
        "last_failure_at": row.last_failure_at,
        "last_latency_ms": row.last_latency_ms,
        "availability_pct": row.availability_pct,
        "retry_count": row.retry_count,
        "consecutive_failures": row.consecutive_failures,
        "error_count": row.error_count,
    }


def record_run_outcome(
    db: Session,
    source_name: str,
    success: bool,
    latency_ms: int,
    retry_count: int = 0,
) -> SourceRegistry | None:
    """Update a source's health snapshot after a completed run.
    Silently no-ops if the source isn't registered — health tracking
    is bookkeeping on top of an existing catalog row, not a reason to
    fail a run that a registry entry hasn't been created for yet."""
    row = db.scalar(select(SourceRegistry).where(SourceRegistry.source_name == source_name))
    if not row:
        return None

    now = datetime.utcnow()
    row.last_run_at = now
    row.last_latency_ms = latency_ms
    row.retry_count = retry_count

    if success:
        row.last_success_at = now
        row.consecutive_failures = 0
    else:
        row.last_failure_at = now
        row.error_count = (row.error_count or 0) + 1
        row.consecutive_failures = (row.consecutive_failures or 0) + 1

    recent = db.scalars(
        select(IngestionRun)
        .where(IngestionRun.source_name == source_name)
        .order_by(IngestionRun.started_at.desc())
        .limit(ROLLING_WINDOW)
    ).all()
    if recent:
        successes = sum(1 for r in recent if r.status == "success")
        row.availability_pct = round(100.0 * successes / len(recent), 1)

    db.commit()
    db.refresh(row)
    return row
