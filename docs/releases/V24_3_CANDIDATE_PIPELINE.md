# CareerOS V24.3 — Candidate Pipeline & Hiring Workflow

## What this version is

V24.3 was scoped as a new recruiter hiring-pipeline feature. The
codebase already had one — a working V9/V16/V18.2 recruiter ATS
(`Applicant.pipeline_stage`, a drag-and-drop Kanban board, applicant
notes, interview scheduling, offer letters, CSV/Excel export, basic
analytics). Building a second, parallel system next to it would have
violated this project's own "no duplicate candidate/application
systems" rule, so V24.3 is an **extension** of that system, not a
replacement: same `Applicant` table, same `ApplicantNote`/`Interview`/
`OfferLetter` tables, same board route. What's genuinely new is listed
under "What V24.3 actually adds" below.

## Status separation (candidate vs recruiter)

Two independent statuses have always coexisted on different tables:

- **Candidate-facing status** — `Application.status` (a candidate's
  private tracker entry for a role, anywhere) and `Applicant.status`
  (submitted/shortlisted/interview/rejected/hired — the simple status
  a candidate sees when they applied through CareerOS itself).
- **Recruiter-facing hiring status** — `Applicant.pipeline_stage`, the
  richer Kanban stage shown only to the recruiter.

Nothing in V24.3 changed this separation or made either side overwrite
the other. `PATCH /recruiter/applicants/{id}/stage` only ever writes
`pipeline_stage`; the recruiter still sets `status` separately via
`PATCH /recruiter/applicants/{id}`.

## The V18.2 → V24.3 stage rename

V18.2's stage vocabulary (`applied`, `shortlisted`, `screening`,
`interview`, `technical_round`, `hr_round`, `offer`, `accepted`,
`rejected`, `withdrawn`) didn't match this version's requested
workflow (New → Reviewing → Shortlisted → Assessment → Interview →
Offer → Hired, with Rejected/Withdrawn as off-ramps) — both in names
and in stage order. Rather than adding a second, parallel stage field
to avoid touching the old one, `PIPELINE_STAGES`
(`app/core/constants.py`) was renamed to the canonical set, with a
migration (`backend/migrations/v24_3_candidate_pipeline.sql`) that
rewrites existing rows:

| V18.2 | V24.3 |
|---|---|
| `applied` | `new` |
| `screening` | `reviewing` |
| `shortlisted` | `shortlisted` |
| `technical_round`, `hr_round` | `assessment` |
| `interview` | `interview` |
| `offer` | `offer` |
| `accepted` | `hired` |
| `rejected` | `rejected` |
| `withdrawn` | `withdrawn` |

`technical_round` and `hr_round` collapse into one `assessment` stage
— the board doesn't need to distinguish them, and a recruiter can
still tell rounds apart via `Interview.round_name` on each scheduled
interview. All existing board/move-stage/analytics behavior is
unchanged; two pre-existing tests that hardcoded the old stage names
(`test_v18_2_job_management.py`, `test_v18_3_candidate_detail_export_analytics.py`)
were updated to the new names, with a comment explaining why.

## What V24.3 actually adds

- **`RecruiterPipelineHistory`** (new table) — one immutable row per
  stage change (`applicant_id`, `old_stage`, `new_stage`,
  `changed_by_user_id`, `changed_at`, `direction`, `reason`). Written
  automatically the moment a candidate applies (`old_stage=None`,
  `new_stage="new"`) and on every subsequent move. Existing applicants
  from before V24.3 get one backfilled "initial" row by the migration.
  Deliberately separate from `ApplicationStatusHistory`, which tracks
  the *candidate*-owned `Application.status` on a different table —
  same "don't conflate the two statuses" principle as above.
- **`Applicant.hired_at`** — set the first time `pipeline_stage`
  becomes `hired`; never reset by a later correction move away from
  `hired`, so "when were they hired" stays answerable even after a
  data-entry fix.
- **Stage-transition validation** (`app/recruiter_pipeline/service.py`,
  `validate_transition`) — see "Transition policy" below.
- **`GET /recruiter/jobs/{job_id}/pipeline/stats`** — per-stage counts,
  applications this week, average days in each stage, last 20 stage
  changes. Every number is a real aggregate; nothing is estimated.
