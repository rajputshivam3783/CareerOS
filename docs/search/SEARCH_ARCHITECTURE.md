# SEARCH ARCHITECTURE â€” V21.1 Unified Search Infrastructure

## Scope of this document

This document covers the backend Search Service: its data model,
provider abstraction, and API. Frontend components
(`frontend/src/components/search/`, `/search` page) are covered in
CHANGELOG_V21_1.md and RELEASE_NOTES_V21_1.md rather than duplicated
here, since they're straightforward consumers of the API this
document describes, not a second architecture of their own.

## Why one centralized service

Before this pass, CareerOS had exactly one search-shaped feature:
`GET /api/v1/search/semantic` in `app/api/platform.py`, a TF-IDF
cosine-similarity ranker over published jobs
(`app/services/semantic_search.py`). Nothing else in the codebase did
search. V21.1's job was to build the *general* case â€” jobs, government
recruitments, internships, apprenticeships, companies, government
organizations, skills, and learning resources, all through one API â€”
without duplicating that existing TF-IDF endpoint (kept, unchanged,
for callers that specifically want cosine-similarity job ranking) or
forking a second implementation per entity type.

Everything lives under `backend/app/search/`:

```
app/search/
  models.py         SearchIndexDocument, SearchQueryLog (SQLAlchemy)
  document.py        EntityType, SearchDocument, build_*_document()
  normalization.py    text/title/organization/location normalization
  indexer.py          create/update/delete/bulk index/reindex/health
  permissions.py       actor -> visibility SQL predicate
  ranking.py           deterministic, explainable scoring
  provider.py           SearchProvider ABC + DatabaseSearchProvider
  service.py             the one facade the API calls
  analytics.py             search query logging
  schemas.py                 API request/response Pydantic models
```

`app/api/search.py` is the only HTTP-facing file; it calls
`app.search.service` and nothing else. No other module in the
codebase queries `search_index_documents` directly â€” see
`app/search/indexer.py`'s docstring for why that matters.

## The document model

`SearchDocument` (`app/search/document.py`) is the normalized shape
every entity type gets mapped into before it's searchable â€” Entity
Type, Entity ID, Title, Description, Organization, Location, Skills,
Category, Tags, Dates, Status, Source, Metadata, Permissions, exactly
per the spec's SEARCH DOCUMENT MODEL section. `SearchIndexDocument`
(`app/search/models.py`) is its persisted, denormalized-column form.

### Entity types, and why there are only five source tables behind eight entity types

```
JOB / GOVERNMENT_RECRUITMENT / INTERNSHIP / APPRENTICESHIP  <- Job (job_type column)
COMPANY                                                       <- Organization
ORGANIZATION                                                  <- GovernmentOrganization
SKILL                                                         <- Skill
LEARNING_RESOURCE                                             <- LearningResource
```

V19.1's Government Recruitment Core and V18.2's job management already
unified government/private/internship/apprenticeship postings into one
`Job` table with a `job_type` column â€” building four separate job
models for search would have duplicated that. `app/search/document.py`
derives the search-facing entity type from `Job.job_type` instead
(`_JOB_TYPE_TO_ENTITY_TYPE`), so filtering by "Internship" works
without a second internship table existing anywhere.

## The index is a derived cache, not a second source of truth

`search_index_documents` is rebuilt from the real tables by
`app.search.indexer` â€” deleting every row and calling `reindex_all()`
reconstructs it exactly. It's kept fresh by a periodic scheduler job
(`careeros_search_reindex`, every `search_reindex_interval_minutes`
minutes â€” default 10, see `app/scheduler.py` and
`app/core/config.py`) rather than synchronous hooks on every
job/company/skill write path. See CHANGELOG_V21_1.md for why that
trade-off was made deliberately, not by oversight.

## Provider abstraction, and the deliberate choice not to add Elasticsearch

`SearchProvider` (`app/search/provider.py`) is an abstract interface;
`DatabaseSearchProvider` is the only implementation, querying
`search_index_documents` directly via SQLAlchemy (works against both
the SQLite used in tests/dev and the PostgreSQL used in production â€”
see `app/db/session.py`). The spec is explicit that Elasticsearch/
OpenSearch shouldn't be introduced "solely for the sake of the
feature if the repository does not need it yet" â€” it doesn't, yet.
What matters architecturally is that `SearchService` and the API layer
only ever call `SearchProvider` methods; a future
`ElasticsearchSearchProvider` is a new class implementing this
interface, not a rewrite of `service.py` or `app/api/search.py`.

## Pagination and caching

**Pagination.** Page/offset (`page`, `page_size`, `total_count`) is the
primary, always-available contract. `app/search/provider.py` also
implements cursor pagination: a cursor encodes the active sort mode
plus the `(entity_type, entity_id)` of the last item a caller saw, and
resuming from it means "start right after this specific document" in
a freshly-recomputed ordering â€” stable against a new document being
inserted into the result order between two requests, which offset
pagination isn't. This is a real, useful guarantee, but not a full
database-level keyset seek: every sort mode (including "relevance")
still derives its ordering from the same bounded candidate set
(`_CANDIDATE_CAP = 500`) on each request; the cursor changes where in
that list a response starts, not how the list is computed. See
SEARCH_API.md "Pagination" for the request/response shape.

**Caching.** `app/search/cache.py` is a short-TTL (30s), in-process
cache used only for the anonymous actor â€” never for a logged-in user,
since a cached response could contain that user's own private rows
(see SEARCH_PERMISSIONS.md) and must never be replayed to someone
else. It's invalidated on every real-time index write
(`app.search.hooks`) and every reindex, so it never masks Phase 3's
real-time indexing guarantees â€” the TTL only matters for a write path
that somehow isn't hooked. This is the same "don't add infrastructure
the repository doesn't need yet" reasoning as the provider
abstraction: a plain dict behind a lock, not a Redis dependency, with
exactly two functions (`get`/`set`) a future high-traffic deployment
could swap for a real cache backend without touching any caller.

## Request flow

```
GET /api/v1/search?q=...&filters...
  -> app/api/search.py:search()
  -> app.search.service.run_search()
       -> app.search.permissions.allowed_entity_types()
       -> DatabaseSearchProvider.search()
            -> app.search.permissions.apply_visibility()   (SQL WHERE)
            -> SQL filters (location/org/category/job_type/...)
            -> SQL text match (tokens, typo-tolerant variants)
            -> app.search.ranking.score_document()          (Python, per row)
            -> sort (relevance/newest/oldest/deadline/salary)
            -> paginate
       -> app.search.analytics.log_search()                 (fire-and-forget)
       -> no-result suggestions, if zero results
  -> SearchResponse
```

## Reuse, explicitly

- **Skill normalization** reuses `app.skill_intelligence.normalization.
  resolve_many` (the V20.5 canonical-skill/alias catalog) rather than
  building a second alias table.
- **Job model** reuses the existing `Job` table and its `job_type`
  field, no duplication.
- **Government Recruitment Core** reuses `Job`/`GovernmentOrganization`
  as-is; V21.1 adds no government-specific tables.
- **Permissions** reuse the existing role model
  (`app.core.rbac.ADMIN_ROLES`) and the existing `owner_user_id`/
  `status == "published"` visibility convention already used across
  `app/api/platform.py`, `app/api/company.py`, etc. â€” V21.1 doesn't
  invent a new authorization scheme.

