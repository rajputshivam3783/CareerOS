"""V21.1 — the centralized Search Service. Per the spec: "All search
functionality must use this service." This is the one function
(``run_search``) the API layer (app.api.search) calls, and the one
place that wires together permissions -> provider -> ranking ->
analytics -> no-result suggestions in a fixed order. Nothing else in
the codebase should query SearchIndexDocument directly.
"""

from __future__ import annotations

import json
import logging
import time

from sqlalchemy.orm import Session

from app.search.document import EntityType
from app.search.permissions import SearchActor, allowed_entity_types
from app.search.provider import DatabaseSearchProvider, SearchFilters, SearchPage, SearchProvider
from app.search.schemas import SearchResponse, SearchResultItem, SearchSuggestion

log = logging.getLogger("careeros.search")


# Provider is resolved once at module load. Swapping to a different
# SearchProvider implementation later (V21.2+) is a one-line change
# here — nothing above this line (or in app.api.search) needs to know.
_provider: SearchProvider = DatabaseSearchProvider()


def _no_result_suggestions(
    db: Session, *, query: str, filters: SearchFilters, actor: SearchActor
) -> list[SearchSuggestion]:
    """NO-RESULT HANDLING. Every suggestion here is derived from real
    index data (facet values, the typo-equivalents table) — never a
    fabricated result. If a broader/looser version of the same search
    genuinely has matches, say so; otherwise suggest nothing rather
    than guess."""
    from app.search.provider import _TYPO_LOOKUP

    suggestions: list[SearchSuggestion] = []

    for token in query.lower().split():
        corrected = _TYPO_LOOKUP.get(token)
        if corrected:
            suggestions.append(SearchSuggestion(kind="spelling", text=query.lower().replace(token, corrected)))

    # Alternative categories: what job types/categories DO have
    # results for filters minus the free-text query (i.e. "nothing
    # matches your search text within these filters — here's what
    # exists in these filters at all").
    facets = _provider.facets(db, facet_fields=["job_type", "category"], filters=filters, actor=actor)
    for facet_name, buckets in facets.items():
        for value, count in buckets[:3]:
            if value:
                suggestions.append(SearchSuggestion(kind="alternative_category", text=value))

    return suggestions[:5]


def run_search(
    db: Session,
    *,
    query: str,
    filters: SearchFilters,
    entity_types: list[EntityType] | None,
    page: int,
    page_size: int,
    sort: str,
    actor: SearchActor,
    cursor: str | None = None,
    log_analytics: bool = True,
) -> SearchResponse:
    """PAGINATION: page/limit/offset/total-count (``page``/``page_size``)
    is the primary, always-supported contract. ``cursor``, when
    provided, takes precedence over ``page`` — see
    app.search.provider.encode_cursor/decode_cursor's docstring for
    what a V21.1 cursor actually guarantees (stability against
    concurrent inserts shifting page boundaries) and what it doesn't
    (it isn't a DB-level keyset seek for the "relevance" sort, since
    relevance is scored in Python over a bounded candidate set — see
    SEARCH_RELEVANCE.md / SEARCH_ARCHITECTURE.md).

    PERFORMANCE / CACHING: for the anonymous actor only (see
    app.search.cache's docstring for why it's restricted to that one
    case), an identical (query, filters, entity_types, sort, page,
    cursor) request within the last 30s is served from an in-process
    cache rather than re-querying — invalidated immediately on any
    real-time index write (app.search.hooks) or manual/scheduled
    reindex (app.search.indexer.reindex_all).
    """
    started = time.perf_counter()

    filters.entity_types = allowed_entity_types(actor, entity_types)

    cache_key = None
    if actor.role == "anonymous":
        from app.search import cache

        cache_key = cache.cache_key(
            "search", query, filters, entity_types, sort, page, page_size, cursor
        )
        cached = cache.get(cache_key)
        if cached is not None:
            if log_analytics:
                _log(db, query=query, filters=filters, entity_types=entity_types, result_count=cached.total_count,
                     latency_ms=(time.perf_counter() - started) * 1000, actor=actor)
            return cached

    result = _provider.search(
        db,
        query=query,
        filters=filters,
        actor=actor,
        page=SearchPage(page=page, page_size=page_size, cursor=cursor),
        sort=sort,
    )

    items = [
        SearchResultItem(
            entity_type=EntityType(sd.document.entity_type),
            entity_id=sd.document.entity_id,
            title=sd.document.title,
            description=sd.document.description,
            organization=sd.document.organization,
            location=sd.document.location,
            category=sd.document.category,
            job_type=sd.document.job_type,
            posted_date=sd.document.posted_date,
            deadline=sd.document.deadline,
            status=sd.document.status,
            score=sd.score,
            score_factors=sd.factors,
            metadata=json.loads(sd.document.metadata_json) if sd.document.metadata_json else {},
        )
        for sd in result.items
    ]

    suggestions: list[SearchSuggestion] = []
    if result.total_count == 0:
        suggestions = _no_result_suggestions(db, query=query, filters=filters, actor=actor)

    response = SearchResponse(
        query=query,
        total_count=result.total_count,
        page=result.page,
        page_size=result.page_size,
        items=items,
        facets={},
        suggestions=suggestions,
        next_cursor=result.next_cursor,
    )

    if cache_key is not None:
        from app.search import cache

        cache.set(cache_key, response)

    latency_ms = (time.perf_counter() - started) * 1000
    if log_analytics:
        _log(db, query=query, filters=filters, entity_types=entity_types, result_count=result.total_count,
             latency_ms=latency_ms, actor=actor)

    # RECENT SEARCHES (V21.2) — only for an authenticated actor, and
    # only real, user-initiated searches (log_analytics=False is used
    # internally e.g. by facet/suggestion helpers that shouldn't count
    # as a "search the user performed"). Best-effort, never blocks or
    # fails the search response — see app.search.recent_searches.record.
    if log_analytics and actor.user_id is not None:
        from app.search import recent_searches

        recent_searches.record(
            db, user_id=actor.user_id, query=query, filters=filters,
            entity_types=entity_types, result_count=result.total_count,
        )

    return response


