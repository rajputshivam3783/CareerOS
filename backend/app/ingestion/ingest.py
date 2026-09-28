"""V2 ingestion pipeline: Adapter -> Normalize -> Deduplicate -> Review queue.

Every run (manual or scheduled) is recorded as an ``IngestionRun`` row
so there's an auditable history of what was collected and when,
without needing to grep logs.
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.ingestion.adapters.base import BaseJobAdapter
from app.core.config import settings
from app.ingestion.services.deduplicate import is_duplicate
from app.ingestion.services.enrichment import enrich_record
from app.ingestion.services.normalize import normalize_job
from app.ingestion.services.publisher import publish_to_review
from app.models.domain import IngestionRun

logger = logging.getLogger("careeros.ingestion")


def run_ingestion(db: Session, adapter: BaseJobAdapter) -> dict:
    """Run one CareerOS ingestion source and record the outcome."""

    run = IngestionRun(source_name=adapter.source_name, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        records = adapter.fetch()
    except Exception as exc:  # a broken/unreachable source must not crash a scheduled batch
        logger.exception("Adapter '%s' failed to fetch", adapter.source_name)
        run.status = "failed"
        run.error_message = str(exc)[:2000]
        run.finished_at = datetime.utcnow()
        db.commit()
        return {"source": adapter.source_name, "status": "failed", "error": run.error_message}

    discovered = len(records)
    created = 0
    skipped = 0
    enriched = 0

    for record in records:
        normalized = normalize_job(record)
        if enriched < settings.ingestion_enrich_max_per_run and not is_duplicate(db, normalized):
            normalized = normalize_job(enrich_record(normalized, db))
            enriched += 1
        was_created, _ = publish_to_review(db=db, record=normalized)
        if was_created:
            created += 1
        else:
            skipped += 1

    run.discovered = discovered
    run.created = created
    run.skipped = skipped
    run.status = "success"
    run.finished_at = datetime.utcnow()
    db.commit()

    return {
        "source": adapter.source_name,
        "discovered": discovered,
        "created": created,
        "skipped": skipped,
        "status": "success",
    }


def run_all_enabled_sources(db: Session) -> list[dict]:
    """Run every source flagged ``enabled=True`` in app/ingestion/sources.py.

    Used by both the on-demand admin endpoint and the background
    scheduler so there's exactly one code path for "collect everything".
    """
    from app.ingestion.sources import enabled_sources  # local import avoids a circular import at module load

    results = []
    for source in enabled_sources():
        adapter = source.build()
        results.append(run_ingestion(db, adapter))
    return results
