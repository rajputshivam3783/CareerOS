"""V21.1 — request/response shapes for /search*. Kept separate from
app.search.provider's internal dataclasses (SearchFilters etc.) so the
wire format can evolve independently of the provider's internal
representation."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.search.document import EntityType

SORT_OPTIONS = ("relevance", "newest", "oldest", "deadline", "salary", "salary_desc", "salary_asc")


class SearchResultItem(BaseModel):
    entity_type: EntityType
    entity_id: int
    title: str
    description: str | None = None
    organization: str | None = None
    location: str | None = None
    category: str | None = None
    job_type: str | None = None
    posted_date: date | None = None
    deadline: date | None = None
    status: str
    score: float
    score_factors: dict[str, float] = Field(
        default_factory=dict, description="Explainable per-factor contribution to `score` — see SEARCH_RELEVANCE.md"
    )
    metadata: dict = Field(default_factory=dict)


class SearchSuggestion(BaseModel):
    """NO-RESULT HANDLING — a suggestion offered when a search returns
    zero results. `kind` tells the client what to render it as."""

    kind: str  # "spelling" / "related_term" / "alternative_category"
    text: str


class SearchResponse(BaseModel):
    query: str
    total_count: int
    page: int
    page_size: int
    items: list[SearchResultItem]
    facets: dict[str, list[dict]] = Field(default_factory=dict)
    suggestions: list[SearchSuggestion] = Field(default_factory=list)
    next_cursor: str | None = Field(
        default=None,
        description="PAGINATION — opaque cursor for the next page, stable against concurrent inserts. "
        "Pass back as `cursor` to resume; omit to keep using page/page_size. None means this is the last page.",
    )


class AutocompleteResponse(BaseModel):
    suggestions: list[str]


class GroupedAutocompleteResponse(BaseModel):
    """V21.2 — GET /search/autocomplete/grouped. Keys present only
    when that group has at least one match (job_titles/companies/
    organizations/skills/locations) — an empty group is omitted
    rather than sent as an empty list, so the frontend doesn't render
    a heading with nothing under it."""

    groups: dict[str, list[str]] = Field(default_factory=dict)


class RecentSearchOut(BaseModel):
    """V21.2 — one entry in GET /search/recent. Deliberately does not
    include the raw filters_json blob in a re-runnable-URL-unfriendly
    shape — ``filters`` is the already-decoded dict, ``entity_types``
    an already-split list, so the frontend can rebuild the exact
    search URL (SEARCH STATE / RECENT SEARCHES "Reuse") without doing
    any parsing itself."""

    id: int
    query: str
    entity_types: list[str] = Field(default_factory=list)
    filters: dict = Field(default_factory=dict)
    result_count: int
    created_at: str


class IndexHealthResponse(BaseModel):
    total_documents: int
    last_indexed_at: str | None
    by_entity_type: dict[str, dict]
    healthy: bool


class ReindexResponse(BaseModel):
    results: list[dict]
    total_indexed: int
    total_errors: int
