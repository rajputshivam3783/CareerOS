# AI Performance Report â€” V20.6

## Method

Direct code review of every AI-adjacent hot path (query patterns,
context building, list endpoints) plus before/after behavioral tests
where a fix was made. No load-testing infrastructure exists in this
environment, so throughput/latency numbers under real traffic are
**NOT MEASURED** â€” this report covers algorithmic/query-level findings
only, which is what code review can actually verify honestly.

## Fixes made this release

### 1. `/skills` search: Python-side filtering â†’ SQL (Fixed)
Previously loaded every row in the `skills` table into memory, then
substring-filtered in a Python list comprehension. At the current
~46-skill seed size this was invisible; it would degrade linearly as
admins grow the catalog. **Fix**: `q=` now compiles to a SQL
`ILIKE` (cross-dialect via SQLAlchemy's `.ilike()` â€” native `ILIKE` on
Postgres, `LOWER(x) LIKE LOWER(y)` on SQLite), and category/subcategory
filters were already SQL-side. Verified behavior-preserving (same
case-insensitive substring match) via
`test_skill_search_is_pushed_into_sql_not_python`.

### 2. Unbounded list endpoints (Fixed)
`/skills`, `/admin/skills`, `/admin/resources` had no result cap.
**Fix**: added a `limit` query param (default 100/200, max 500/1000,
consistent with the existing `/ai/usage/logs` pattern) to all three.

## Reviewed, no issue found

- **Context building already enforces a token budget.**
  `context_builder.build_context(max_context_tokens=settings.ai_max_context_tokens)`
  computes a real budget and trims to it â€” not a config field that
  goes unused. Confirmed by reading the implementation, not just the
  setting's existence.
- **Conversation history is capped and summarized.**
  `ai_conversation_history_max_messages` (20) bounds how much history
  is sent per request; `ai_conversation_summary_trigger` (30) rolls
  older messages into a summary rather than letting history grow
  unbounded â€” this existed before V20.6 and was re-verified via the
  existing `test_conversation_summarizes_after_trigger_threshold`.
- **No N+1 query pattern found in the V20.5 skill-gap/learning-path
  hot path** â€” `gap.py`'s `normalization.resolve_many()` builds one
  lookup dict per call (one query for all skills, one for all
  aliases) rather than querying per skill name; `learning_path.py`
  reuses that same resolved data rather than re-querying per step.
- **Rate limiting is present on every AI-triggering endpoint** across
  all four modules (`resume-ai-generate`, career-copilot message
  endpoints, interview answer submission, etc.) â€” this bounds both
  cost *and* incidental load per user, confirmed by grep across
  `app/api/*.py` for `enforce_rate_limit`.
- **Embeddings**: `embedding_service.py` reviewed â€” calls are
  synchronous and not cached, but there is no current caller of
  embedding generation in a loop or hot path in this codebase (it's
  infrastructure for a future search feature, per V20.1's own module
  map) â€” no fix needed because there's nothing exercising it yet to
  optimize.

## Not measured (honest gap)

- Real end-to-end AI response latency under load (no live provider
  credentials, no load-testing tool available in this environment)
- Database query plan / index effectiveness under production-scale
  data volume (this environment's SQLite test databases are tiny;
  Postgres `EXPLAIN ANALYZE` against realistic data was not run)
- Frontend rendering performance (bundle size was checked via `npm run
  build` output â€” no route exceeds typical Next.js page-weight
  norms â€” but no Lighthouse/Web Vitals run was performed)

## Recommendation before production launch

Run a realistic-data-volume load test against Postgres (not SQLite)
for the skill catalog, learning plans, and AI usage log tables
specifically, since those are the ones most likely to grow large in
production and weren't performance-tested against real volume in this
session.

