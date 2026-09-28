# SEARCH RELEVANCE â€” V21.1

Ranking lives in `backend/app/search/ranking.py`. Every factor is a
plain computation over the query string and one `SearchIndexDocument`
row â€” no learned weights, no call to an AI model, nothing that
couldn't be recomputed by hand from the row and the query. This is a
deliberate constraint from the brief ("Do NOT use arbitrary
AI-generated scores. Every ranking factor must be explainable"), and
it's also why every search result in the API response carries a
`score_factors` object â€” the same numbers this document describes,
per result, so a person (or a test) can see exactly why one result
ranked above another.

## Factors and weights

| Factor | Weight | What it measures |
|---|---|---|
| `exact_title_match` | 0.30 | 1.0 if the normalized query string equals the normalized title exactly, else 0.0. |
| `phrase_match` | 0.15 | 1.0 if the normalized query appears as a contiguous substring anywhere in the document's indexed text, else 0.0. |
| `skill_match` | 0.20 | Fraction of query tokens that appear in the document's normalized skill list. |
| `organization_match` | 0.10 | 1.0 if the query and the organization name overlap as substrings of each other, else 0.0. |
| `location_match` | 0.10 | Same, for location. |
| `token_coverage` | 0.10 | Fraction of query tokens found anywhere in the document's indexed text â€” the general keyword-overlap signal. |
| `recency` | 0.03 | Exponential decay from the document's posted date, halving every 30 days. An empty-query ("browse") search relies on this (and `entity_quality`) since every text-match factor is 0 with no query. |
| `entity_quality` | 0.02 | A verified/rated signal specific to the entity (e.g. `Job.verified`, a `LearningResource`'s rating) â€” clamped to [0, 1]. |

Weights are a readability convention (they sum to 1.0) â€” scores are
only ever used to *sort*, never shown to a user as a percentage, so
the sum isn't load-bearing and can be retuned without a migration.

## Normalization, so both sides of a match compare fairly

`app/search/normalization.py` lowercases, strips punctuation, and
collapses whitespace on both the query and every indexed field before
either is compared â€” so `"Sr. Software Engineer"` and `"senior
software engineer"` are the same string by the time ranking runs.
Three small, curated alias tables (not a fuzzy matcher) additionally
fold common variants together:

- **Title variants** â€” `Sr.`â†’`senior`, `SWE`â†’`software engineer`, etc.
- **Organization aliases** â€” `SSC`â†’`staff selection commission`, etc.
- **Location aliases** â€” `BLR`/`Bengaluru`â†’`bangalore`, `WFH`â†’`remote`, etc.

Skill names are normalized against the existing V20.5 canonical-skill
catalog (`app.skill_intelligence.normalization.resolve_many`) rather
than a second, search-specific alias table.

## Typo tolerance, scoped deliberately

A short, curated table (`_TYPO_TOLERANT_EQUIVALENTS` in
`app/search/provider.py`) maps a handful of commonly-mistyped
tech/job terms (`pyhton`â†’`python`, `managr`â†’`manager`, etc.) to their
correct form, and the SQL match tries both forms. This is **not** a
general edit-distance/fuzzy matcher â€” the brief asks for typo
tolerance "where practical," not a spell-checker, and a
whole-vocabulary fuzzy matcher can silently surface unrelated results
for a short query, which would undermine explainability. Extending the
table is a one-line, reviewable change.

## What's deliberately not here

- No personalized ranking (candidate history, click-through, etc.) â€”
  explicitly deferred to V21.2+ per the brief's stop condition.
- No semantic/embedding similarity in the general search path â€” that
  remains `GET /api/v1/search/semantic`
  (`app/services/semantic_search.py`), unchanged, for callers that
  specifically want TF-IDF cosine-similarity job ranking.

