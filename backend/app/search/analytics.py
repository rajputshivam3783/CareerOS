"""V21.1 — SEARCH ANALYTICS. Deliberately minimal: query text,
filters, entity types, result count, latency, and whether it was a
no-result search — enough to answer "what are people searching for
that returns nothing" without building a per-user search-history
feature nobody asked for (see SearchQueryLog's docstring for the
"why no user id" reasoning)."""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.search.document import EntityType
from app.search.models import SearchQueryLog
from app.search.permissions import SearchActor
from app.search.provider import SearchFilters

logger = logging.getLogger("careeros.search.analytics")


def _filters_to_json(filters: SearchFilters) -> str:
    payload = {
        "location": filters.location,
        "organization": filters.organization,
        "category": filters.category,
        "job_type": filters.job_type,
        "employment_type": filters.employment_type,
        "work_mode": filters.work_mode,
        "experience": filters.experience,
        "education": filters.education,
        "skills": filters.skills,
        "salary_min": filters.salary_min,
        "salary_max": filters.salary_max,
        "status": filters.status,
    }
    return json.dumps({k: v for k, v in payload.items() if v is not None})


def log_search(
    db: Session,
    *,
    query: str,
    filters: SearchFilters,
    entity_types: list[EntityType] | None,
    result_count: int,
    latency_ms: float,
    actor: SearchActor,
) -> None:
    try:
        db.add(
            SearchQueryLog(
                query=(query or "")[:500],
                entity_types=",".join(e.value for e in entity_types) if entity_types else None,
                filters_json=_filters_to_json(filters),
                result_count=result_count,
                latency_ms=latency_ms,
                had_results=result_count > 0,
                actor_role=actor.role,
            )
        )
        db.commit()
    except Exception:
        # Analytics must never break a search request.
        logger.exception("Failed to log search query")
        db.rollback()
