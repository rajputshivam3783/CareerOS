"""V21.1 — SEARCH INDEX abstraction: create / update / delete / bulk
index / reindex / partial update / index health.

This is the *only* code path allowed to write to
``search_index_documents`` — everything else (the provider, the
service, the API) only reads it. That keeps "how a source row becomes
a search document" defined in exactly one place (app.search.document),
so V21.2's provider swap (Elasticsearch/OpenSearch/etc.) only needs a
new provider implementation, not a new indexer.

V21.1 scope note: this module is called on-demand (from the admin
reindex endpoint and the periodic scheduler job — see app.scheduler)
rather than from every entity write path (job creation, company
verification, etc.). Wiring real-time incremental indexing into each
of those write paths is real cross-cutting surgery across
recruiter.py/admin.py/government_core.py/company.py/skill_intelligence
and is left for a follow-up phase rather than risking those flows in
this pass — see CHANGELOG_V21_1.md "Not yet done". A published job is
guaranteed to appear in search within one scheduler interval
(default: every 10 minutes; see app.scheduler) even without it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.domain import GovernmentOrganization, Job, LearningResource, Organization, Skill
from app.search.document import EntityType, SearchDocument, build_company_document, build_government_organization_document, build_job_document, build_learning_resource_document, build_skill_document
from app.search.models import SearchIndexDocument

logger = logging.getLogger("careeros.search.indexer")


@dataclass
class IndexResult:
    entity_type: str
    indexed: int = 0
    deleted: int = 0
    errors: int = 0


def _upsert(db: Session, doc: SearchDocument) -> None:
    row_kwargs = doc.as_row_kwargs()
    existing = db.scalars(
        select(SearchIndexDocument).where(
            SearchIndexDocument.entity_type == doc.entity_type.value,
            SearchIndexDocument.entity_id == doc.entity_id,
        )
    ).first()
    if existing:
        for key, value in row_kwargs.items():
            setattr(existing, key, value)
    else:
        db.add(SearchIndexDocument(**row_kwargs))


def index_job(db: Session, job_id: int) -> bool:
    """Create or update the search document for one Job. Returns False
    (and removes any stale index row) if the job no longer exists —
    lets a caller treat "job was deleted" and "job never existed" the
    same way without a separate delete call."""
    job = db.get(Job, job_id)
    if not job:
        delete_entity(db, EntityType.JOB, job_id)
        for et in (EntityType.GOVERNMENT_RECRUITMENT, EntityType.INTERNSHIP, EntityType.APPRENTICESHIP):
            delete_entity(db, et, job_id)
        return False
    _upsert(db, build_job_document(db, job))
    return True


def index_government_organization(db: Session, org_id: int) -> bool:
    org = db.get(GovernmentOrganization, org_id)
    if not org:
        delete_entity(db, EntityType.ORGANIZATION, org_id)
        return False
    _upsert(db, build_government_organization_document(org))
    return True


def index_company(db: Session, org_id: int) -> bool:
    org = db.get(Organization, org_id)
    if not org:
        delete_entity(db, EntityType.COMPANY, org_id)
        return False
    _upsert(db, build_company_document(org))
    return True


def index_skill(db: Session, skill_id: int) -> bool:
    skill = db.get(Skill, skill_id)
    if not skill:
        delete_entity(db, EntityType.SKILL, skill_id)
        return False
    _upsert(db, build_skill_document(skill))
    return True


def index_learning_resource(db: Session, resource_id: int) -> bool:
    resource = db.get(LearningResource, resource_id)
    if not resource:
        delete_entity(db, EntityType.LEARNING_RESOURCE, resource_id)
        return False
    skill = db.get(Skill, resource.skill_id) if resource.skill_id else None
    _upsert(db, build_learning_resource_document(db, resource, skill))
    return True


def delete_entity(db: Session, entity_type: EntityType, entity_id: int) -> None:
    db.execute(
        delete(SearchIndexDocument).where(
            SearchIndexDocument.entity_type == entity_type.value,
            SearchIndexDocument.entity_id == entity_id,
        )
    )


_INDEXABLE_ENTITY_TYPES = (
    EntityType.JOB,  # bulk_index("JOB") walks the Job table for all job-family entity types at once
    EntityType.ORGANIZATION,
    EntityType.COMPANY,
    EntityType.SKILL,
    EntityType.LEARNING_RESOURCE,
)


def bulk_index(db: Session, entity_type: EntityType, *, commit_every: int = 200) -> IndexResult:
    """Bulk (re)index every row of the source table backing
    ``entity_type``. Commits in batches so reindexing a large table
    doesn't hold one giant transaction open."""
    result = IndexResult(entity_type=entity_type.value)

    if entity_type in (EntityType.JOB, EntityType.GOVERNMENT_RECRUITMENT, EntityType.INTERNSHIP, EntityType.APPRENTICESHIP):
        ids = db.scalars(select(Job.id)).all()
        for i, job_id in enumerate(ids, start=1):
            try:
                index_job(db, job_id)
                result.indexed += 1
            except Exception:
                logger.exception("Failed to index Job id=%s", job_id)
                result.errors += 1
            if i % commit_every == 0:
                db.commit()
        db.commit()
        return result

    if entity_type == EntityType.ORGANIZATION:
        ids = db.scalars(select(GovernmentOrganization.id)).all()
        indexer = index_government_organization
    elif entity_type == EntityType.COMPANY:
        ids = db.scalars(select(Organization.id)).all()
        indexer = index_company
    elif entity_type == EntityType.SKILL:
        ids = db.scalars(select(Skill.id)).all()
        indexer = index_skill
    elif entity_type == EntityType.LEARNING_RESOURCE:
        ids = db.scalars(select(LearningResource.id)).all()
        indexer = index_learning_resource
    else:
        raise ValueError(f"Unsupported entity_type for bulk_index: {entity_type}")

    for i, entity_id in enumerate(ids, start=1):
        try:
            indexer(db, entity_id)
            result.indexed += 1
        except Exception:
            logger.exception("Failed to index %s id=%s", entity_type.value, entity_id)
            result.errors += 1
        if i % commit_every == 0:
            db.commit()
    db.commit()
    return result


