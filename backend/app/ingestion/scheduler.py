"""V19.2 — Scheduler framework.

Deliberately **in-process** for this version — there is no background
worker process, cron entry, or task queue wired up yet (see
ROADMAP.md's V19.3+ notes). What this module provides is the
*framework*: a pure, testable function that decides which sources are
due right now given their ``schedule`` string and health history, in
priority order, plus a runner that executes them one at a time through
``app.ingestion.orchestrator.run_source``.

Wiring this to an actual clock is intentionally left to the deployment
(a simple option: an external cron hitting
``POST /government/scheduler/run-due`` hourly; see
docs/SCHEDULER.md). For a future distributed-worker setup, the unit of
work is exactly ``app.ingestion.orchestrator.run_source_by_id(db, id)``
— a single source id, safe to hand to any task queue (Celery/RQ/etc.)
as the job payload; ``run_due_sources`` below is just a sequential
in-process caller of that same function and can be swapped for
"enqueue one job per due source id" without changing the due-selection
logic at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.orchestrator import run_source
from app.ingestion.services.errors import circuit_is_open
from app.models.domain import SourceRegistry

# Interpreted cadences for SourceRegistry.schedule. Anything else
# (including None/blank, or "manual") is never auto-selected by
# due_sources() — it only runs via an explicit manual trigger.
_CADENCE_INTERVALS = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
}


def is_due(source: SourceRegistry, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    if source.status != "active":
        return False
    if circuit_is_open(source):
        return False
    interval = _CADENCE_INTERVALS.get((source.schedule or "").strip().lower())
    if interval is None:
        return False  # "manual" or unset — never auto-scheduled
    if source.last_run_at is None:
        return True
    return now >= source.last_run_at + interval


def due_sources(db: Session, now: datetime | None = None) -> list[SourceRegistry]:
    """Sources due for a run right now, ordered as a priority queue
    (lower ``priority`` value first, then longest-since-last-run)."""
    now = now or datetime.utcnow()
    candidates = db.scalars(select(SourceRegistry).where(SourceRegistry.status == "active")).all()
    due = [s for s in candidates if is_due(s, now)]
    due.sort(key=lambda s: (s.priority, s.last_run_at or datetime.min))
    return due


def run_due_sources(db: Session, now: datetime | None = None, limit: int | None = None) -> list[dict]:
    """Run every currently-due source, in priority order, sequentially
    and in-process. See module docstring for how this maps onto a
    future distributed-worker setup."""
    sources = due_sources(db, now)
    if limit is not None:
        sources = sources[:limit]
    return [run_source(db, s) for s in sources]
