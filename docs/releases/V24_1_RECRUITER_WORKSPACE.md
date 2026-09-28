# V24.1 — Recruiter Workspace & Hiring Dashboard

## Summary

V24.1 turns the existing recruiter/company/applicant stack (V9, V16,
V18.1–V18.7) into a professional Employer Workspace: a single Overview
with real statistics, pending actions and a recent-activity feed; a
recruiter profile screen; and richer job-list data (application count,
expiry, review status). This is explicitly a **gap-filling pass, not a
rebuild** — most of what the V24.1 brief asked for (company profile,
company verification, team management, job CRUD/lifecycle, applicant
pipeline, notes, interviews, offer letters, CSV/Excel export,
analytics) already existed in V9–V18.7 and V16, and is reused
unmodified. Nothing about V16–V23.5 was rewritten, removed, or
duplicated.

## What already existed (reused, not touched)

| Area | Existing implementation |
|---|---|
| Recruiter auth/approval | `app.core.security.require_recruiter`, `User.recruiter_status` |
| Job ownership | `Job.owner_user_id`, `app.core.team_access.team_owner_ids` (V18.6 team-shared access) |
| Job lifecycle | `app.api.recruiter` create/update/submit-for-review/close/reopen/archive/clone; admin approval in `app.api.admin` |
| Company profile | `app.api.company` (`Organization`, `CompanyBranch`) |
| Company verification | `Organization.verification_status` |
| Team management | `CompanyTeamMember` |
| Applicant pipeline | `Applicant`, `PIPELINE_STAGES`, Kanban board (`GET/PATCH .../pipeline`, `.../stage`) |
| Notes / interviews / offers | `ApplicantNote`, `Interview`, `OfferLetter` |
| Analytics | `GET /recruiter/analytics` |
| Applicant export | CSV and `.xlsx` export endpoints |

## What V24.1 actually adds

### 1. `Job.published_at` (new column, additive)

`jobs.published_at` (nullable `TIMESTAMP`) is set once, the first time
`app.api.admin.publish()` moves a job to `status="published"`. A later
close/reopen never touches it again, so it keeps meaning "when this
listing first went public," distinct from `created_at` ("when the
recruiter first saved it"). Jobs published before this column existed
keep `published_at = NULL` — the API treats that as "unknown," never a
fabricated date. See `migrations/v24_1_recruiter_workspace.sql`.

A composite index `ix_jobs_owner_status (owner_user_id, status)` was
added alongside it, since every workspace query (dashboard, job list)
filters by exactly that pair.

No other schema change was made. `Job`, `Applicant`, `Organization`
were **not** duplicated; recruiter hiring status reuses `Applicant.status`
and `Applicant.pipeline_stage` exactly as V16/V18.2 defined them (see
"Status vocabulary" below).

### 2. `GET /recruiter/dashboard` — extended in place

The endpoint's URL and existing fields (`jobs_posted`,
`jobs_published`, `jobs_in_review`, `jobs_draft`, `jobs_closed`,
`jobs_archived`, `total_applicants`) are unchanged, so nothing that
already reads this endpoint breaks. New fields:

- `jobs_rejected`, `jobs_expired` — real counts (`jobs_expired` =
  published jobs whose `deadline` has passed; computed, not stored).
- `new_applications` — applicants with `status == "submitted"`.
- `candidates_in_interview` — `status == "interview"` OR
  `pipeline_stage` in `interview`/`technical_round`/`hr_round`.
- `offers` — count of `OfferLetter` rows for this recruiter's
  applicants (any status: draft/sent/accepted/declined/withdrawn).
- `pending_actions` — a list of `{type, count, message}` for anything
  needing recruiter attention right now (new applications, jobs
  awaiting admin review, rejected jobs, expired jobs). Empty list when
  there's nothing pending — never a placeholder entry.
- `recent_activity` — up to 20 events, newest first, assembled from
  **existing** `Job`/`Applicant` timestamps and status (job submitted
  for review / approved / rejected / closed; new application;
  candidate status changed). No new event-log table was created, per
  spec section 4 ("do not create duplicate activity storage").
  Limitation: because there is no persisted state-transition history
  for `Job` (unlike `Application`'s `ApplicationStatusHistory` on the
  candidate side), a job's activity entry reflects its *current*
  status with the best available timestamp (`published_at`,
  `closed_at`, or `updated_at`) — not a full audit trail of every
  status change that job has ever had. If a job has been
  submitted → rejected → resubmitted → approved, only the current
  state ("approved") shows up, not the intermediate rejection. This is
  an honest, documented gap, not a hidden one.
- `quick_actions` — `{create_job, manage_jobs, review_applications,
  edit_company_profile}` booleans, so the frontend never renders an
  action the recruiter's current state doesn't support (e.g.
  "manage jobs" is `false` for a recruiter with zero jobs).

Every number is a real aggregate query against `jobs`/`applicants`/
`offer_letters` for this endpoint's authenticated recruiter (and their
team, via `team_owner_ids`) — nothing is hard-coded, estimated, or a
placeholder "0" standing in for missing data.

