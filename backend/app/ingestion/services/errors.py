"""V19.2 — Error handling: retry+backoff, circuit breaker, dead letter queue.

Kept deliberately dependency-free (no tenacity/pybreaker) so this adds
zero new third-party trust surface for logic this small — each piece
is ~20 lines and unit-testable on its own.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Callable, TypeVar

from sqlalchemy.orm import Session

from app.models.domain import IngestionDeadLetter, SourceRegistry

logger = logging.getLogger("careeros.ingestion.errors")

T = TypeVar("T")

# Circuit stays open (skipped by the scheduler) for this long after
# tripping, then allows one half-open trial run.
CIRCUIT_COOLDOWN = timedelta(minutes=30)
CIRCUIT_FAILURE_THRESHOLD = 3


def retry_with_backoff(
    fn: Callable[[], T],
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[T | None, Exception | None, int]:
    """Calls ``fn`` up to ``max_attempts`` times with exponential
    backoff (base_delay * 2**attempt) between tries. Returns
    (result, last_exception, attempts_used) — result is None and
    last_exception is set if every attempt failed. Never raises.
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return fn(), None, attempt + 1
        except Exception as exc:  # noqa: BLE001 — deliberately broad: any adapter failure is retryable
            last_exc = exc
            logger.warning("Attempt %d/%d failed: %s", attempt + 1, max_attempts, exc)
            if attempt < max_attempts - 1:
                sleep(base_delay_seconds * (2 ** attempt))
    return None, last_exc, max_attempts


def circuit_is_open(row: SourceRegistry) -> bool:
    """True if this source's circuit is currently open and still
    within its cooldown window (i.e. the scheduler should skip it)."""
    if row.circuit_state != "open":
        return False
    if row.circuit_opened_at is None:
        return False
    return datetime.utcnow() < row.circuit_opened_at + CIRCUIT_COOLDOWN


def record_circuit_result(db: Session, row: SourceRegistry, success: bool) -> None:
    """Update circuit state after a run. Opens the circuit after
    CIRCUIT_FAILURE_THRESHOLD consecutive failures; a single success
    (including a half-open trial run) closes it again."""
    if success:
        row.circuit_state = "closed"
        row.circuit_opened_at = None
    else:
        if (row.consecutive_failures or 0) >= CIRCUIT_FAILURE_THRESHOLD:
            if row.circuit_state != "open":
                row.circuit_state = "open"
                row.circuit_opened_at = datetime.utcnow()
                logger.warning("Circuit opened for source '%s' after %d consecutive failures",
                                row.source_name, row.consecutive_failures)
        elif row.circuit_state == "open" and not circuit_is_open(row):
            # Cooldown elapsed but this run also failed — stay open,
            # reset the clock for another cooldown window.
            row.circuit_opened_at = datetime.utcnow()
    db.commit()


def send_to_dead_letter(db: Session, source_name: str, payload: dict, error: str, run_id: int | None = None) -> None:
    """Record a per-record failure for manual review. Adapter-level
    (whole-source) failures are recorded on IngestionRun.error_message
    instead — see app.ingestion.orchestrator."""
    entry = IngestionDeadLetter(
        source_name=source_name,
        run_id=run_id,
        payload=json.dumps(payload, default=str)[:20000],
        error=str(error)[:2000],
    )
    db.add(entry)
    db.commit()
