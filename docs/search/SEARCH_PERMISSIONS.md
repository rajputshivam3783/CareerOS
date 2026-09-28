# SEARCH PERMISSIONS â€” V21.1

Permission logic lives in one place, `backend/app/search/
permissions.py`, and every query the `DatabaseSearchProvider` runs
goes through `apply_visibility()` first. That's a deliberate choice:
one function to audit for a leak, rather than one permission check per
entity type scattered across the provider.

## Actor resolution

`SearchActor` (`app/search/permissions.py`) is built once per request
from the new `optional_user` dependency (`app/core/security.py`) â€”
like the existing `current_user`, but returns `None` instead of
raising 401 when there's no (or an invalid) token, since `/search`
must work for anonymous visitors. A bad/expired token is treated
exactly like no token â€” the endpoint doesn't require auth, so it
shouldn't error on a stale one.

| Actor | `role` | Sees |
|---|---|---|
| Anonymous | `"anonymous"` | `visibility == "public"` documents only |
| Candidate | `"candidate"` | same as anonymous â€” candidates have no owned search-indexed content in V21.1 |
| Recruiter | `"recruiter"` | public documents, **plus** any document where `owner_user_id` matches their own user id (their own draft/review job postings, their own unpublished company profile) |
| Admin / Super Admin | `"admin"` / `"super_admin"` | everything, unfiltered |

`SearchActor.is_admin` checks `app.core.rbac.ADMIN_ROLES` â€” the same
role set every other admin-gated endpoint in the codebase uses, not a
new/separate admin concept.

## What "public" means per entity type

Set at index time by `app/search/document.py`'s `build_*_document`
functions, mirroring the visibility rule each entity already enforces
elsewhere in the app (V21.1 doesn't invent new rules â€” it reads the
existing ones):

| Entity type | `visibility == "public"` when | Matches existing convention in |
|---|---|---|
| JOB / GOVERNMENT_RECRUITMENT / INTERNSHIP / APPRENTICESHIP | `Job.status == "published"` | `app/api/platform.py` public job listing |
| ORGANIZATION (government) | `GovernmentOrganization.status == "active"` | government hub listing |
| COMPANY | the organization has claimed a public `slug` | `app/api/company.py`'s `list_companies` |
| SKILL | always public | there is no private skill in the catalog |
| LEARNING_RESOURCE | `status == "published"` **and** `is_verified == True` | `app.skill_intelligence` resource visibility gate |

## Never-leak guarantees

- `apply_visibility()` is additive-only relative to the unfiltered
  query â€” for a non-admin actor it can only *remove* rows, never add
  any that a plain unfiltered query wouldn't already contain.
- Recruiter ATS candidate data (resumes, applications, candidate
  profiles) has **no** `build_*_document` function and is never
  indexed â€” it's not merely filtered out at query time, it's simply
  never in `search_index_documents` to begin with. This is the
  strongest guarantee available: a permission-filter bug can't leak
  data that was never indexed.
- Autocomplete and facets apply the exact same `apply_visibility()`
  call as search â€” there's no separate, easier-to-forget permission
  path for those two endpoints.

## Tested

`backend/tests/test_v21_1_unified_search.py` includes explicit checks
that an unpublished job is invisible to anonymous search, visible to
its owning recruiter, invisible to a *different* recruiter, and
visible to an admin â€” see
`test_unpublished_job_not_visible_to_anonymous_search`,
`test_unpublished_job_visible_to_its_owner_but_not_another_user`,
`test_admin_sees_unpublished_jobs_in_search`.

## Deferred to a later phase

`allowed_entity_types()` currently returns every entity type to every
actor (subject to the row-level filter above) â€” there is no entity
type in V21.1 reserved for a specific role. If a future entity type
needs to be, say, recruiter/admin-only regardless of individual row
visibility (a hypothetical future `CANDIDATE_PROFILE` search entity,
for instance), that's a one-line addition to this function, not a
redesign.