def reindex_all(db: Session) -> list[IndexResult]:
    """Full reindex of every entity type, from scratch. Idempotent —
    upserts by (entity_type, entity_id), so running it twice in a row
    is safe and produces the same index state (modulo source data
    having changed in between)."""
    results = [bulk_index(db, et) for et in _INDEXABLE_ENTITY_TYPES]
    from app.search import cache

    cache.clear()  # V21.1 — a manual/scheduled reindex invalidates the anonymous-search cache too
    return results


def index_health(db: Session) -> dict:
    """SEARCH INDEX 'Index Health' requirement: per-entity-type
    document counts in the index versus the source table, so a stale
    or partially-failed reindex is visible rather than silent."""
    from sqlalchemy import func

    source_counts = {
        "JOB_FAMILY": db.scalar(select(func.count()).select_from(Job)) or 0,
        EntityType.ORGANIZATION.value: db.scalar(select(func.count()).select_from(GovernmentOrganization)) or 0,
        EntityType.COMPANY.value: db.scalar(select(func.count()).select_from(Organization)) or 0,
        EntityType.SKILL.value: db.scalar(select(func.count()).select_from(Skill)) or 0,
        EntityType.LEARNING_RESOURCE.value: db.scalar(select(func.count()).select_from(LearningResource)) or 0,
    }

    index_counts_rows = db.execute(
        select(SearchIndexDocument.entity_type, func.count()).group_by(SearchIndexDocument.entity_type)
    ).all()
    index_counts = {row[0]: row[1] for row in index_counts_rows}
    job_family_indexed = sum(
        index_counts.get(et.value, 0)
        for et in (EntityType.JOB, EntityType.GOVERNMENT_RECRUITMENT, EntityType.INTERNSHIP, EntityType.APPRENTICESHIP)
    )

    total_indexed = sum(index_counts.values())
    last_indexed_at = db.scalar(select(func.max(SearchIndexDocument.indexed_at)))

    return {
        "total_documents": total_indexed,
        "last_indexed_at": last_indexed_at.isoformat() if last_indexed_at else None,
        "by_entity_type": {
            "JOB_FAMILY": {"source_rows": source_counts["JOB_FAMILY"], "indexed": job_family_indexed},
            EntityType.ORGANIZATION.value: {
                "source_rows": source_counts[EntityType.ORGANIZATION.value],
                "indexed": index_counts.get(EntityType.ORGANIZATION.value, 0),
            },
            EntityType.COMPANY.value: {
                "source_rows": source_counts[EntityType.COMPANY.value],
                "indexed": index_counts.get(EntityType.COMPANY.value, 0),
            },
            EntityType.SKILL.value: {
                "source_rows": source_counts[EntityType.SKILL.value],
                "indexed": index_counts.get(EntityType.SKILL.value, 0),
            },
            EntityType.LEARNING_RESOURCE.value: {
                "source_rows": source_counts[EntityType.LEARNING_RESOURCE.value],
                "indexed": index_counts.get(EntityType.LEARNING_RESOURCE.value, 0),
            },
        },
        "healthy": all(
            index_counts.get(et.value, 0) <= source_counts.get(et.value, 10**9)
            for et in (EntityType.ORGANIZATION, EntityType.COMPANY, EntityType.SKILL, EntityType.LEARNING_RESOURCE)
        )
        and job_family_indexed <= source_counts["JOB_FAMILY"],
    }
