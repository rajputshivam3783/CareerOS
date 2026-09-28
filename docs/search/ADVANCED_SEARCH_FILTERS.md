# Advanced Search Filters â€” V21.2

## Design

One `SearchFilters` type (`frontend/src/lib/search.ts`, unchanged from
V21.1) maps to one `SearchFilters` dataclass on the backend
(`app/search/provider.py`, also unchanged in shape). `DiscoveryFilters.tsx`
shows a different *subset* of these same fields depending on the
active category â€” there is no separate filter data model per category,
only a different UI presentation of the same underlying fields. This
avoids the "duplicate search engines per category" the spec explicitly
prohibits.

## Filter sets actually implemented (backed by real, existing data)

**COMMON** (every category): Location, Skills, Posted Date

**PRIVATE JOB**: Company, Experience, Salary Range, Employment Type,
Work Mode, Department/Industry (maps to `Job.category`), Education

**GOVERNMENT**: Organization, Qualification (maps to `education`),
Category (maps to `Job.category`), Application Deadline

**INTERNSHIP**: Stipend Range (min/max â€” see "Stipend filtering" below),
Remote/On-site

**APPRENTICESHIP**: Organization, Trade (maps to `Job.category`),
Qualification

## Filters listed in the spec but NOT implemented â€” and why

The spec's GOVERNMENT FILTERS list also includes **Central/State/PSU**,
**State**, **Application Status**, and **Exam Stage**. Central/State/PSU
already has a backing field (`Job.govt_level`) but a dedicated UI
control for it wasn't added this release â€” see "known limitations"
below. **State** (as a distinct Indian-state filter separate from
free-text location), **Application Status** (a tracked lifecycle
beyond published/archived/rejected), and **Exam Stage** (a tracked
recruitment-stage state machine) have **no backing column anywhere in
the data model**. Per the spec's own instruction ("Do not fabricate...
Prefer existing tables... Do not create duplicate Jobs... models"),
these are not implemented rather than faked with a UI control that
filters on nothing. Adding real tracked fields for these is a
legitimate future feature, not a V21.2 stabilization-scope change.

## Stipend filtering (a real V21.2 fix, not a limitation)

Internships/apprenticeships store compensation in `Job.stipend`, a
separate free-text field from `Job.salary`. V21.1's document indexer
only parsed `salary` into the filterable `salary_min`/`salary_max`
columns, meaning stipends were never numerically filterable or
sortable at all. Fixed in `document.py`:
`_parse_salary_bounds(job.salary or job.stipend)` â€” since a `Job` row
practically only ever populates one of the two depending on
`job_type`, reusing the same numeric columns for both means the
existing salary-range filter/sort infrastructure works for stipends
too, with no new column and no second filter code path. Verified by
`test_internship_stipend_is_filterable_via_salary_range`.

## Filter UX

- **Applied filter chips** â€” every active filter renders as a
  removable chip (`AppliedChips` in `DiscoveryFilters.tsx`), each with
  its own âœ• to clear just that one filter, plus a "Clear all" chip.
- **Multi-select** â€” Skills accepts a comma-separated list, sent as
  repeated `skills=` query params (a job must match all of them â€” see
  `provider.py`'s `_base_query`, unchanged AND logic from V21.1).
- **Mobile filter drawer / desktop sidebar** â€” a simple show/hide
  toggle (`.discovery-mobile-toggle`, CSS media-query gated at the
  existing 760px breakpoint used throughout the app), not an animated
  slide-in panel â€” see `SEARCH_UX.md`'s "Avoid unnecessary animation"
  rationale. On desktop the toggle is hidden entirely and filters are
  always visible (no "sidebar vs. inline" distinction needed at that
  width in the current layout).
- **URL-addressable** â€” every filter round-trips through the URL (see
  `JOB_DISCOVERY_ARCHITECTURE.md`).

## Known limitations

- Central/State/PSU (`govt_level`) has no dedicated filter control in
  `DiscoveryFilters.tsx` yet, though the field is indexed and could be
  exposed as a simple select in a follow-up change â€” omitted this
  release for time, not for a data reason.
- State, Application Status, and Exam Stage filters: no backing data,
  not implemented (see above).
- Filter validation: every filter value passed to the backend now has
  a `max_length` bound (see `SEARCH_SECURITY_V21_2.md`); there's no
  semantic validation (e.g., rejecting a nonsensical "Location" value)
  beyond that â€” filters that match nothing simply return zero results,
  handled by the zero-result experience.

