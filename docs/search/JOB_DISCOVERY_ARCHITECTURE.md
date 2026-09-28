# Job Discovery Architecture â€” V21.2

## What this is

The primary job discovery experience (`/discover`), built entirely on
top of the V21.1 Unified Search Infrastructure. This is **not** a
second search engine â€” every result on this page comes from the same
`GET /search` endpoint, the same `SearchIndexDocument` table, and the
same ranking/permission code every other search surface
(`/search`, `/government/search`, `/companies`) already uses.

## Why a new page instead of extending `/search`

V21.1's `/search` page is intentionally generic â€” it spans every
entity type (jobs, companies, government organizations, skills,
learning resources) with one filter panel and one card shape. V21.2's
spec calls for a **job-family-specific** experience: category tabs,
per-category filters (private/government/internship/apprenticeship
each need different fields), and result cards with fields a company
or a skill document doesn't have (vacancies, stipend, official-source
badges). Building that into the generic page would mean branching
half its logic on "is this a job-family entity" â€” instead, `/discover`
is a new page that composes the same underlying `runSearch()` call
with job-family-specific presentation on top. `/search` itself was not
modified (see `CHANGELOG_V21_2.md` for the one shared-component change
that *was* necessary â€” `SearchSortBar`'s type widening for the new
salary sort directions â€” and why it's backward compatible).

## Component map

```
frontend/src/app/discover/
    page.tsx            Server wrapper â€” Suspense boundary + metadata
    DiscoverClient.tsx  All page logic: URL state, category tabs,
                        search execution, result rendering

frontend/src/components/discovery/           (new, V21.2)
    DiscoverySearchBox.tsx   Grouped-autocomplete search input
    DiscoveryFilters.tsx     Category-aware filters + applied chips
    JobResultCard.tsx        Entity-specific result cards
    RecentSearches.tsx       View/reuse/delete/clear panel

frontend/src/components/search/               (V21.1, reused as-is)
    SearchStates.tsx    Loading/Error/Empty states
    SearchSortBar.tsx   Sort dropdown + pagination (extended, see below)
    SearchBox.tsx       useDebouncedValue hook (reused directly)

frontend/src/lib/search.ts   Typed API client (extended, see below)
```

## Category â†’ entity type mapping

Jobs, government recruitments, internships, and apprenticeships are
all rows in the *same* `jobs` table (`Job.job_type` distinguishes
them) and have been indexed as **distinct entity types** since V21.1
(`JOB` / `GOVERNMENT_RECRUITMENT` / `INTERNSHIP` / `APPRENTICESHIP` â€”
see `backend/app/search/document.py`'s `_JOB_TYPE_TO_ENTITY_TYPE`
map). The discovery page's category tabs are a thin UI layer over
this existing mapping â€” "Private Jobs" passes `entity_type=JOB`, "All
Opportunities" passes all four job-family types (never
`COMPANY`/`ORGANIZATION`/`SKILL`/`LEARNING_RESOURCE`, which stay
exclusive to `/search`).

## Search state (URL-addressable)

Every piece of state lives in the URL query string, read via
`useSearchParams` and written via `router.replace` (no full navigation
â€” filters update the URL without a page reload):

```
/discover?q=python&location=noida&type=JOB&sort=newest&page=2
```

This means: page refresh survives, browser back/forward works,
and the URL is shareable/bookmarkable exactly as the spec requires.
`page.tsx` wraps the client component in `<Suspense>` (the same
pattern `jobs/[id]/page.tsx` + `JobDetailClient.tsx` already
established for a server/client split) since `useSearchParams`
requires it.

## What was extended vs. left alone

| File | V21.1 state | V21.2 change |
|---|---|---|
| `app/search/document.py` | metadata had 4 fields | +21 fields for result cards (additive to the dict) |
| `app/search/provider.py` | 1 salary sort direction | +1 direction (`salary_asc`), stipend reuses salary_min/max, expired-job exclusion |
| `app/search/schemas.py` | flat autocomplete | + `GroupedAutocompleteResponse`, `RecentSearchOut` |
| `app/api/search.py` | 6 endpoints | +4 endpoints (grouped autocomplete, 3 recent-searches) |
| `lib/search.ts` | typed client | + grouped autocomplete, recent-searches functions |
| `components/search/SearchSortBar.tsx` | 5 sort options | +2 options, `options` prop so `/search` keeps its original 5 |
| `components/search/SearchFiltersPanel.tsx` | â€” | **untouched** â€” `/search` still uses it |
| `components/search/SearchResults.tsx` | â€” | **untouched** â€” `/search` still uses it |

See `SEARCH_API_V21_2.md` for the full endpoint reference and
`CHANGELOG_V21_2.md` for the complete file-by-file diff.