### 3. `GET/PATCH /recruiter/profile` (new)

```
GET  /api/v1/recruiter/profile
PATCH /api/v1/recruiter/profile   {"full_name": "...", "phone": "..."}
```

Built entirely on the existing `users` table plus V18.1
`organizations`/V18.4 `company_team_members` — no new table. `GET`
returns the recruiter's name/email/phone/role/recruiter_status plus
which company they act for and in what capacity (`owner` or their
`CompanyTeamMember.role`). `PATCH` only accepts `full_name` and
`phone` — **`email` and `role` are deliberately not accepted fields**,
so a PATCH payload that includes them has those fields silently
ignored (standard Pydantic behavior for undeclared fields) and the
user's identity/role stays exactly what Authentication already set.
Phone uniqueness is enforced the same way registration already
enforces it (`User.phone` is a unique column).

### 4. Jobs list/preview — enriched, not replaced

`GET /recruiter/jobs` and `GET /recruiter/jobs/{id}` now return every
existing `Job` column (unchanged names/values) plus:

- `application_count` — real count from `applicants`, not a stored
  counter (avoids a second source of truth that could drift).
- `is_expired` — `true` only when `status == "published"` and
  `deadline` has passed; computed on read.
- `review_status` — an alias for `status`, under the name spec
  section 5 uses, without introducing a second, divergent status
  column.

## Status vocabulary (spec section 17)

The spec asks for a documented split between "Candidate Application
Status" and "Recruiter Hiring Status." That split already existed
before V24.1 and is unchanged here:

- **Candidate-facing** (`Applicant.status`): `submitted`,
  `shortlisted`, `interview`, `rejected`, `hired` — the simpler
  vocabulary shown to the candidate and used for status-change
  notification emails.
- **Recruiter-facing Kanban** (`Applicant.pipeline_stage`):
  `applied`, `shortlisted`, `screening`, `interview`,
  `technical_round`, `hr_round`, `offer`, `accepted`, `rejected`,
  `withdrawn` — the richer stage set shown on the recruiter's board.

V24.1 does not add a third status column. Dashboard aggregates (e.g.
`candidates_in_interview`) read from both columns where the spec's
category (e.g. "Interview") could reasonably map to either
vocabulary, rather than picking one and silently missing candidates
tracked under the other. Nothing overwrites either column; this is a
read-only aggregation layer.

## Authorization (unchanged, re-verified)

Every new/changed endpoint goes through the same two checks every
existing recruiter endpoint already uses:

1. `require_recruiter` — must be an authenticated user with
   `role == "recruiter"` and `recruiter_status == "approved"` (or an
   admin role).
2. Ownership — `_owned_job_or_404` / `team_owner_ids` restrict every
   job/applicant read to the requesting recruiter's own team, computed
   from `Job.owner_user_id` and `CompanyTeamMember` — never inferred
   from email, company name, or frontend state. A 404 (not a 403) is
   returned for another team's job, so a recruiter can't distinguish
   "not yours" from "doesn't exist."

`GET/PATCH /recruiter/profile` only ever reads/writes the caller's own
`User` row (`recruiter` from `require_recruiter`, never a
path-supplied id), so there is no cross-recruiter profile access
surface to test for IDOR.

## API

New/changed, all under `/api/v1/recruiter`:

| Method | Path | Change |
|---|---|---|
| GET | `/dashboard` | extended response (see above); same URL, backward-compatible |
| GET | `/jobs` | each item now includes `application_count`, `is_expired`, `review_status` |
| GET | `/jobs/{id}` | same enrichment |
| GET | `/profile` | new |
| PATCH | `/profile` | new |

Every other endpoint listed in the V24.1 brief (`/company`,
`/jobs/{id}/applications`, etc.) already existed under a slightly
different but equivalent path (`/company`, `/jobs/{id}/applicants`,
`/jobs/{id}/pipeline`) and was left as-is rather than duplicated.

## Database

- `migrations/v24_1_recruiter_workspace.sql` — `ALTER TABLE jobs ADD
  COLUMN IF NOT EXISTS published_at TIMESTAMP;` plus
  `CREATE INDEX IF NOT EXISTS ix_jobs_owner_status ...`. Safe to
  re-run. No historical migration was modified.
- SQLite dev/test path creates `published_at` and the index
  automatically from the updated `Job` model via
  `Base.metadata.create_all()`.

## Security review performed

Manual (static) review of every new/changed code path for the classes
of issue the brief calls out:

- **IDOR** — `/profile` reads/writes only `recruiter.id` (from the
  auth dependency, never a request parameter); job/applicant reads in
  the enrichment helpers reuse the existing `_owned_job_or_404`/
  `team_owner_ids` checks, not a new, possibly-looser check.
- **Cross-recruiter / cross-company access** — dashboard aggregates
  are scoped to `team_owner_ids(db, recruiter)`, the same team
  resolution every existing recruiter endpoint uses.
