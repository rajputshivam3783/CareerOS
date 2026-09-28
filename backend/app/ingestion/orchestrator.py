"""V19.2 — the adapter framework's run orchestrator.

This is the V19.2 counterpart to the existing V2 ``ingest.run_ingestion``
(app.ingestion.ingest, unchanged): where that function runs one
``BaseJobAdapter`` end to end for the static, code-defined sources in
``app/ingestion/sources.py``, ``run_source`` here runs one
*database-registered* ``SourceRegistry`` row end to end, adding the
V19.2 requirements that don't apply to the V2 path: circuit breaker
short-circuiting, retry with backoff, structured per-event logs,
change detection against existing Job rows, and health-metric
recording. Both paths write to the same ``IngestionRun``/``Job``/
``RecruitmentUpdate`` tables, so the admin review queue and government
dashboard see records from either path identically.
"""

from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy.orm import Session

from app.ingestion.adapters.configured import ConfiguredSourceAdapter
from app.ingestion.services import health as health_service
from app.ingestion.services.change_detection import apply_change, detect_change
from app.ingestion.services.errors import (
    circuit_is_open,
    record_circuit_result,
    retry_with_backoff,
    send_to_dead_letter,
)
from app.ingestion.services.deduplicate import is_duplicate
from app.ingestion.services.enrichment import enrich_record
from app.ingestion.services.normalize import normalize_job
from app.ingestion.services.publisher import publish_to_review
from app.core.config import settings
from app.models.domain import IngestionRun, IngestionRunLog, SourceRegistry

MAX_FETCH_ATTEMPTS = 3


def _log(db: Session, run_id: int, source_name: str, message: str, level: str = "info") -> None:
    db.add(IngestionRunLog(run_id=run_id, source_name=source_name, level=level, message=message[:4000]))
    db.commit()


def run_source(db: Session, source: SourceRegistry) -> dict:
    """Run one registered source end to end. Always returns a result
    dict and always leaves an IngestionRun row behind — a source that
    fails validation, is circuit-open, or fails every retry is still a
    recorded, inspectable outcome, never a silent no-op."""

    run = IngestionRun(source_name=source.source_name, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    if source.status != "active":
        _log(db, run.id, source.source_name, f"Skipped — source status is '{source.status}', not 'active'.")
        run.status = "skipped"
        run.finished_at = datetime.utcnow()
        db.commit()
        return {"source": source.source_name, "status": "skipped", "reason": f"status={source.status}"}

    if circuit_is_open(source):
        _log(db, run.id, source.source_name, "Skipped — circuit breaker is open (source recently failed repeatedly).",
             level="warning")
        run.status = "skipped"
        run.finished_at = datetime.utcnow()
        db.commit()
        return {"source": source.source_name, "status": "skipped", "reason": "circuit_open"}

    adapter = ConfiguredSourceAdapter.from_registry_row(source)
    valid, reason = adapter.validate()
    if not valid:
        _log(db, run.id, source.source_name, f"Validation failed: {reason}", level="error")
        run.status = "failed"
        run.error_message = reason
        run.finished_at = datetime.utcnow()
        db.commit()
        health_service.record_run_outcome(db, source.source_name, success=False, latency_ms=0)
        record_circuit_result(db, source, success=False)
        return {"source": source.source_name, "status": "failed", "error": reason}

    _log(db, run.id, source.source_name, f"Fetch started ({source.collector_type}) — {source.official_url}")
    started = time.monotonic()
    records, exc, attempts = retry_with_backoff(adapter.fetch, max_attempts=MAX_FETCH_ATTEMPTS)
    latency_ms = int((time.monotonic() - started) * 1000)

    if exc is not None:
        _log(db, run.id, source.source_name, f"Fetch failed after {attempts} attempt(s): {exc}", level="error")
        run.status = "failed"
        run.error_message = str(exc)[:2000]
        run.finished_at = datetime.utcnow()
        db.commit()
        health_service.record_run_outcome(db, source.source_name, success=False, latency_ms=latency_ms, retry_count=attempts)
        record_circuit_result(db, source, success=False)
        return {"source": source.source_name, "status": "failed", "error": run.error_message}

    discovered = len(records or [])
    _log(db, run.id, source.source_name, f"Fetch succeeded in {latency_ms}ms — {discovered} record(s) discovered "
                                          f"(attempt {attempts}/{MAX_FETCH_ATTEMPTS}).")

    created = 0
    skipped = 0
    changes: list[str] = []
    enriched_count = 0

    for raw in records or []:
        try:
            normalized = normalize_job(raw)
            # V25.7 — only NEW records are enriched (a download per record),
            # so re-runs over already-known notices cost nothing extra.
            if enriched_count < settings.ingestion_enrich_max_per_run and not is_duplicate(db, normalized):
                normalized = normalize_job(enrich_record(normalized, db))
                enriched_count += 1
            change = detect_change(db, normalized)
            was_created, job = publish_to_review(db=db, record=normalized)
            if was_created:
                created += 1
            else:
                skipped += 1
                update = apply_change(db, change, source_url=normalized.notification_url)
                if update is not None:
                    changes.append(change.change_type)
        except Exception as record_exc:  # noqa: BLE001 — one bad record must not fail the whole run
            send_to_dead_letter(db, source.source_name, raw.model_dump() if hasattr(raw, "model_dump") else {},
                                 str(record_exc), run_id=run.id)
            _log(db, run.id, source.source_name, f"Record save failed, sent to dead letter queue: {record_exc}",
                 level="warning")
            skipped += 1

    run.discovered = discovered
    run.created = created
    run.skipped = skipped
    run.status = "success"
    run.finished_at = datetime.utcnow()
    db.commit()

    _log(db, run.id, source.source_name,
         f"Run complete — {created} created, {skipped} skipped/updated, changes: {changes or 'none'}.")

    health_service.record_run_outcome(db, source.source_name, success=True, latency_ms=latency_ms, retry_count=attempts)
    record_circuit_result(db, source, success=True)

    return {
        "source": source.source_name,
        "status": "success",
        "discovered": discovered,
        "created": created,
        "skipped": skipped,
        "changes": changes,
        "latency_ms": latency_ms,
        "attempts": attempts,
    }


def run_source_by_id(db: Session, source_id: int) -> dict:
    """Convenience entry point for a single manual-sync trigger (the
    admin 'Run adapter manually' action) or a distributed-worker job
    payload of just an id — see app.ingestion.scheduler's docstring
    for how this composes with a future task queue."""
    source = db.get(SourceRegistry, source_id)
    if not source:
        return {"status": "failed", "error": f"No SourceRegistry row with id={source_id}"}
    return run_source(db, source)
