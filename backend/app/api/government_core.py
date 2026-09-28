"""V19.1 — Government Recruitment Core.

Additive API surface layered on top of the existing V16c Government
Hub (app.api.platform's /government/* read routes) and V9 admin
review pipeline (app.api.admin). Nothing here replaces those; this
module only adds:

  * GovernmentOrganization CRUD — a structured government-body catalog that
    Government Jobs may optionally link to via Job.organization_id.
    Existing Government Jobs keep working unchanged via their
    free-text Job.organization string whether or not they're ever
    linked to a row here.
  * Source Registry CRUD — a standing catalog of ingestion sources
    (distinct from the existing per-run IngestionRun log), for the
    "every future adapter registers itself here" requirement.
  * A Government-scoped moderation queue — a filtered view over the
    exact same Job.status="review" rows app.api.admin's generic
    GET /admin/review already returns; publish/reject/delete continue
    to happen through the existing admin endpoints, unchanged.
  * A duplicate-check preflight endpoint, reusing the existing
    app.ingestion.services.deduplicate.is_duplicate check.
  * A dashboard extension (latest results / latest admit cards) that
    complements — does not replace — the existing
    GET /government/home cards.

All admin-only endpoints reuse app.api.admin.guard so authentication
behaves identically to every other admin route (shared X-Admin-Key or
an admin-role JWT).
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.admin import guard
from app.core.audit import log_audit
from app.core.constants import (
    GOVERNMENT_LEVELS,
    ORGANIZATION_STATUSES,
    SOURCE_COLLECTOR_TYPES,
    SOURCE_REGISTRY_STATUSES,
)
from app.db.session import get_db
from app.ingestion.models.job_record import JobRecord
from app.ingestion.services.deduplicate import is_duplicate
from app.models.domain import GovernmentOrganization, IngestionRun, Job, RecruitmentUpdate, SourceRegistry
from app.search.hooks import sync_government_organization

router = APIRouter()


# --- Organizations -----------------------------------------------------------

class OrganizationIn(BaseModel):
    name: str
    short_name: str | None = None
    department: str | None = None
    ministry: str | None = None
    govt_level: str | None = None
    official_website: str | None = None
    official_career_url: str | None = None
    official_result_url: str | None = None
    official_admit_card_url: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    logo_url: str | None = None


class OrganizationPatch(BaseModel):
    name: str | None = None
    short_name: str | None = None
    department: str | None = None
    ministry: str | None = None
    govt_level: str | None = None
    official_website: str | None = None
    official_career_url: str | None = None
    official_result_url: str | None = None
    official_admit_card_url: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    logo_url: str | None = None
    status: str | None = None


def _validate_govt_level(govt_level: str | None) -> None:
    if govt_level is not None and govt_level not in GOVERNMENT_LEVELS:
        raise HTTPException(400, f"govt_level must be one of {GOVERNMENT_LEVELS}")


@router.get("/organizations")
def list_organizations(
    search: str | None = None,
    govt_level: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = select(GovernmentOrganization)
    if search:
        term = f"%{search.strip()}%"
        q = q.where(or_(GovernmentOrganization.name.ilike(term), GovernmentOrganization.short_name.ilike(term)))
    if govt_level:
        q = q.where(GovernmentOrganization.govt_level == govt_level)
    if status:
        q = q.where(GovernmentOrganization.status == status)
    else:
        q = q.where(GovernmentOrganization.status == "active")
    return db.scalars(q.order_by(GovernmentOrganization.name.asc()).offset(offset).limit(limit)).all()


@router.get("/organizations/{org_id}")
def get_organization(org_id: int, db: Session = Depends(get_db)):
    org = db.get(GovernmentOrganization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    return org


@router.post("/organizations", dependencies=[Depends(guard)], status_code=201)
def create_organization(payload: OrganizationIn, db: Session = Depends(get_db)):
    _validate_govt_level(payload.govt_level)
    org = GovernmentOrganization(**payload.model_dump())
    db.add(org)
    db.commit()
    db.refresh(org)
    log_audit(db, action="create_organization", entity_type="organization", entity_id=str(org.id))
    db.commit()
    sync_government_organization(db, org.id)  # V21.1 Phase 3
    db.refresh(org)  # sync_government_organization's own commit expires org — refresh before returning it
    return org


@router.patch("/organizations/{org_id}", dependencies=[Depends(guard)])
def update_organization(org_id: int, payload: OrganizationPatch, db: Session = Depends(get_db)):
    org = db.get(GovernmentOrganization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    changes = payload.model_dump(exclude_unset=True)
    if "govt_level" in changes:
        _validate_govt_level(changes["govt_level"])
    if "status" in changes and changes["status"] not in ORGANIZATION_STATUSES:
        raise HTTPException(400, f"status must be one of {ORGANIZATION_STATUSES}")
    for key, value in changes.items():
        setattr(org, key, value)
    db.commit()
    log_audit(db, action="update_organization", entity_type="organization", entity_id=str(org_id), detail=str(changes))
    db.commit()
    sync_government_organization(db, org_id)  # V21.1 Phase 3
    db.refresh(org)  # sync_government_organization's own commit expires org — refresh before returning it
    return org


@router.delete("/organizations/{org_id}", dependencies=[Depends(guard)], status_code=204)
def archive_organization(org_id: int, db: Session = Depends(get_db)):
    """Soft-delete: government organizations are referenced by
    recruitment history, so this sets status='inactive' rather than
    deleting the row (consistent with how Job archival works
    elsewhere in this codebase — see Job.archived_at)."""
    org = db.get(GovernmentOrganization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    org.status = "inactive"
    db.commit()
    log_audit(db, action="archive_organization", entity_type="organization", entity_id=str(org_id))
    db.commit()
    sync_government_organization(db, org_id)  # V21.1 Phase 3


# --- Duplicate detection -------------------------------------------------------

class DuplicateCheckIn(BaseModel):
    title: str
    organization: str
    ad_number: str | None = None
    official_url: str | None = None
    notification_url: str | None = None
    source_name: str | None = None
    source_reference: str | None = None


@router.post("/duplicate-check", dependencies=[Depends(guard)])
def duplicate_check(payload: DuplicateCheckIn, db: Session = Depends(get_db)):
    """Preflight check for the admin UI, before curating a recruitment
    by hand — reuses the same is_duplicate() logic the ingestion
    pipeline runs automatically on every adapter-sourced record."""
    record = JobRecord(
        title=payload.title,
        organization=payload.organization,
        ad_number=payload.ad_number,
        official_url=payload.official_url,
        notification_url=payload.notification_url,
        source_name=payload.source_name or "duplicate-check",
        source_reference=payload.source_reference,
    )
    return {"duplicate": is_duplicate(db, record)}


# --- Moderation queue ----------------------------------------------------------

@router.get("/moderation/queue", dependencies=[Depends(guard)])
def moderation_queue(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Government-scoped view of the existing admin review queue
    (Job.status == "review"). Approve/reject/delete continue to go
    through the existing generic admin endpoints —
    POST /admin/jobs/{id}/publish, POST /admin/jobs/{id}/reject,
    DELETE /admin/jobs/{id} — so nothing about moderation itself is
    reimplemented here."""
    base = select(Job).where(Job.status == "review", Job.job_type.ilike("Government"))
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.order_by(Job.id.desc()).offset(offset).limit(limit)).all()
    return {"total": total, "jobs": rows}


