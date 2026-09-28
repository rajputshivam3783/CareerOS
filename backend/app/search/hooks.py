"""V21.1 (Phase 3) — thin hooks for near-real-time indexing.

Each function here does exactly one thing: re-derive one entity's
search document and commit it, swallowing (and logging) any error so
a search-indexing failure can never break the caller's primary
business transaction — publishing a job, verifying a company, etc.
must never fail because search indexing had a bad day.

Call one of these right after the caller's own `db.commit()` for the
entity that changed. That's the entire integration surface — see
CHANGELOG_V21_1.md for the list of call sites this was wired into.

This intentionally does NOT replace the periodic `careeros_search_reindex`
scheduler job (app/scheduler.py) — that job remains as a safety net
(catches anything a hook call site missed, a crashed process mid-write,
etc.), just no longer the *only* thing keeping the index fresh.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger("careeros.search.hooks")


def _safe(db: Session, label: str, fn) -> None:
    try:
        fn()
        db.commit()
        from app.search import cache

        cache.clear()  # V21.1 — invalidate the anonymous-search cache on every successful index write
    except Exception:
        logger.exception("V21.1 real-time reindex hook failed: %s", label)
        db.rollback()


def sync_job(db: Session, job_id: int | None) -> None:
    if job_id is None:
        return
    from app.search.indexer import index_job

    _safe(db, f"job:{job_id}", lambda: index_job(db, job_id))


def sync_company(db: Session, organization_id: int | None) -> None:
    if organization_id is None:
        return
    from app.search.indexer import index_company

    _safe(db, f"company:{organization_id}", lambda: index_company(db, organization_id))


def sync_government_organization(db: Session, organization_id: int | None) -> None:
    if organization_id is None:
        return
    from app.search.indexer import index_government_organization

    _safe(db, f"government_organization:{organization_id}", lambda: index_government_organization(db, organization_id))


def sync_skill(db: Session, skill_id: int | None) -> None:
    if skill_id is None:
        return
    from app.search.indexer import index_skill

    _safe(db, f"skill:{skill_id}", lambda: index_skill(db, skill_id))


def sync_learning_resource(db: Session, resource_id: int | None) -> None:
    if resource_id is None:
        return
    from app.search.indexer import index_learning_resource

    _safe(db, f"learning_resource:{resource_id}", lambda: index_learning_resource(db, resource_id))
