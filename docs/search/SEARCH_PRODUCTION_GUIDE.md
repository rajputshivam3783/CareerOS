# Search â€” Production Guide

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/search` | Main search â€” `q` (â‰¤300 chars), filters, `sort` (relevance/newest/oldest/deadline/salary), `page`/`page_size` (â‰¤100), `cursor` |
| `GET /api/v1/search/autocomplete` | Prefix suggestions |
| `GET /api/v1/search/facets` | Filter-option counts for the current query |
| `GET /api/v1/search/recent` | The caller's own recent searches |
| `DELETE /api/v1/search/recent/{id}` / `DELETE /api/v1/search/recent` | Delete one / all â€” candidate-owned, self-service |

All are validated by Pydantic before reaching the query layer â€” an
invalid `sort` value, an over-limit `page_size`, or a `page < 1` is a
clean `422`, never a 500 (verified â€” see SEARCH_SECURITY_AUDIT.md).

## Query correctness, verified by direct testing this release

Exact, partial, phrase, skill, location, company, and government
searches all go through the same `DatabaseSearchProvider`; mixed
queries combine query text + structured filters in one call. Edge
cases specifically tested: empty query, whitespace-only query, unicode/
emoji, a 500-character query (â†’ 422, not truncation), a query matching
nothing (â†’ `items: [], total_count: 0`, not an error), and 8 distinct
SQL/search-injection payloads (all handled as literal text â€” see
SEARCH_SECURITY_AUDIT.md).

## Filters

Location, skills, experience, salary range, work mode, employment
type, company, industry, education, government organization,
qualification, state, deadline, posted-date are all AND-combined in
`SearchFilters`. Every filter narrows via `SearchActor`-scoped,
parameterized SQLAlchemy â€” a filter can never surface a job the
requesting actor isn't authorized to see, and combining filters can
only narrow results further, never leak something a single filter
alone would have excluded.

## Pagination

Cursor-based, stable against concurrent inserts (see
`SearchResponse.next_cursor`'s docstring). Verified this release: no
duplicate job appears across two pages of the same query, and an
out-of-range page returns an empty list, not an error.

## Sorting

`relevance` (default, scored), `newest`/`oldest` (by posted date),
`deadline`, `salary`. Verified this release: repeated identical
queries with an explicit sort return byte-identical ordering
(deterministic â€” no unstable tie-breaking).

## Job data quality

A job is only ever returned if it's `status == "published"` (enforced
by `SearchActor` visibility, same rule for every consumer including
recommendations) **and** its deadline (if set) hasn't passed â€”
deadline expiry is checked explicitly since it does not automatically
flip `Job.status` anywhere in the codebase (confirmed by reading
`app/scheduler.py`/`app/services/automation.py`). Duplicate canonical
jobs are prevented at ingestion (`app.ingestion.ingest`: "Adapter ->
Normalize -> Deduplicate -> Review queue") â€” verified this release by
adding unique-title fixtures to previously-colliding test files and
confirming the real dedup logic is what was firing, not a test
artifact (see TEST_REPORT_V21_5.md).

## Indexing

`sync_job(db, job.id)` runs synchronously on every publish/update/
close/archive â€” real-time, not batch-only. A scheduled reindex also
runs periodically (`app.scheduler`) as a consistency backstop.

## Caching

`app.search.cache` â€” short-TTL result caching keyed by the full query
shape (query + filters + sort + page). Analytics logging
(`app.search.service._log`) is best-effort: **fixed this release** â€”
a logging failure no longer breaks the search response itself
(verified by a test that injects a forced logging failure and
confirms `200` is still returned).

## Optional performance extension

`v21_1_unified_search.sql` optionally creates a `pg_trgm` GIN index to
speed up `ILIKE` scans at volume; wrapped in a `DO $$ ... EXCEPTION
WHEN insufficient_privilege OR feature_not_supported$$` block so a
managed Postgres instance without the extension (or without
CREATE EXTENSION privilege) degrades to a full scan instead of failing
the migration. Confirmed this release that the migration script now
parses this block correctly (see V21_PRODUCTION_READINESS.md â€” the
splitter had a real bug here, fixed).

## Known limitations

- No load testing at production-scale job-table volume; latency was
  measured with 300 seeded jobs (see SEARCH_PERFORMANCE_REPORT.md),
  not millions.
- `pg_trgm` availability on the target Postgres instance/image is
  assumed, not verified against every possible managed-Postgres
  provider â€” the migration degrades gracefully either way.

