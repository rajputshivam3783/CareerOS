"""V21.1 — Unified Search Infrastructure API. See SEARCH_API.md.

Public, permission-aware search across every entity type (SEARCH
requirement). Reindex/index-health are admin-only (INDEX HEALTH /
REINDEX requirements) since they touch every row in the index and
reindexing is a moderately expensive operation.
"""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.admin import guard
from app.core.security import User, current_user, optional_user
from app.db.session import get_db
from app.search import indexer, recent_searches, service
from app.search.document import EntityType
from app.search.permissions import SearchActor
from app.search.provider import SearchFilters
from app.search.schemas import (
    AutocompleteResponse,
    GroupedAutocompleteResponse,
    IndexHealthResponse,
    ReindexResponse,
    RecentSearchOut,
    SearchResponse,
)

router = APIRouter()
admin_router = APIRouter()


def _parse_entity_types(entity_type: list[str] | None) -> list[EntityType] | None:
    if not entity_type:
        return None
    resolved = []
    for value in entity_type:
        try:
            resolved.append(EntityType(value.upper()))
        except ValueError:
            continue  # Unknown entity type strings are ignored, not a 400 — keeps the API lenient for future values.
    return resolved or None


@router.get("/search", response_model=SearchResponse, tags=["V21.1 Unified Search Infrastructure"])
def search(
    q: str = Query(default="", max_length=300, description="Free-text search query"),
    entity_type: list[str] | None = Query(default=None, description="Repeat to filter to multiple entity types"),
    location: str | None = Query(default=None, max_length=200),
    organization: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=200),
    job_type: str | None = Query(default=None, max_length=60),
    employment_type: str | None = Query(default=None, max_length=60),
    work_mode: str | None = Query(default=None, max_length=60),
    experience: str | None = Query(default=None, max_length=120),
    education: str | None = Query(default=None, max_length=200),
    skills: list[str] | None = Query(default=None, max_length=100, description="Repeat to filter by multiple required skills"),
    salary_min: float | None = None,
    salary_max: float | None = None,
    status: str | None = Query(default=None, description="Admins/owners only — defaults to public documents"),
    posted_after: date | None = None,
    deadline_before: date | None = None,
    sort: str = Query(default="relevance", pattern="^(relevance|newest|oldest|deadline|salary|salary_desc|salary_asc)$"),
    page: int = Query(default=1, ge=1, description="Ignored when `cursor` is provided"),
    page_size: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(
        default=None,
        description="PAGINATION — opaque token from a previous response's `next_cursor`. "
        "Takes precedence over `page` when provided; stable against concurrent inserts. "
        "Must have been minted under the same `sort` — a mismatched cursor is ignored, not an error.",
    ),
    current: User | None = Depends(optional_user),
    db: Session = Depends(get_db),
) -> SearchResponse:
    filters = SearchFilters(
        location=location,
        organization=organization,
        category=category,
        job_type=job_type,
        employment_type=employment_type,
        work_mode=work_mode,
        experience=experience,
        education=education,
        skills=skills,
        salary_min=salary_min,
        salary_max=salary_max,
        status=status,
        posted_after=posted_after,
        deadline_before=deadline_before,
    )
    return service.run_search(
        db,
        query=q,
        filters=filters,
        entity_types=_parse_entity_types(entity_type),
        page=page,
        page_size=page_size,
        cursor=cursor,
        sort=sort,
        actor=SearchActor.from_user(current),
    )


@router.get("/search/autocomplete", response_model=AutocompleteResponse, tags=["V21.1 Unified Search Infrastructure"])
def autocomplete(
    # No min_length: default="" must itself be a valid value (an
    # omitted `q` means "no query yet, nothing to suggest" — a normal,
    # graceful case per SEARCH CORRECTNESS's empty-query requirement,
    # not an error). A min_length=1 here previously made every request
    # that omitted `q` 422 instead of returning [] — found by actually
    # validating the generated OpenAPI schema, which flagged the
    # schema's own default value as violating its own minLength.
    q: str = Query(default="", max_length=200),
    entity_type: list[str] | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=25),
    current: User | None = Depends(optional_user),
    db: Session = Depends(get_db),
) -> AutocompleteResponse:
    suggestions = service.run_autocomplete(
        db,
        prefix=q,
        entity_types=_parse_entity_types(entity_type),
        actor=SearchActor.from_user(current),
        limit=limit,
    )
    return AutocompleteResponse(suggestions=suggestions)