# --- Source registry -------------------------------------------------------

class SourceRegistryIn(BaseModel):
    source_name: str
    official_url: str | None = None
    collector_type: str = "official_html"
    schedule: str | None = None
    status: str = "disabled"
    # V19.2 — Official Source Adapter Framework. All optional so the
    # unchanged V19.1 payload shape (the four fields above only)
    # keeps working exactly as it always has; see
    # app.ingestion.adapters.configured for what `config` accepts per
    # collector_type.
    organization: str | None = None
    govt_level: str | None = None
    category: str | None = None
    config: dict | None = None
    priority: int = 100


class SourceRegistryPatch(BaseModel):
    official_url: str | None = None
    collector_type: str | None = None
    schedule: str | None = None
    status: str | None = None
    organization: str | None = None
    govt_level: str | None = None
    category: str | None = None
    config: dict | None = None
    priority: int | None = None


@router.get("/sources", dependencies=[Depends(guard)])
def list_sources(db: Session = Depends(get_db)):
    return db.scalars(select(SourceRegistry).order_by(SourceRegistry.source_name.asc())).all()


@router.post("/sources", dependencies=[Depends(guard)], status_code=201)
def register_source(payload: SourceRegistryIn, db: Session = Depends(get_db)):
    if payload.collector_type not in SOURCE_COLLECTOR_TYPES:
        raise HTTPException(400, f"collector_type must be one of {SOURCE_COLLECTOR_TYPES}")
    if payload.status not in SOURCE_REGISTRY_STATUSES:
        raise HTTPException(400, f"status must be one of {SOURCE_REGISTRY_STATUSES}")
    existing = db.scalar(select(SourceRegistry).where(SourceRegistry.source_name == payload.source_name))
    if existing:
        raise HTTPException(409, "A source with this name is already registered")
    data = payload.model_dump()
    if data.get("config") is not None:
        data["config"] = json.dumps(data["config"])
    source = SourceRegistry(**data)
    db.add(source)
    db.commit()
    db.refresh(source)
    log_audit(db, action="register_source", entity_type="source_registry", entity_id=str(source.id))
    db.commit()
    db.refresh(source)  # this commit expires source again — refresh before returning it
    return source


