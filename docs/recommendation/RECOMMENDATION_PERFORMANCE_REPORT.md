# Recommendation Performance Report â€” V21.5

## Methodology

Same environment/caveats as SEARCH_PERFORMANCE_REPORT.md â€” SQLite,
sandbox hardware, 300 real seeded/published jobs, real HTTP calls
through the actual FastAPI app, and direct SQL query-count
instrumentation via SQLAlchemy's `before_cursor_execute` event.

## Latency results

| Operation | Result |
|---|---|
| Recommendations, cold (first compute, forced refresh, 300-job pool â†’ scored) | 230.5ms |
| Recommendations, warm (served from `RecommendationSnapshot` cache) | 25.0ms |

The cache delivers roughly a **9Ã— speedup**, confirming the
signature-based invalidation design (RECOMMENDATION_ARCHITECTURE.md)
is working as intended, not just present in code.

## N+1 query bug â€” found and fixed this release

Query-count instrumentation on a 50-job candidate pool found **167 SQL
queries for 20 returned items** â€” far more than expected. Breaking
down which statements repeated identified `SELECT
ranking_configuration...` running **exactly once per job in the pool**
(50 times for 50 jobs): V21.4's admin-configurable component weights
(`app.recommendations.ranking_config.get`) were being re-fetched from
the database inside the per-job scoring call instead of once per
request.

**Fix:** `app.recommendations.scoring.score()` now accepts an optional
pre-fetched `weights_config`; `app.recommendations.service._rank_pool`
fetches it once before the scoring loop and passes it to every call.
Backward compatible â€” `db` alone still works for any other caller.

**Verified, not just reasoned about:** re-ran the identical
instrumented request after the fix â€” query count dropped to 118 for
the same 50-job pool (the expected ~49-query reduction), and the full
V21.3/V21.4/V21.5 recommendation test suites (75 tests) still pass.

## Remaining query pattern â€” documented, not changed this release

The same instrumentation shows roughly 2 additional queries per
*displayed* item (not per pool item) from impression-event logging:
each call to `record_event` does a duplicate-check `SELECT` followed
by an `INSERT`, and independently re-fetches the `Job` row via
`db.get(Job, job_id)`. In principle `db.get()` should hit SQLAlchemy's
session identity map (no query) for a `Job` object already loaded
earlier in the same request during ranking â€” but an intervening
`db.commit()` (from saving the recommendation snapshot to cache, which
must commit to persist) expires the whole session's identity map,
forcing a real re-query on next access. This is a real, understood
inefficiency, proportional to the number of *displayed* results (not
the whole pool), and was left unchanged this release rather than risk
a deeper refactor of the event-logging/caching interaction under time
pressure. Flagged here explicitly rather than left silent.

## What this does and doesn't tell you

Confirms the caching design and the fixed N+1 bug's resolution at
small scale. Does not tell you:

- Cold-compute latency at production job-table volume (thousands+ of
  jobs in a candidate's retrieval pool, bounded by
  `MAX_RANKING_POOL=200` regardless, but retrieval itself scales with
  total table size) â€” not load-tested.
- Behavior under concurrent recommendation requests for many
  candidates simultaneously â€” not tested.
- Real Postgres query-planner performance vs. SQLite for the same
  query shapes.

## Recommendation

Same as SEARCH_PERFORMANCE_REPORT.md: run a realistic load test
against staging Postgres before a production launch at scale. The
event-logging query pattern documented above is a reasonable candidate
for a future optimization pass (e.g. passing already-loaded `Job`
objects through to the event-logging call instead of re-fetching by
id) if per-request query volume becomes a measured bottleneck.

