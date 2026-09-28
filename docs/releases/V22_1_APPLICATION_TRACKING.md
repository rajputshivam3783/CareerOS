# V22.1 — Application Tracking Infrastructure

A production-grade Application Tracking System for candidates: the
complete lifecycle of every job application, whether it's a CareerOS
listing or one found elsewhere, in one place.

## What this is NOT

CareerOS already has an "ATS" — `ATS_ARCHITECTURE.md`, the **recruiter**-
side applicant tracking system (a recruiter's pipeline of candidates
for *their* job postings, backed by the `Applicant` model). This
document is the unrelated **candidate**-side system: a private list of
roles *one candidate* is pursuing, backed by the pre-existing V7
`Application` model. The two share an acronym, nothing else — neither
is touched or duplicated by the other. See "Relationship to the
recruiter Applicant pipeline" below for the exact boundary.

## Architecture

```
app/models/domain.py
    Application              (V7, extended in place)
    ApplicationStatusHistory (new)

app/applications/
    status.py    — canonical status vocabulary, legacy-value
                    normalization, terminal-status set
    service.py   — the one place that reads/writes Application or
                    ApplicationStatusHistory; every function takes and
                    enforces a user_id

app/api/applications.py  — REST API; calls only into app.applications.service
```

`app/api/platform.py`'s four inline V7 endpoints
(`POST/GET/PUT/DELETE /applications`) are removed and replaced by this
module at the *same* base path — nothing that already pointed at
`/applications` needs a new base URL. `platform.py`'s `/dashboard`
endpoint is extended (not replaced) to include the new stats.

## Database schema

Extends the existing `applications` table (migration
`v22_1_application_tracking.sql`) — **no second application table**.

New columns (all nullable or safely defaulted — no existing row or
query breaks): `job_title`, `job_url`, `location`, `employment_type`,
`source`, `salary`, `deadline`, `recruiter_name`, `recruiter_email`,
`external_reference`, `status_updated_at`, `updated_at`.

New table: `application_status_history` (id, application_id FK
CASCADE, old_status, new_status, changed_at, metadata_json).

New indexes: `(user_id, status)`, `(user_id, created_at)`,
`(user_id, deadline)`, `(user_id, applied_on)` — `job_id` was already
indexed since V7.

### Field-naming notes (why some fields have two names)

- **`job_title` vs `role`.** The spec calls the field `job_title`;
  the pre-existing V7 column is `role`, and
  `app.recommendations.candidate_features` already reads `.role`
  directly. Rather than rename (breaking that reader) or duplicate
  silently, `app.applications.service` writes both on every create/
  update — `job_title` is canonical going forward, `role` is kept in
  sync for backward compatibility.
- **`applied_at` vs `applied_on`.** Same fact, one column
  (`applied_on`, a `Date`, unchanged from V7). The API layer renders
  it as `applied_at` in every JSON response — no second column for
  the same information.
- **`deadline` vs `next_deadline`.** These are genuinely different
  facts, both kept: `deadline` (new) is the application's own
  deadline; `next_deadline` (V7) is the next upcoming *action* (an
  interview date, a follow-up) — which can be an entirely different
  date.

## Status lifecycle

```
SAVED -> PLANNING_TO_APPLY -> APPLIED -> ASSESSMENT -> INTERVIEW
-> OFFER -> ACCEPTED / REJECTED / WITHDRAWN
                (GHOSTED reachable from APPLIED onward)
```

This is the *typical* journey, not an enforced state machine — a real
job search often skips steps (straight from APPLIED to REJECTED) or
reverses (a corrected mistake), so `app.applications.service` only
validates that a status is one of the 10 known values, never that a
specific transition is "allowed." Every change is still fully
recorded.

**Legacy compatibility.** V7 used five informal, lowercase values
(`planned`/`applied`/`interview`/`offer`/`rejected`). The migration
backfills every existing row into the new vocabulary
(`planned`→`PLANNING_TO_APPLY`, etc.), and
`app.applications.status.normalize()` accepts either form at runtime
as a defensive fallback — nothing that already sent a lowercase status
value breaks.

**Immutable history.** Every status change — including the very first
one, at creation — writes one `ApplicationStatusHistory` row. Existing
rows are never edited or deleted by the service layer (only cascade-
deleted if the parent `Application` itself is deleted). Pre-existing
V7 applications get one synthetic "creation" history row backfilled by
the migration so their timeline is never empty.

## Duplicate prevention

"Where appropriate," per the spec — not an absolute block. A second
*active* (non-terminal) application for the same CareerOS `job_id`, or
the same `(company, job_title)` pair for an external one, is rejected
with `409 Conflict`. An application in a terminal status (`ACCEPTED`,
`REJECTED`, `WITHDRAWN`, `GHOSTED`) is never counted as a duplicate
blocker — a candidate who withdrew or was rejected can genuinely track
a fresh attempt.

## Apply from a CareerOS job

`POST /jobs/{job_id}/applications?mark_applied=<bool>` — "Track
Application" (`mark_applied=false`, default status `PLANNING_TO_APPLY`)
or "Mark as Applied" (`mark_applied=true`, status `APPLIED`, sets
`applied_at` to today). Copies a **snapshot** of the job's
company/title/location/employment_type/salary/deadline/URL at the
moment of tracking — never a live join — so a later edit or deletion
of the `Job` row leaves the application's own history meaningful (see
`test_tracking_persists_job_snapshot_even_if_job_later_changes`, which
deletes the underlying job and confirms the application's own fields
survive). `job_id` itself is `ON DELETE SET NULL`, so a deleted job
becomes an untethered-but-intact record rather than a broken
application.

