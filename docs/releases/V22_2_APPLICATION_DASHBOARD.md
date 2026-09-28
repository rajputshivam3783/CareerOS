# V22.2 — Smart Application Dashboard & Kanban

Transforms V22.1's basic `/applications` list page into a full
dashboard: real statistics, a drag-and-drop Kanban board, a filterable/
searchable list view, upcoming deadlines, and recent activity — all on
top of the exact same V22.1 `Application`/`ApplicationStatusHistory`
models and service layer. No new tables, no duplicate application
system, no rewritten V22.1 code path.

## Dashboard architecture

```
app/applications/service.py
    get_stats()              — V22.1, unchanged: total/by_status/recent_activity
    get_dashboard()           — NEW: get_stats() + this-week/month counts
                                 + upcoming deadlines + conversion rates
    get_upcoming_deadlines()  — NEW: shared by get_dashboard() and its
                                 own dedicated endpoint

app/api/applications.py
    GET /applications/stats               — V22.1, response shape unchanged
    GET /applications/dashboard           — NEW
    GET /applications/upcoming-deadlines  — NEW
```

`get_dashboard()` is additive on top of `get_stats()` — it calls it and
extends the result, so `/applications/stats`'s existing response shape
(and every existing caller of it, including the candidate dashboard
widget) is untouched. `GET /applications/dashboard` is a strict
superset: `{total, by_status, recent_activity, applications_this_week,
applications_this_month, upcoming_deadlines, conversion_rates}`.

### Conversion rates, computed correctly

A naive "count applications currently in each status" undercounts —
an application rejected *after* an interview has a current status of
`REJECTED`, not `INTERVIEW`, but it genuinely did reach the interview
stage. `get_dashboard()` instead counts, per candidate, how many
distinct applications ever had a given status in
`ApplicationStatusHistory` (`GROUP BY new_status`), then:

```
applied_to_interview  = ever_reached(INTERVIEW) / ever_reached(APPLIED)
interview_to_offer    = ever_reached(OFFER)     / ever_reached(INTERVIEW)
offer_to_acceptance   = ever_reached(ACCEPTED)  / ever_reached(OFFER)
```

Any rate is `null` — never `0` or a divide-by-zero — when the
denominator is zero ("avoid misleading statistics when the sample size
is zero"). The frontend renders `null` as "Not enough data yet."

## Kanban architecture

Frontend-only feature — no new backend concept beyond the existing
status-change endpoint. `KANBAN_STATUSES` (9 columns: Planning to
Apply, Applied, Assessment, Interview, Offer, Accepted, Rejected,
Withdrawn, Ghosted) deliberately excludes `SAVED`, since a saved-but-
not-yet-tracked job isn't really "in the pipeline" yet — it's still
visible via the List view and the existing Saved Jobs page.

Drag-and-drop reuses the exact pattern already established by the
recruiter's own Kanban pipeline
(`frontend/src/app/recruiter/jobs/[id]/pipeline/page.tsx` — native
HTML5 drag events, no new dependency): moving a card **optimistically**
updates the UI immediately, then calls the real status-change API;
on failure, the UI is rolled back to the last known-good state and an
error is shown. The backend is always the source of truth for the
actual status — the frontend never persists a status change locally
without a corresponding API call succeeding.

## Status transition rules

`app/applications/status.py`. V22.1 deliberately validated only that a
new status is *a* known value, never that a specific transition makes
sense (a real job search isn't linear — being rejected immediately
after applying, with no assessment/interview step, is common; so is
reapplying). V22.2 keeps that philosophy for every forward or lateral
move: nothing blocks jumping ahead, skipping a stage, or moving
sideways between non-terminal stages.

The one new rule: moving an application **out of** `ACCEPTED`,
`REJECTED`, or `WITHDRAWN` requires the caller to pass `reopen: true`
explicitly, or the API returns `409`. `GHOSTED` is deliberately *not*
in this set — "the recruiter went quiet" is often provisional, not a
real outcome, so it stays freely reversible. This is a separate
constant (`REOPEN_REQUIRED_STATUSES`) from the pre-existing
`TERMINAL_STATUSES` (which includes `GHOSTED` and is used elsewhere for
duplicate-application-prevention) — reusing `TERMINAL_STATUSES` here
would have silently changed `GHOSTED`'s duplicate-prevention behavior
too; found and avoided during this release's own testing.

```
Typical (not enforced) forward path:
SAVED → PLANNING_TO_APPLY → APPLIED → ASSESSMENT/INTERVIEW → OFFER → ACCEPTED
                                                            ↘ REJECTED
Any non-terminal status → REJECTED/WITHDRAWN/GHOSTED : always allowed
ACCEPTED/REJECTED/WITHDRAWN → anything else : requires reopen=true (409 otherwise)
GHOSTED → anything : always allowed, no reopen needed
```

Both `POST /applications/{id}/status` and `PATCH /applications/{id}`
(when it includes a `status` field) accept `reopen`. The frontend
(`StatusChangeControl.tsx`, `KanbanBoard.tsx`) shows a confirmation
dialog before setting `reopen: true`, so reopening a closed application
is always an explicit, visible action — never a silent side effect of
a stray drag.

## API changes

| Endpoint | Status | Notes |
|---|---|---|
| `GET /applications/dashboard` | New | Superset of `/stats` |
| `GET /applications/upcoming-deadlines` | New | `days`, `limit` query params |
| `GET /applications` | Extended | New `search` param (see Filtering) |
| `POST /applications/{id}/status` | Extended | New `reopen` field |
| `PATCH /applications/{id}` | Extended | New `reopen` field |

All five require authentication and are scoped to `current_user` —
never a client-supplied `user_id` — identical to every V22.1 endpoint.

## Filtering & search

The spec asks search to cover "company name, job title, location."
V22.1's list endpoint only ever filtered on `company` (exact
substring). V22.2 adds a separate `search` query param that matches
company **OR** job title **OR** location (`OR`, not `AND` — a
candidate typing into one search box doesn't know or care which field
the match lands in). The original `company` filter is unchanged and
still available for a company-specific filter chip.