- **`GET /recruiter/jobs/{job_id}/pipeline/conversion`** — new→
  shortlisted→interview→offer→hired funnel. A step with zero
  candidates in its "from" stage reports `conversion_rate: null`, not
  a misleading `0%`.
- **`GET /recruiter/jobs/{job_id}/pipeline/stale?days=N`** (default 7)
  — active candidates with no stage activity for `N` days: last
  activity, days inactive, and a fixed, non-judgmental suggested next
  action per stage. Never claims a candidate is "likely to reject."
- **`GET /recruiter/applicants/{id}/pipeline-history`** — the full,
  chronological, immutable history for one candidate.
- **`POST /recruiter/applicants/bulk-stage`** — move many candidates
  at once. Every id is ownership- and transition-checked before any
  write, so one bad id in a batch is reported per-id (`ok: false`)
  rather than losing the rest of the batch; see that endpoint's
  docstring for exactly what "transactional" does and doesn't mean
  here.
- **Candidate-side in-app notification on stage change** — reuses the
  existing V23 notification service (`app/notifications/service.py`),
  category `APPLICATION`, for a documented subset of stages
  (reviewing/shortlisted/assessment/interview/offer/hired). Rejection
  keeps using the existing, richer `reject_reason`-aware notification
  already sent by `update_applicant_status`, so a rejected candidate
  doesn't get two separate "you were rejected" messages.
- **Enriched board cards** — `GET .../pipeline` now returns headline,
  top skills, experience level, location, and days-in-current-stage
  per card, reusing V24.2's `_load_candidate_rows` rather than
  re-deriving that data. Match score is *not* recomputed on every
  board load (a named performance concern in the spec) — it stays on
  the one-candidate-at-a-time detail view instead.
