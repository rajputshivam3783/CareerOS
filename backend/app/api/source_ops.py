"""V19.2 — Official Source Adapter Framework: operational API.

Additive to app.api.government_core (unchanged) — that module owns
Source Registry *CRUD* (register/list/patch a source); this module
owns *running* sources and reading back what happened: manual sync,
health, run history, structured logs, aggregate statistics, the
scheduler's due-queue, and seeding the initial organization catalog.
Mounted at the same ``/government`` prefix so the whole Source
Registry surface lives under one path from the frontend's point of
view (``/government/sources/...``).

Every endpoint here is admin-only via the same ``guard`` dependency
every other admin route in this codebase uses (shared X-Admin-Key or
an admin-role JWT) — no new auth mechanism.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.admin import guard
from app.core.audit import log_audit
from app.db.session import get_db
from app.ingestion.adapters.configured import ConfiguredSourceAdapter
from app.ingestion.orchestrator import run_source
from app.ingestion.registry_seed import FRAMEWORK_ORGANIZATIONS, seed_framework_organizations
from app.ingestion.scheduler import due_sources, run_due_sources
from app.ingestion.services import health as health_service
from app.core.constants import SOURCE_COLLECTOR_TYPES
from app.models.domain import IngestionDeadLetter, IngestionRun, IngestionRunLog, SourceRegistry

router = APIRouter()


def _get_source_or_404(source_id: int, db: Session) -> SourceRegistry:
    source = db.get(SourceRegistry, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    return source


# --- Adapter type metadata (for the admin UI's "add source" form) ---------

@router.get("/adapters/types", dependencies=[Depends(guard)])
def list_adapter_types():
    return {"collector_types": SOURCE_COLLECTOR_TYPES}


# --- Manual sync ------------------------------------------------------------

@router.post("/sources/{source_id}/run", dependencies=[Depends(guard)])
def run_source_manually(source_id: int, db: Session = Depends(get_db)):
    source = _get_source_or_404(source_id, db)
    result = run_source(db, source)
    log_audit(db, action="run_source", entity_type="source_registry", entity_id=str(source_id), detail=result.get("status"))
    db.commit()
    return result


@router.post("/sources/{source_id}/validate", dependencies=[Depends(guard)])
def validate_source(source_id: int, db: Session = Depends(get_db)):
    """No-network configuration check — lets the admin UI catch a bad
    selector/JSON-path/URL before ever scheduling a run."""
    source = _get_source_or_404(source_id, db)
    adapter = ConfiguredSourceAdapter.from_registry_row(source)
    ok, reason = adapter.validate()
    return {"source": source.source_name, "valid": ok, "reason": reason, "metadata": adapter.metadata().__dict__}


# --- Health / runs / logs ---------------------------------------------------

@router.get("/sources/{source_id}/health", dependencies=[Depends(guard)])
def source_health(source_id: int, db: Session = Depends(get_db)):
    source = _get_source_or_404(source_id, db)
    return health_service.get_health(db, source.source_name)


@router.get("/sources/{source_id}/runs", dependencies=[Depends(guard)])
def source_runs(
    source_id: int,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    source = _get_source_or_404(source_id, db)
    q = select(IngestionRun).where(IngestionRun.source_name == source.source_name)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(IngestionRun.started_at.desc()).offset(offset).limit(limit)).all()
    return {"total": total, "runs": rows}


@router.get("/sources/{source_id}/logs", dependencies=[Depends(guard)])
def source_logs(
    source_id: int,
    run_id: int | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    source = _get_source_or_404(source_id, db)
    q = select(IngestionRunLog).where(IngestionRunLog.source_name == source.source_name)
    if run_id is not None:
        q = q.where(IngestionRunLog.run_id == run_id)
    rows = db.scalars(q.order_by(IngestionRunLog.created_at.desc()).limit(limit)).all()
    return {"logs": rows}


@router.get("/sources/{source_id}/dead-letters", dependencies=[Depends(guard)])
def source_dead_letters(
    source_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    source = _get_source_or_404(source_id, db)
    q = select(IngestionDeadLetter).where(IngestionDeadLetter.source_name == source.source_name, IngestionDeadLetter.resolved.is_(False))
    rows = db.scalars(q.order_by(IngestionDeadLetter.created_at.desc()).limit(limit)).all()
    return {"dead_letters": rows}


# --- Statistics dashboard ----------------------------------------------------

@router.get("/sources/statistics", dependencies=[Depends(guard)])
def statistics(db: Session = Depends(get_db)):
    sources = db.scalars(select(SourceRegistry)).all()
    by_status = {}
    for s in sources:
        by_status[s.status] = by_status.get(s.status, 0) + 1

    total_runs = db.scalar(select(func.count()).select_from(IngestionRun)) or 0
    success_runs = db.scalar(select(func.count()).select_from(IngestionRun).where(IngestionRun.status == "success")) or 0
    failed_runs = db.scalar(select(func.count()).select_from(IngestionRun).where(IngestionRun.status == "failed")) or 0
    total_created = db.scalar(select(func.coalesce(func.sum(IngestionRun.created), 0))) or 0
    open_circuits = sum(1 for s in sources if s.circuit_state == "open")
    unresolved_dead_letters = db.scalar(
        select(func.count()).select_from(IngestionDeadLetter).where(IngestionDeadLetter.resolved.is_(False))
    ) or 0

    return {
        "total_sources": len(sources),
        "sources_by_status": by_status,
        "open_circuits": open_circuits,
        "total_runs": total_runs,
        "successful_runs": success_runs,
        "failed_runs": failed_runs,
        "success_rate_pct": round(100.0 * success_runs / total_runs, 1) if total_runs else None,
        "failure_rate_pct": round(100.0 * failed_runs / total_runs, 1) if total_runs else None,
        "total_jobs_created": total_created,
        "unresolved_dead_letters": unresolved_dead_letters,
    }


# --- Scheduler ---------------------------------------------------------------

@router.get("/scheduler/due", dependencies=[Depends(guard)])
def scheduler_due(db: Session = Depends(get_db)):
    return {"due": due_sources(db)}


@router.post("/scheduler/run-due", dependencies=[Depends(guard)])
def scheduler_run_due(limit: int | None = Query(None, ge=1, le=100), db: Session = Depends(get_db)):
    results = run_due_sources(db, limit=limit)
    log_audit(db, action="scheduler_run_due", entity_type="source_registry", entity_id="*", detail=f"{len(results)} source(s)")
    db.commit()
    return {"ran": len(results), "results": results}


@router.post("/sources/run-all", dependencies=[Depends(guard)])
def run_all_government_sources(
    activate_verified: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Operator-friendly government sync.

    Disabled sources are dry-run fetched first. With activate_verified=true,
    only sources returning at least one record are activated. Then every active
    source is run independently; one failure is reported without aborting the rest.
    """
    seed_framework_organizations(db)
    sources = db.scalars(select(SourceRegistry).order_by(SourceRegistry.priority, SourceRegistry.id)).all()
    verification = []

    for source in sources:
        if source.status == "active":
            continue
        adapter = ConfiguredSourceAdapter.from_registry_row(source)
        ok, reason = adapter.validate()
        if not ok:
            verification.append({"source": source.source_name, "status": "invalid", "error": reason})
            continue
        try:
            records = adapter.fetch()
        except Exception as exc:  # noqa: BLE001
            verification.append({"source": source.source_name, "status": "failed", "error": str(exc)[:1000]})
            continue
        verification.append({"source": source.source_name, "status": "ok", "records": len(records)})
        if activate_verified and records:
            source.status = "active"
            db.commit()

    active = db.scalars(
        select(SourceRegistry).where(SourceRegistry.status == "active").order_by(SourceRegistry.priority, SourceRegistry.id)
    ).all()
    results = []
    for source in active:
        try:
            results.append(run_source(db, source))
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            results.append({"source": source.source_name, "status": "failed", "error": str(exc)[:1000]})

    log_audit(db, action="run_all_government_sources", entity_type="source_registry", entity_id="*", detail=f"{len(results)} source(s)")
    db.commit()
    return {"verification": verification, "ran": len(results), "results": results}


# --- Seeding the initial organization catalog --------------------------------

@router.get("/sources/framework-catalog", dependencies=[Depends(guard)])
def framework_catalog():
    """Preview of the curated organizations seed_framework_organizations()
    would add, without writing anything."""
    return {"organizations": [
        {"source_name": n, "official_url": u, "organization": o, "govt_level": g, "category": c}
        for n, u, o, g, c in FRAMEWORK_ORGANIZATIONS
    ]}


@router.post("/sources/seed-framework", dependencies=[Depends(guard)], status_code=201)
def seed_framework(db: Session = Depends(get_db)):
    result = seed_framework_organizations(db)
    log_audit(db, action="seed_framework_organizations", entity_type="source_registry", entity_id="*",
              detail=f"{len(result['created'])} created")
    db.commit()
    return result