## Relationship to the recruiter Applicant pipeline

`POST /jobs/{job_id}/apply` (existing, V9, in `app/api/platform.py`)
creates an `Applicant` row — visible to the job's recruiter owner,
and only usable for a job that actually has one
(`job.owner_user_id is not None`; otherwise it 409s, unchanged
behavior). `POST /jobs/{job_id}/applications` (new, V22.1) creates a
private `Application` row for the candidate's own tracker — works for
*any* published job (government, private, recruiter-hosted or not),
never visible to anyone but the candidate. A candidate can use either,
both, or neither for the same job; they do not interact.

## Saved Job integration

`SavedJob` (bookmarking) and `Application` (tracking) remain two
distinct, un-merged concerns — bookmarking a job never creates an
application, and tracking an application never removes or alters a
bookmark (`test_saved_job_functionality_still_works_independently`).
The expected *candidate* journey (Saved → Planning to Apply → ... )
described in the V22.1 spec is a UX/product flow across two existing
systems, not a new shared data model — there was no single source of
truth to "conflict," so none was introduced.

## API

All endpoints require authentication (`current_user`) and operate only
on the caller's own applications — no endpoint accepts or trusts a
caller-supplied `user_id`.

| Method & path | Purpose |
|---|---|
| `POST /applications` | Create (external, or CareerOS via explicit `job_id`) |
| `POST /jobs/{job_id}/applications?mark_applied=` | Apply/track from a CareerOS job (snapshot copy) |
| `GET /applications` | List — filters: `status`, `company` (substring), `source`, `job_id`, `date_from`, `date_to`; sorting: `sort_by`/`sort_dir`; pagination: `limit`/`offset`. Legacy `?upcoming_days=N` shape preserved unchanged. |
| `GET /applications/{id}` | Fetch one (404 if not owned — never a distinguishing 403) |
| `PATCH /applications/{id}` | Partial update; a `status` field is routed through the same audited transition path, never a silent change |
| `DELETE /applications/{id}` | Delete (cascades to its history) |
| `POST /applications/{id}/status` | Explicit status change + optional note, always audited |
| `GET /applications/{id}/history` | Full immutable journey |
| `GET /applications/stats` | Aggregate counts by status + last 10 status-change activity |

Every response and request body is documented automatically via
FastAPI's OpenAPI generation (`/api/v1/docs`, `/api/v1/openapi.json`) —
no manual doc mechanism was added.

## Security

- Every query in `app.applications.service` filters by the
  authenticated `user_id` — ownership is enforced in the service
  layer itself, not only at the API layer, so a bug in one endpoint
  can't accidentally bypass it.
- A non-owner's read/update/delete/status-change/history request
  returns `404` (not `403`), so existence of another user's
  application is never leaked.
- `job_url` must start with `http://`/`https://` (rejects
  `javascript:`/`data:`/arbitrary schemes) — validated at the Pydantic
  layer before it ever reaches the service or database.
- Sorting is restricted to a fixed allow-list of columns
  (`_VALID_SORT_FIELDS`/`_SORTABLE_FIELDS`) — a `sort_by` value outside
  that list is rejected with `422`, never used to build a raw/dynamic
  `ORDER BY` clause (no SQL-injection surface via sorting).
- All filtering/sorting/pagination happens via SQLAlchemy's query
  builder (parameterized), never raw/string-interpolated SQL.
- `POST /jobs/{job_id}/applications` never creates or modifies an
  `Applicant` row, and vice versa — a bug in one cannot corrupt the
  other's data.

## Performance

- `list_applications` filters, sorts, and paginates entirely in the
  database (`LIMIT`/`OFFSET` + indexed `WHERE`/`ORDER BY`) — never
  loads a candidate's full history into Python to slice it.
- `get_stats` is one `GROUP BY status` query plus one bounded (`LIMIT
  10`) join for recent activity — never N+1, never a full-table scan
  per status.
- New indexes cover every filter/sort combination the spec calls out:
  `user + status`, `user + created_at`, plus `user + deadline` and
  `user + applied_on` for date-range/sort queries.

## Testing

See `TEST_REPORT_V22_1.md` for the full, honest breakdown of what was
executed vs. only written-and-traced in this environment.
`tests/test_v22_1_application_tracking.py` covers creation (both
paths), duplicate prevention (including the terminal-status
exception), status transitions and immutable history, filters,
sorting, pagination, ownership isolation (5 distinct IDOR checks),
unauthenticated access, invalid input (bad status, bad URL scheme, bad
sort field), deletion, dashboard statistics, Saved Job independence,
and regression checks against V21.1 search, V21.3 recommendations, the
career copilot context engine, and the recruiter Applicant pipeline.

## Deferred to V22.2

Per the spec: no Kanban board yet. `/applications` is a filterable,
sortable, paginated list with a detail drill-down
(`/applications/[id]`, including the full status history) — exactly
what V22.1 asks for, nothing more.
