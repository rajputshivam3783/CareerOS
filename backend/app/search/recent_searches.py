"""V21.2 — RECENT SEARCHES. Per-user, privacy-scoped (see
SEARCH HISTORY PRIVACY): only the owning user can ever list, reuse, or
delete their own recent searches — no endpoint here accepts a
user_id parameter, it's always derived from the authenticated caller.

Recording is best-effort and non-blocking (same posture as
app.search.hooks._safe) — a failure to record a recent search must
never break the search request itself.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.search.document import EntityType
from app.search.models import RecentSearch
from app.search.provider import SearchFilters

logger = logging.getLogger("careeros.search.recent_searches")

MAX_PER_USER = 20


def _filters_payload(filters: SearchFilters) -> dict:
    payload = {
        "location": filters.location,
        "organization": filters.organization,
        "category": filters.category,
        "job_type": filters.job_type,
        "employment_type": filters.employment_type,
        "work_mode": filters.work_mode,
        "experience": filters.experience,
        "education": filters.education,
        "skills": sorted(filters.skills) if filters.skills else None,
        "salary_min": filters.salary_min,
        "salary_max": filters.salary_max,
    }
    return {k: v for k, v in payload.items() if v is not None}


def _search_key(query: str, entity_types: list[EntityType] | None, filters_payload: dict) -> str:
    normalized = json.dumps(
        {
            "q": (query or "").strip().lower(),
            "entity_types": sorted(e.value for e in entity_types) if entity_types else None,
            "filters": filters_payload,
        },
        sort_keys=True,
    )
    return hashlib.sha256(normalized.encode()).hexdigest()[:64]


def record(
    db: Session,
    *,
    user_id: int,
    query: str,
    filters: SearchFilters,
    entity_types: list[EntityType] | None,
    result_count: int,
) -> None:
    """Upsert one recent-search row for this user. A blank query with
    no filters isn't worth remembering (e.g. just opening the
    discovery page with no input yet) — skipped rather than recorded
    as noise."""

    if not (query or "").strip() and not entity_types and not _filters_payload(filters):
        return

    try:
        filters_payload = _filters_payload(filters)
        key = _search_key(query, entity_types, filters_payload)
        existing = db.scalar(
            select(RecentSearch).where(RecentSearch.user_id == user_id, RecentSearch.search_key == key)
        )
        if existing:
            existing.result_count = result_count
            existing.created_at = datetime.utcnow()
        else:
            db.add(
                RecentSearch(
                    user_id=user_id,
                    query=(query or "")[:500],
                    entity_types=",".join(e.value for e in entity_types) if entity_types else None,
                    filters_json=json.dumps(filters_payload) if filters_payload else None,
                    search_key=key,
                    result_count=result_count,
                )
            )
        db.commit()
        _trim(db, user_id)
    except Exception:
        logger.exception("Failed to record recent search for user %s", user_id)
        db.rollback()


def _trim(db: Session, user_id: int) -> None:
    """Keep only the MAX_PER_USER most recent rows for this user —
    recent searches is a convenience list, not an archive."""

    rows = list(
        db.scalars(
            select(RecentSearch).where(RecentSearch.user_id == user_id).order_by(RecentSearch.created_at.desc())
        )
    )
    for stale in rows[MAX_PER_USER:]:
        db.delete(stale)
    if len(rows) > MAX_PER_USER:
        db.commit()


def list_for_user(db: Session, user_id: int, limit: int = MAX_PER_USER) -> list[RecentSearch]:
    return list(
        db.scalars(
            select(RecentSearch)
            .where(RecentSearch.user_id == user_id)
            .order_by(RecentSearch.created_at.desc())
            .limit(limit)
        )
    )


def delete_one(db: Session, user_id: int, recent_search_id: int) -> bool:
    row = db.get(RecentSearch, recent_search_id)
    if not row or row.user_id != user_id:
        return False
    db.delete(row)
    db.commit()
    return True


def clear_all(db: Session, user_id: int) -> int:
    rows = list(db.scalars(select(RecentSearch).where(RecentSearch.user_id == user_id)))
    for row in rows:
        db.delete(row)
    db.commit()
    return len(rows)
