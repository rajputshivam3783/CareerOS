# Recommendation Engine â€” Production Guide

## Endpoints

Mounted at `/api/v1/job-recommendations` â€” not `/recommendations`,
which is a different, older, pre-existing endpoint (V6,
`app.api.platform` â€” see RECOMMENDATION_ARCHITECTURE.md for the full
naming rationale).

| Endpoint | Purpose |
|---|---|
| `GET /job-recommendations` | "Jobs For You" â€” the main feed, cached |
| `POST /job-recommendations/refresh` | Force a recompute, bypassing the cache |
| `GET /job-recommendations/{job_id}/explanation` | Always scored fresh â€” never stale even if the cached feed hasn't refreshed |
| `POST /job-recommendations/{job_id}/feedback` | Interested/Not Interested/Dismiss/Not Relevant |
| `POST /job-recommendations/{job_id}/event` | Impression/open/save/apply/dismiss analytics signal |
| `GET`/`PUT /job-recommendations/preferences` | Which opportunity types to include, diversity level |
| `GET /job-recommendations/analytics` | Admin-only, aggregate counts + CTR/conversion |
| `GET`/`PUT /job-recommendations/admin/ranking-config/{key}` | Admin-only, V21.4 component/event weight tuning |
| `POST /job-recommendations/admin/ranking-config/reset` | Admin-only, revert to defaults |

## Caching and refresh

`RecommendationSnapshot`, one row per user, keyed by an
`input_signature` hash of every signal that could change the result
(resume upload time, career-preference update time, saved/applied/
feedback counts, newest `updated_at` across published jobs). Reused
while unchanged and within a 6-hour TTL; recomputed on mismatch, TTL
expiry, or an explicit refresh call. Verified this release: measured
~230ms cold vs. ~25ms warm on a 300-job pool â€” roughly a 9Ã— speedup
from the cache (see RECOMMENDATION_PERFORMANCE_REPORT.md).

## Government recommendations

Never say "You are eligible" unless `app.services.eligibility` returns
a confirmed positive verdict against a complete profile. Everything
else is worded "Potentially relevant" or "Not clearly eligible" â€” one
enforcement point (`app.recommendations.government.assess`), verified
by test.

## Cold start

A candidate with no resume, no career goal, and no profile skills
still gets a real, labelled (`is_cold_start: true`) response â€” recent
jobs by default, plus a real-engagement-based "popular verified jobs"
pool (never a fabricated popularity number).

## Feedback loop

Dismiss/Not Relevant/Not Interested exclude that specific job from
future recommendations for that candidate â€” verified per-user isolated
(user A's dismissal never affects user B). One negative action on one
job never removes an entire category or opportunity type; that's a
separate, explicit preference toggle.

## Diversity, dedup, exclusion

`Job.id` is the canonical identity (ingestion already dedupes across
sources before a row reaches the `jobs` table). Diversity is a
post-ranking reorder only â€” capped company/location/title repetition
within a small lookahead window â€” never a relevance cut; a
higher-scored item is never demoted for variety's sake. Expired
(deadline passed) and closed/unpublished jobs are excluded at both
retrieval and ranking time â€” verified this release with a dedicated
expired-deadline test.

## Performance (V21.5 finding + fix)

A real N+1 query bug was found and fixed this release: V21.4's
admin-configurable ranking weights (`ranking_config.get`) were being
re-queried from the database once per job in the scoring loop â€” 50
identical queries for a 50-job pool. Fixed to fetch once per request
and reuse across the whole pool; verified via direct query-count
instrumentation before/after. See RECOMMENDATION_PERFORMANCE_REPORT.md
for the numbers and one remaining, smaller, documented pattern that
was not changed this release.

## Known limitations (carried forward, still true)

- No load testing at production job-table volume beyond the 300-job
  measurement in this release.
- Event deduplication (`app.recommendations.events._is_duplicate`) is
  a `SELECT` then `INSERT` with no DB-level unique constraint â€” a
  genuine race under true concurrent duplicate requests is possible
  and was not fixed or load-tested this release (inherited from
  V21.4's own report).
- `retention.purge_old_events` exists and is callable but isn't wired
  into a scheduled job.
- No statistical fairness audit â€” this codebase has no demographic
  data on candidates beyond the two Government-eligibility fields
  (reservation category, PwD status), which are structurally excluded
  from ranking (verified this release by both a static field-name
  check and a runtime test that injects a bogus weight key and
  confirms it has zero scoring effect) â€” but there is no protected-
  attribute dataset to run a disparate-impact test against in the
  first place.