@router.patch("/sources/{source_id}", dependencies=[Depends(guard)])
def update_source(source_id: int, payload: SourceRegistryPatch, db: Session = Depends(get_db)):
    source = db.get(SourceRegistry, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    changes = payload.model_dump(exclude_unset=True)
    if "collector_type" in changes and changes["collector_type"] not in SOURCE_COLLECTOR_TYPES:
        raise HTTPException(400, f"collector_type must be one of {SOURCE_COLLECTOR_TYPES}")
    if "status" in changes and changes["status"] not in SOURCE_REGISTRY_STATUSES:
        raise HTTPException(400, f"status must be one of {SOURCE_REGISTRY_STATUSES}")
    if "config" in changes and changes["config"] is not None:
        changes["config"] = json.dumps(changes["config"])
    for key, value in changes.items():
        setattr(source, key, value)
    db.commit()
    log_audit(db, action="update_source", entity_type="source_registry", entity_id=str(source_id), detail=str(changes))
    db.commit()
    db.refresh(source)  # commit expires source — refresh before returning it
    return source


@router.post("/sources/{source_id}/sync-runs", dependencies=[Depends(guard)])
def sync_source_from_runs(source_id: int, db: Session = Depends(get_db)):
    """Roll the existing V2 IngestionRun log (app.ingestion.ingest,
    unchanged) up into this source's last_run_at/last_success_at/
    error_count summary. Additive read of an existing table — does
    not touch how ingestion runs are recorded."""
    source = db.get(SourceRegistry, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    latest_run = db.scalar(
        select(IngestionRun)
        .where(IngestionRun.source_name == source.source_name)
        .order_by(IngestionRun.started_at.desc())
        .limit(1)
    )
    if latest_run:
        source.last_run_at = latest_run.started_at
    latest_success = db.scalar(
        select(IngestionRun)
        .where(IngestionRun.source_name == source.source_name, IngestionRun.status == "success")
        .order_by(IngestionRun.started_at.desc())
        .limit(1)
    )
    if latest_success:
        source.last_success_at = latest_success.started_at
    source.error_count = db.scalar(
        select(func.count()).select_from(IngestionRun)
        .where(IngestionRun.source_name == source.source_name, IngestionRun.status == "failed")
    ) or 0
    db.commit()
    db.refresh(source)  # commit expires source — refresh before returning it
    return source


# --- Dashboard extension ------------------------------------------------------

@router.get("/dashboard/extended")
def dashboard_extended(limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
    """Complements the existing GET /government/home cards
    (latest_jobs / closing_soon / counts) with the two V19.1 cards
    that need a RecruitmentUpdate join: Latest Results and Latest
    Admit Cards. "Pending Moderation" is intentionally left out of
    this public endpoint — that count is admin-only, see
    GET /government/moderation/queue's `total` field."""
    def _latest(update_type: str):
        q = (
            select(RecruitmentUpdate, Job)
            .join(Job, Job.id == RecruitmentUpdate.job_id)
            .where(
                Job.status == "published",
                Job.job_type.ilike("Government"),
                RecruitmentUpdate.status == "published",
                RecruitmentUpdate.update_type == update_type,
            )
            .order_by(RecruitmentUpdate.event_date.desc().nullslast(), RecruitmentUpdate.id.desc())
            .limit(limit)
        )
        return [{"update": u, "job": j} for u, j in db.execute(q).all()]

    return {
        "latest_results": _latest("result"),
        "latest_admit_cards": _latest("admit_card"),
    }
