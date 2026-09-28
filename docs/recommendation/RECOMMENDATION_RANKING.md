# Recommendation Ranking â€” V21.3

## Ranking order

Within `app/recommendations/service.py::_rank_pool`, every job in the
Stage-1 candidate pool (see RECOMMENDATION_ARCHITECTURE.md) is scored
independently and the resulting list is sorted purely by
`overall_score` descending. Ties are not further broken â€” insertion
order (Stage-1 retrieval order, itself relevance/recency-sorted by
search) decides ties, which is stable and reproducible for a given
pool.

## Duplicate prevention

`Job.id` is the canonical identity for a job. V21's ingestion pipeline
(`app.ingestion.ingest`: "Adapter -> Normalize -> Deduplicate -> Review
queue") already deduplicates near-identical postings from multiple
sources *before* a row ever reaches the `jobs` table â€” there is no
second canonicalization step to reinvent in the recommendation engine.
`app/recommendations/diversity.py::dedupe_by_job_id` only needs to
guard against the same `Job.id` appearing twice in one ranked list
(e.g. if it matched via more than one Stage-1 retrieval query), which
it does by construction (dict keyed by id, keeps the first/highest-
scored occurrence).

## Diversity

Applied strictly after ranking, and never as a relevance cut â€” "Do not
sacrifice relevance just to increase diversity" is enforced
structurally: `apply_diversity()` walks the score-sorted list once and,
for each output slot, looks ahead at most 12 items for the
highest-scored one that doesn't exceed a per-company/per-location/
per-title cap (set by `RecommendationPreference.diversity_level` â€”
low/balanced/high). If every item in that lookahead window is already
over-cap, it falls back to the plain highest-scored remaining item
rather than skipping it. This guarantees no item is ever promoted more
than 11 positions above its score-sorted rank, and the output is
always a bounded reordering of the top-N by score, never a
lower-relevance substitution.

## Ranking pool size

Bounded at `MAX_RANKING_POOL = 200` (service.py) â€” Stage 1 already
caps retrieval at 150 (widened once to ~300 if a location filter
over-narrows it), plus up to 30 cold-start popular jobs. This keeps a
single recommendation request to a bounded number of scoring
computations regardless of total job-table size, per the PERFORMANCE
requirement ("Do not calculate recommendations from every job on every
page request").

## Category filtering vs. ranking

`GET /job-recommendations?category=...` filters the already-ranked,
already-diversified list to items carrying that category tag â€” it
never triggers a separate ranking pass or changes any score. This
means switching category filters in the UI is instant (served from the
same cached snapshot) rather than a new computation.

