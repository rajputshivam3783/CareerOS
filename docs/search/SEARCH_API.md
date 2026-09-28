# SEARCH API â€” V21.1

All endpoints are under `/api/v1` (the app's existing global prefix â€”
see `app/main.py`). Swagger/OpenAPI is generated automatically by
FastAPI for every route below, same as the rest of the app â€”
`/api/v1/openapi.json` / the interactive docs UI, whichever is enabled
in the deployment (no change to that config in this pass).

## `GET /search`

Public â€” works for anonymous visitors, personalizes for a logged-in
user (see SEARCH_PERMISSIONS.md).

| Param | Type | Notes |
|---|---|---|
| `q` | string | Free-text query. Empty string is valid â€” "browse" mode, ranked by recency/quality only. |
| `entity_type` | repeatable string | e.g. `?entity_type=JOB&entity_type=SKILL`. Omit for all types. |
| `location`, `organization`, `category`, `job_type`, `employment_type`, `work_mode`, `experience`, `education` | string | Substring/exact filters, see FILTER INFRASTRUCTURE below. |
| `skills` | repeatable string | Every listed skill must appear on the result (AND, not OR). |
| `salary_min`, `salary_max` | number | Matches if the document's own range overlaps the requested range. |
| `status` | string | Only meaningful for an owner/admin â€” anonymous/candidate results are always `status == "published"` regardless of this param. |
| `posted_after`, `deadline_before` | date (`YYYY-MM-DD`) | |
| `sort` | `relevance` \| `newest` \| `oldest` \| `deadline` \| `salary` | Default `relevance`. |
| `page`, `page_size` | int | `page_size` capped at 100. |
| `cursor` | string | Optional. From a previous response's `next_cursor`. Takes precedence over `page` when both are given â€” see "Pagination" below. |

Response (`SearchResponse`):

```json
{
  "query": "backend engineer",
  "total_count": 42,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "entity_type": "JOB",
      "entity_id": 123,
      "title": "Backend Engineer",
      "organization": "Acme Corp",
      "location": "Bangalore",
      "job_type": "Private",
      "posted_date": "2026-08-01",
      "deadline": null,
      "status": "published",
      "score": 0.71,
      "score_factors": {"exact_title_match": 0.0, "phrase_match": 1.0, "...": "..."},
      "metadata": {"slug": "acme-corp-backend-engineer-a1b2c3d4", "apply_url": "..."}
    }
  ],
  "facets": {},
  "suggestions": [],
  "next_cursor": "eyJzb3J0IjogInJlbGV2YW5jZSIsICJldCI6ICJKT0IiLCAiaWQiOiAxMjN9"
}
```

`facets` is always `{}` on `/search` itself â€” call `/search/facets`
separately (see below); keeping them separate means a plain search
doesn't pay for facet aggregation queries it didn't ask for.

## Pagination

Two supported modes, both always available on `GET /search`:

- **Page-based (default/primary).** `page` + `page_size`, with
  `total_count` in every response. Nothing new here.
- **Cursor-based.** Pass the previous response's `next_cursor` back as
  `cursor` to get the next page; `next_cursor` is `null` once there
  are no more results. A cursor is tied to the `sort` it was minted
  under â€” using it with a different `sort` is silently treated as "no
  cursor" (start over), never an error. Prefer this over `page` when a
  person might be paging through results while new content is being
  published concurrently â€” a cursor doesn't reshow or skip items the
  way an offset can when rows shift underneath it. See
  SEARCH_ARCHITECTURE.md "Pagination" for what a cursor does and
  doesn't guarantee (it isn't a true database-level keyset seek for
  the "relevance" sort).

## Caching

Anonymous (unauthenticated) requests to `/search`, `/search/
autocomplete`, and `/search/facets` are cached in-process for up to
30 seconds, and invalidated immediately on any write that goes
through `app.search.hooks` or a manual/scheduled reindex â€” so an
anonymous visitor never sees a *stale* cache for longer than the
narrow window before that invalidation runs, and a cache hit never
skips permission filtering (there's nothing to filter â€” an anonymous
response is public-only by construction). A logged-in request (any
role) is **never** cached, to guarantee a personalized response (a
recruiter's own unpublished postings, for instance) can never be
served to a different person. See SEARCH_PERMISSIONS.md.

## `GET /search/autocomplete`

Public. `q` (required, min length 1), `entity_type` (repeatable,
optional), `limit` (default 10, max 25). Returns matching titles,
shortest-first, deduplicated case-insensitively, respecting the same
visibility rules as `/search`.

## `GET /search/facets`

Public. `facet` (repeatable; one or more of `job_type`, `location`,
`organization`, `category`, `experience`, `entity_type`; defaults to
`job_type`, `location`, `category`), `entity_type` (repeatable,
optional). Returns up to 20 buckets per facet, each with a count,
ordered by count descending, respecting the same visibility rules as
`/search`.

## `POST /admin/search/reindex`

Admin-only (`app.api.admin.guard` â€” shared `X-Admin-Key` header or a
JWT for an admin/super_admin user, same as every other `/admin/*`
route). Runs a full reindex synchronously and returns per-entity-type
counts. See SEARCH_INDEXING.md.

## `GET /admin/search/index-health`

Admin-only, same auth. Returns the Index Health report from
SEARCH_INDEXING.md.

## No-result handling

When `total_count == 0`, `suggestions` is populated with up to 5
`{"kind": ..., "text": ...}` entries:

- `kind: "spelling"` â€” only emitted if a query token matches an entry
  in the curated typo-equivalents table (see SEARCH_RELEVANCE.md);
  never a guessed correction.
- `kind: "alternative_category"` â€” real facet values (job types /
  categories) that exist within the requested filters, so "here's what
  does exist" is never fabricated.

An empty `suggestions` array is a valid, honest response â€” it means
neither of the above had anything real to offer, not that the feature
is broken.

