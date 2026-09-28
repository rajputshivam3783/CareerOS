"""V25.5 — durable dead-letter / failed-job tracking (spec section 9).

Before this, background-job failure state lived only in
``app.scheduler.job_health`` — an in-memory dict that only ever holds
the *last* run of each named scheduled job and resets on every
process restart. That's fine as a liveness convenience (it still
backs GET /admin/automation/health, unchanged), but it can't answer
"what failed, how many times, and when will it retry next" after a
restart, and it has no concept of a single failed *unit of work*
(e.g. one job-ingestion source, one AI Career Agent action) as
opposed to "the whole scheduled job errored".

``FailedJobRecord`` is the durable counterpart: one row per failed
unit of work, written by ``record_failure``/``record_recovery`` below.
Nothing existing was changed to make room for it — it is a new table,
populated by a new, narrow call from ``app.scheduler._with_retry``
(the same place that already updated ``job_health``), and read by the
new GET /admin/observability endpoint. No other call site is required
to use it; callers that don't will simply not show up here, exactly
as before V25.5.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FailedJobRecord(Base):
    """One row per background unit of work that failed at least once.

    ``job_name`` + ``idempotency_key`` is the natural dedupe key: a
    retried unit of work updates its existing row (``retry_count``,
    ``last_attempt_at``, ``next_retry_at``) instead of creating a new
    one, so the dead-letter list reflects distinct failures rather
    than one row per attempt.
    """

    __tablename__ = "failed_job_records"
    __table_args__ = (
        Index("ix_failed_job_records_job_status", "job_name", "status"),
        Index("ix_failed_job_records_idempotency", "job_name", "idempotency_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String(120), index=True)
    # Identifies the specific unit of work within job_name (e.g. an
    # ingestion source slug, a notification id, an AI action id) so
    # repeated failures of the *same* work item update one row rather
    # than piling up duplicates. Free text — callers choose a stable
    # value; "" is valid for jobs with no natural sub-unit.
    idempotency_key: Mapped[str] = mapped_column(String(200), default="")
    # "pending_retry" | "failed" (retries exhausted) | "recovered"
    status: Mapped[str] = mapped_column(String(20), default="pending_retry", index=True)
    # Deliberately not the full exception/traceback — see this
    # module's docstring and app.core.logging on avoiding sensitive
    # payloads in anything an admin dashboard renders. Truncated to
    # keep a runaway error message from bloating the table.
    failure_reason: Mapped[str] = mapped_column(Text, default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    first_failed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