- **Mass assignment** — `RecruiterProfileIn` is an explicit allow-list
  (`full_name`, `phone` only); `email`/`role` are not declared fields,
  so they cannot be set via this endpoint regardless of payload
  content.
- **Private candidate data exposure** — no new field exposes anything
  beyond what `list_applicants`/`get_applicant_detail` already return;
  the dashboard activity feed exposes only `job_title`/`applicant_id`/
  `status`/`pipeline_stage`, never resume content or contact details.
- **N+1 / unbounded queries** — dashboard and job-list enrichment each
  issue a small, fixed number of queries per request (jobs, applicants
  for those jobs, offers for those applicants) rather than one query
  per row; `recent_activity` is capped at 20 entries in the response
  (computed from at most the recruiter's own jobs + up to 50 most
  recent applicants, not the whole table).

This was a **manual code review**, not a run of an automated SAST tool
or a live penetration test — see "Known limitations" below.

## Tests

`backend/tests/test_v24_1_recruiter_workspace.py` — 5 new tests:

1. `test_dashboard_counts_reflect_real_data` — publishing a job and
   receiving one application produces correct counts and a non-empty
   activity feed.
2. `test_job_list_includes_application_count_and_expiry` — a published
   job with a past deadline and one applicant shows
   `application_count == 1`, `is_expired == True`.
3. `test_recruiter_profile_get_and_update` — profile read reflects the
   registered account; a name change persists.
4. `test_recruiter_profile_cannot_change_email_or_role` — a PATCH
   payload containing `email`/`role` is accepted (200) but those
   fields are silently ignored; the account's real email/role are
   unchanged afterward.
5. `test_dashboard_and_jobs_are_isolated_across_recruiters` — a second
   recruiter's dashboard/job-list/job-preview never surfaces the
   first recruiter's job (404 on direct preview, absent from listing,
   zero counted on their own dashboard).

## PASS / FAIL / NOT VERIFIED

Reported honestly, per the brief's own instruction not to claim PASS
without actually running anything:

| Check | Result |
|---|---|
| `python -m py_compile` on every changed/added Python file | **PASS** — ran in this sandbox; all compile cleanly |
| New backend tests (5) | **NOT VERIFIED** — this sandbox has no outbound network access, so `pip install` for `fastapi`/`sqlalchemy`/etc. fails and the suite cannot be executed here. Written to the existing `pytest`/`TestClient` pattern used by `test_v16b_recruiter_ats.py`; needs to be run in an environment with dependencies installed. |
| Full existing backend suite (regression) | **NOT VERIFIED** — same reason. No code path outside the files listed under "Files changed" was touched, so no regression is *expected*, but that is not the same as a passing run. |
| Frontend build / type-check / lint | **NOT VERIFIED** — same sandbox limitation (no `npm install`). |
| Manual security review (IDOR, mass assignment, cross-tenant access) | **PASS** (manual/static) — see "Security review performed" above; not a substitute for an automated scan or live test. |
| Migration validity | **PASS** (manual review) — matches the exact `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` pattern every prior additive migration in this repo uses; SQLite dev path re-derives the same schema from the model automatically. |

This mirrors how prior versions in this same repository were honestly
logged (e.g. V23.3/V23.4's "N new tests written — not executed in the
authoring sandbox") rather than a new standard invented for this
release.

## Known limitations

- `recent_activity` shows current job status with the best available
  timestamp, not a full history of every status transition (no job
  state-history table exists — see "recent_activity" note above).
- `offers` on the dashboard counts `OfferLetter` rows in any state; it
  does not distinguish "extended" from "accepted" the way `/analytics`
  already does (`offers_sent`/`offers_accepted`/
  `offer_acceptance_rate_pct`) — a recruiter wanting that breakdown
  should still use `/recruiter/analytics`, which is unchanged.
- Advanced candidate search (spec section 9) is explicitly out of
  scope for V24.1, per the brief itself ("belongs to V24.2").
- No responsive/accessibility frontend audit was performed on the
  existing recruiter pages beyond the small changes made in this pass
  (see the frontend changes below); a full accessibility pass across
  the whole recruiter workspace was not part of this version's scope
  and was not claimed as done.
- Tests and build were not executed (see table above) — treat this as
  code review-complete, not deployment-verified, until run in a real
  environment.

## Files changed

- `backend/app/models/domain.py` — `Job.published_at`,
  `Job.__table_args__` index.
- `backend/migrations/v24_1_recruiter_workspace.sql` — new.
- `backend/app/api/admin.py` — set `published_at` on publish.
- `backend/app/api/recruiter.py` — `_job_to_dict` helper; enriched
  `list_my_jobs`/`preview_my_job`; extended `recruiter_dashboard`;
  new `GET/PATCH /profile`.
- `backend/tests/test_v24_1_recruiter_workspace.py` — new.
- `frontend/src/app/recruiter/page.tsx` — Overview stats, pending
  actions, recent activity, quick actions, profile link.
- `frontend/src/app/recruiter/profile/page.tsx` — new.
- `CHANGELOG.md`, `README.md` — version entries.