- **Frontend**: richer cards (skills/headline/days-in-stage/stale
  flag), a non-drag "change stage" `<select>` on every card for
  keyboard/mobile users, bulk selection + a bulk-move bar, a stats
  strip, a search box, and a mobile single-column stage-tab view. All
  additive to the existing board (`globals.css`'s V24.3 section) —
  reuses `.board`/`.col`/`.kcard`/`.statgrid`/`.statcard`/`.steps`
  rather than a new visual language.

## Transition policy

Section 6 of the spec is explicit: "do not make the workflow
unnecessarily restrictive." The enforced policy
(`app/recruiter_pipeline/service.py::validate_transition`) is:

- Any stage may move to `rejected` or `withdrawn` at any time.
- Any two of the seven forward stages (`new` … `hired`) may be moved
  between in either direction — e.g. `interview → reviewing` is a
  valid backward correction, not just `interview → offer`.
- `rejected`/`withdrawn` may be reactivated back into any forward
  stage.
- The only transition rejected outright is moving a stage to itself.

Every move is still recorded with a `direction`
(`forward`/`backward`/`reactivation`/`terminal`/`initial`) for
reporting, but direction is never used to block a move.

## Notes, interviews, offers

Unchanged from V18.2/V18.3 — `ApplicantNote`, `Interview`,
`OfferLetter`, and their existing endpoints are reused as-is. The
board's "Add note" / "Schedule interview" card actions link to the
existing applicant detail page
(`/recruiter/jobs/[id]/applicants/[applicantId]`), which already has
full forms for both, rather than duplicating that UI in the board.

## API surface

New in V24.3 (all under `/api/v1/recruiter`, all recruiter-owned-job
scoped, all 404 for another recruiter's job/applicant):

```
GET  /jobs/{job_id}/pipeline/stats
GET  /jobs/{job_id}/pipeline/conversion
GET  /jobs/{job_id}/pipeline/stale?days=N
GET  /applicants/{id}/pipeline-history
POST /applicants/bulk-stage
```

Unchanged in shape, enriched in behavior:

```
GET   /jobs/{job_id}/pipeline        (cards now include profile fields + days_in_stage)
PATCH /applicants/{id}/stage         (now validates the transition, writes history, notifies the candidate)
```

## Security

- Every new endpoint requires `require_recruiter` and re-derives
  ownership from `_owned_job_or_404`/`_owned_applicant_or_404` (job →
  recruiter's organization), never from a client-supplied
  `recruiter_id`/`company_id`.
- `bulk-stage` checks ownership per id — an id belonging to another
  recruiter's job is reported as a per-id failure, not silently
  skipped or (worse) applied.
- `RecruiterPipelineHistory` and the stats/conversion/stale endpoints
  never surface another recruiter's data — confirmed by
  `test_pipeline_endpoints_are_isolated_across_recruiters`.
- Recruiter notes never appear in a candidate's own view (unchanged
  V18.2 behavior; re-verified by
  `test_recruiter_notes_and_interviews_still_work_alongside_pipeline_moves`).

## Performance

- Board cards reuse V24.2's batched candidate-row loader instead of a
  per-card query; match score is deliberately not recomputed per load.
- `RecruiterPipelineHistory` is indexed on `(applicant_id, changed_at)`
  and on `applicant_id`/`new_stage` individually, for the history,
  stats, and stale-candidate queries.
- Bulk-stage still writes one history row per accepted id (each move
  needs its own audit row), so a very large batch is still N writes —
  not a single query — by design.

## Testing

`backend/tests/test_v24_3_candidate_pipeline.py` — 10 tests, all
passing (verified per-file, see "How this was tested" below):
enriched board data; valid forward/backward transitions + history;
same-stage and unknown-stage rejection; `hired_at` set-once semantics;
candidate in-app notification on stage change; stats/conversion/stale
correctness including the zero-denominator case; bulk move with
partial-failure reporting; cross-recruiter isolation (including IDOR
via bulk-stage); notes/interviews unaffected by pipeline moves.

**Known, pre-existing (not introduced by V24.3):**

- `test_v24_2_candidate_discovery.py::test_job_candidate_matches_scores_and_explains`
  and `::test_natural_language_parse_is_deterministic_and_never_executes_sql`
  fail on the unmodified V24.2 codebase too (a semantic-scoring
  threshold flake and a `"Java"` vs `"java"` case-sensitivity
  assertion). Not touched by V24.3.
- The V23.5 changelog already documents that the backend's DB engine
  is a module-level singleton bound to whichever test file imports it
  first, so a combined `pytest tests/` run shares one database across
  files and isn't a reliable signal — the project's own established
  methodology (also used here) is per-file verification.

**How this was tested:** every file V24.3 touched or added was run
individually with a clean SQLite database
(`test_v9_platform.py`, `test_v18_2_job_management.py`,
`test_v18_3_candidate_detail_export_analytics.py`,
`test_v18_7_excel_export.py`, `test_v16b_recruiter_ats.py`,
`test_v24_1_recruiter_workspace.py`, `test_v24_2_candidate_discovery.py`,
`test_v24_3_candidate_pipeline.py`) — all pass except the two
pre-existing V24.2 failures above, which are unchanged from the
unmodified codebase (confirmed by running the same files against the
original, unmodified V24.2 zip). Frontend: `npx tsc --noEmit` and
`npm run build` both pass cleanly with the new pipeline page and CSS.

## Known limitations

- The migration's data rename (`applied → new`, etc.) is written for
  PostgreSQL (matching every other `backend/migrations/*.sql` file in
  this project); it hasn't been run against a live production
  database, only exercised via SQLite's `create_all()` in tests, which
  doesn't need it (fresh tables use the new names from the start).
- `hired_at` for applicants that were already `accepted` before V24.3
  is backfilled from `updated_at` (the last time the row changed at
  all) — a documented approximation, since no earlier stage-change
  timestamp exists to draw on.
- Offer-deadline-approaching notifications (spec section 20's example
  list) are not implemented — no existing scheduled job reads
  `OfferLetter.expiry_date`, and adding one is a bigger, separate
  piece of work than this version's scope.
- Bulk-stage is "no id is left half-updated," not one all-or-nothing
  database transaction across the whole batch — see that endpoint's
  docstring in `app/api/recruiter_pipeline.py` for the exact
  guarantee.
- A combined `pytest tests/` run is not a reliable regression signal
  for this codebase (pre-existing, see "Testing" above); this version
  was verified per-file instead, consistent with V23.5's established
  methodology.