Filters (status, company, source, date range) and the current view
(`kanban`/`list`) are all reflected in the URL
(`/applications?view=list&status=INTERVIEW&search=...`), so the page
can be refreshed or shared without losing state. Search input is
debounced 400ms client-side before it becomes a URL param / triggers a
request.

## Performance decisions

- **Kanban fetch is capped, not unlimited**: `limit=200` (bounded, not
  the whole table) — realistic for how many applications one candidate
  actively kanban-manages at once. The List view uses normal
  pagination (`limit=20`) for everything beyond that.
- **No N+1 queries added**: dashboard's conversion-rate calculation is
  one `GROUP BY` query, not one query per status; upcoming deadlines is
  one indexed query (`ix_applications_user_status`,
  `ix_applications_deadline` from V22.1's migration already cover
  this).
- **Optimistic Kanban moves** avoid a network round-trip before the UI
  responds; only a failure triggers a full reload.
- Stable React keys (`application.id`) throughout — no index-based
  keys — so a reorder/status-move never causes an unnecessary
  full-list re-render.

## Accessibility

- Every status change achievable by drag-and-drop is also achievable
  via `StatusChangeControl`'s keyboard-operable `<select>` — "Change
  Status" is present on every card in both views, not just Kanban.
- Kanban columns and the board itself carry `role="list"`/
  `role="listitem"`; the view toggle uses `role="tablist"`/
  `role="tab"`/`aria-selected`.
- Filter inputs all have visible or screen-reader-only (`.sr-only`)
  labels; search has `aria-label`.
- Reopening a terminal-status application always requires an explicit,
  visible confirmation — dragging alone can never silently reopen
  something without the user seeing and confirming the prompt.

## Testing

`backend/tests/test_v22_2_application_dashboard.py` (24 tests) —
status-transition rules (forward moves, skipped stages, lateral moves,
terminal-reopen required, reopen via both endpoints, no-op-to-self,
GHOSTED's non-terminal reopen behavior, invalid status rejected even
with reopen), dashboard correctness (real counts, per-user isolation,
conversion-rate null-at-zero-sample, conversion computed from history
not current status), upcoming deadlines (sort order, overdue/due-soon/
upcoming classification, terminal exclusion, per-user isolation),
search (company/title/location match, per-user isolation), and
regression (V22.1's `/stats` shape unchanged, V21.1 search, V21.3
recommendations).

See `TEST_REPORT_V22_2.md` for full execution results — this release,
unlike V22.1's own report, had a real network-enabled sandbox and ran
every test for real against real Postgres for migrations, not just by
inspection.

## A real bug found and fixed this release (not new functionality)

While establishing a clean baseline before starting V22.2 work, one
V22.1 test was found actually failing:
`test_tracking_persists_job_snapshot_even_if_job_later_changes`. Root
cause: SQLite silently ignores every `ON DELETE CASCADE`/`SET NULL` in
the schema unless `PRAGMA foreign_keys=ON` is set per-connection — off
by default. This meant `Application.job_id`'s `ON DELETE SET NULL`
(and every other such relationship in the schema) worked correctly in
real Postgres but never actually fired in dev/test. Fixed in
`app/db/session.py`; verified against the full V16–V22.1 regression
suite with zero side effects (42/42 files passing before this release
even started its own new work).
