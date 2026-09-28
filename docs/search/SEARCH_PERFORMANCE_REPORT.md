# Search Performance Report â€” V21.5

## Methodology

Measured directly against a running instance of this application
(SQLite, this sandbox's hardware â€” not representative of production
Postgres/hardware, reported honestly as a relative/sanity-check
measurement, not a production SLA). 300 real jobs were ingested and
published through the actual `/admin/ingest` + `/admin/jobs/{id}/publish`
endpoints (so indexing, not just DB inserts, is included), then live
HTTP requests were timed end-to-end.

## Results

| Operation | Result |
|---|---|
| Ingest + publish (incl. real-time indexing), 300 jobs | 14.4ms/job average |
| Search (`GET /search`), 5 varied queries, 300-job index | min 5.3ms / avg 11.6ms / max 16.5ms |
| Autocomplete | 4.8ms |

## Query-count check (N+1 detection)

Instrumented via SQLAlchemy's `before_cursor_execute` event to count
actual SQL statements per request â€” not estimated.

| Operation | Result |
|---|---|
| `GET /search`, 20 returned items | **2 SQL queries** â€” no N+1 pattern found |

Search's query pattern is clean: one query for the page of results,
one for the total count. No further investigation needed here.

## What this does and doesn't tell you

This confirms search is fast and query-efficient at a *small* scale
(hundreds of jobs) on *modest* hardware (a shared sandbox VM, SQLite).
It does not tell you:

- Latency at production scale (tens of thousands to millions of job
  rows) â€” not tested; the `pg_trgm` trigram index
  (`v21_1_unified_search.sql`) exists specifically to keep `ILIKE`
  scans fast at that volume, but its effect was not benchmarked here.
- Behavior under concurrent load (many simultaneous searchers) â€” not
  tested; no load-testing tool was introduced for this pass, per the
  spec's "do not introduce infrastructure merely for benchmarking."
- Real Postgres performance characteristics vs. SQLite (different
  query planner, different index behavior) â€” the schema and query
  shapes are the same, but absolute numbers will differ.

## Recommendation

Before a production launch at meaningful scale, run a realistic
load/latency test against a staging Postgres instance sized close to
expected production data volume. This was explicitly out of scope for
what this sandboxed engagement could measure.