def _log(db: Session, *, query: str, filters: SearchFilters, entity_types, result_count: int, latency_ms: float,
          actor: SearchActor) -> None:
    from app.search.analytics import log_search

    try:
        log_search(
            db, query=query, filters=filters, entity_types=entity_types, result_count=result_count,
            latency_ms=latency_ms, actor=actor,
        )
    except Exception:
        # Best-effort telemetry — a logging failure must never break
        # the actual search response the user is waiting on.
        log.warning("Search analytics logging failed; the search response itself was unaffected.", exc_info=True)


def run_autocomplete(
    db: Session, *, prefix: str, entity_types: list[EntityType] | None, actor: SearchActor, limit: int = 10
) -> list[str]:
    resolved_types = allowed_entity_types(actor, entity_types)

    if actor.role == "anonymous":
        from app.search import cache

        cache_key = cache.cache_key("autocomplete", prefix, resolved_types, limit)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        result = _provider.autocomplete(db, prefix=prefix, entity_types=resolved_types, actor=actor, limit=limit)
        cache.set(cache_key, result)
        return result

    return _provider.autocomplete(db, prefix=prefix, entity_types=resolved_types, actor=actor, limit=limit)


def run_grouped_autocomplete(db: Session, *, prefix: str, actor: SearchActor, limit_per_group: int = 6) -> dict[str, list[str]]:
    """V21.2 — grouped variant of run_autocomplete, same caching
    posture (anonymous results cached, authenticated never cached
    since they may see private entities)."""

    if actor.role == "anonymous":
        from app.search import cache

        cache_key = cache.cache_key("autocomplete_grouped", prefix, limit_per_group)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        result = _provider.autocomplete_grouped(db, prefix=prefix, actor=actor, limit_per_group=limit_per_group)
        cache.set(cache_key, result)
        return result

    return _provider.autocomplete_grouped(db, prefix=prefix, actor=actor, limit_per_group=limit_per_group)


def run_facets(
    db: Session, *, facet_fields: list[str], filters: SearchFilters, actor: SearchActor
) -> dict[str, list[tuple[str, int]]]:
    filters.entity_types = allowed_entity_types(actor, filters.entity_types)

    if actor.role == "anonymous":
        from app.search import cache

        cache_key = cache.cache_key("facets", tuple(facet_fields), filters)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        result = _provider.facets(db, facet_fields=facet_fields, filters=filters, actor=actor)
        cache.set(cache_key, result)
        return result

    return _provider.facets(db, facet_fields=facet_fields, filters=filters, actor=actor)