@router.get(
    "/search/autocomplete/grouped", response_model=GroupedAutocompleteResponse, tags=["V21.2 Advanced Job Search"]
)
def autocomplete_grouped(
    q: str = Query(default="", max_length=200),  # see autocomplete() above for why no min_length
    limit_per_group: int = Query(default=6, ge=1, le=15),
    current: User | None = Depends(optional_user),
    db: Session = Depends(get_db),
) -> GroupedAutocompleteResponse:
    groups = service.run_grouped_autocomplete(db, prefix=q, actor=SearchActor.from_user(current), limit_per_group=limit_per_group)
    return GroupedAutocompleteResponse(groups=groups)


@router.get("/search/facets", tags=["V21.1 Unified Search Infrastructure"])
def facets(
    facet: list[str] = Query(default=["job_type", "location", "category"]),
    entity_type: list[str] | None = Query(default=None),
    current: User | None = Depends(optional_user),
    db: Session = Depends(get_db),
) -> dict:
    filters = SearchFilters(entity_types=_parse_entity_types(entity_type))
    result = service.run_facets(db, facet_fields=facet, filters=filters, actor=SearchActor.from_user(current))
    return {name: [{"value": value, "count": count} for value, count in buckets] for name, buckets in result.items()}


@admin_router.post("/search/reindex", response_model=ReindexResponse, tags=["V21.1 Unified Search Infrastructure"])
def reindex(_: None = Depends(guard), db: Session = Depends(get_db)) -> ReindexResponse:
    results = indexer.reindex_all(db)
    return ReindexResponse(
        results=[r.__dict__ for r in results],
        total_indexed=sum(r.indexed for r in results),
        total_errors=sum(r.errors for r in results),
    )


@admin_router.get(
    "/search/index-health", response_model=IndexHealthResponse, tags=["V21.1 Unified Search Infrastructure"]
)
def index_health(_: None = Depends(guard), db: Session = Depends(get_db)) -> IndexHealthResponse:
    return IndexHealthResponse(**indexer.index_health(db))


# ---------------------------------------------------------------------------
# V21.2 — Recent Searches. Every endpoint below is scoped to the
# authenticated caller only (SEARCH HISTORY PRIVACY: never another
# candidate, recruiter, company, or — beyond aggregate operational
# data — an admin). No route here accepts a user_id parameter.
# ---------------------------------------------------------------------------


def _recent_search_out(row) -> RecentSearchOut:
    return RecentSearchOut(
        id=row.id,
        query=row.query,
        entity_types=row.entity_types.split(",") if row.entity_types else [],
        filters=json.loads(row.filters_json) if row.filters_json else {},
        result_count=row.result_count,
        created_at=row.created_at.isoformat(),
    )


@router.get("/search/recent", response_model=list[RecentSearchOut], tags=["V21.2 Advanced Job Search"])
def get_recent_searches(u: User = Depends(current_user), db: Session = Depends(get_db)) -> list[RecentSearchOut]:
    return [_recent_search_out(r) for r in recent_searches.list_for_user(db, u.id)]


@router.delete("/search/recent/{recent_search_id}", status_code=204, tags=["V21.2 Advanced Job Search"])
def delete_recent_search(recent_search_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    if not recent_searches.delete_one(db, u.id, recent_search_id):
        raise HTTPException(404, "Recent search not found")


@router.delete("/search/recent", tags=["V21.2 Advanced Job Search"])
def clear_recent_searches(u: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    count = recent_searches.clear_all(db, u.id)
    return {"cleared": count}
