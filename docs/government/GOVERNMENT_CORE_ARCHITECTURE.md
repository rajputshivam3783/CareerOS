# GOVERNMENT_CORE_ARCHITECTURE â€” V19.1 Government Recruitment Core

Builds on V16c (Government Hub) and V18 (Company Module, Job
Management, Team Management, Email Templates). Authentication,
Security, Recruiter ATS, AI, Search, Notifications, Analytics,
Deployment, and Docker were not touched, per this pass's explicit
scope boundary.

## Design decision: extend, don't replace

Before writing any code, the existing repository was read in full.
V16c already implements a working Government Hub on top of the
generic `Job` model (`Job.job_type = "Government"`), with:

- Almost every field the V19.1 spec calls the "Recruitment Entity"
  (title, organization, department, category, vacancies, age_limit,
  application_fee, salary, selection_process, notification/apply/
  official URLs, source_name/source_reference, status) already present
  on `Job`.
- A working lifecycle-timeline table, `RecruitmentUpdate`
  (`recruitment_updates`), validated against a whitelist
  (`RECRUITMENT_UPDATE_TYPES` in `app/core/constants.py`) â€” this *is*
  the "Recruitment Lifecycle" table the spec asks for.
- A working moderation state machine reusing `Job.status`
  (`draft â†’ review â†’ published`, plus `closed`/`archived`/`rejected`
  â€” see `JOB_LIFECYCLE_STATUSES`).
- A working duplicate-detection service
  (`app/ingestion/services/deduplicate.py`).
- A working pluggable ingestion framework (`app/ingestion/` â€”
  `BaseJobAdapter`, adapters, `normalize_job`, `publish_to_review`)
  and a per-run ingestion log (`IngestionRun`).
- A working "Government Dashboard" (`GET /government/home` in
  `app/api/platform.py`) with latest/closing-soon/counts cards, and
  category sections for every lifecycle stage.

Given that, and the instruction to reuse existing architecture and
not redesign existing modules, V19.1 **extends the existing Job-based
model in place** rather than building a second, parallel
Organization/Recruitment schema. Concretely, V19.1 adds:

1. A new `GovernmentOrganization` table (`government_organizations`)
   â€” a structured government-body catalog that a Government `Job` can
   *optionally* link to via the new `Job.organization_id` (nullable).
   `Job.organization` (free text) is untouched and remains how every
   existing Government Job â€” and any future one that never links to
   an organization row â€” identifies its issuer.

   **Naming note:** there is a pre-existing, unrelated `Organization`
   model (V18.1 Company Module) mapped to table `organizations`, used
   for private-sector recruiter companies. `GovernmentOrganization` /
   `government_organizations` is a deliberately distinct name and
   table â€” the two do not share rows or code paths.

2. Two new columns on `Job`: `ad_number` (advertisement number) and
   `answer_key_url`, alongside the existing V7 exam-lifecycle columns
   (`admit_card_url`, `result_url`, ...).

3. A new `SourceRegistry` table (`source_registry`) â€” one row per
   ingestion source (as opposed to `IngestionRun`, which is one row
   per *run* of a source). Every future adapter registers itself here
   with its schedule/status; `POST /government/sources/{id}/sync-runs`
   rolls the existing `IngestionRun` log up into
   `last_run_at`/`last_success_at`/`error_count` for that source.

4. Twelve new lifecycle stages added to `RECRUITMENT_UPDATE_TYPES`
   (see `RECRUITMENT_LIFECYCLE.md`) â€” additive to the existing set,
   nothing removed.

5. Duplicate detection extended to also compare `ad_number` (scoped to
   organization, since an ad number is only unique within its issuing
   organization) and `official_url`, alongside the pre-existing
   source/notification-URL/organization+title checks.

6. A new, additive API router, `app/api/government_core.py`, mounted
   at `/api/v1/government/*` alongside (not replacing) the existing
   `/api/v1/government/home`, `/sections/{section}`, `/coverage`
   routes in `app/api/platform.py`.

## What was deliberately *not* built

- A parallel `Recruitment` entity â€” `Job` already covers that surface
  area; adding a second table for the same data would fork the two
  Government surfaces this codebase already has to keep in sync
  forever, which is the opposite of the "reuse existing architecture"
  instruction.
- Real scrapers for UPSC/SSC/RRB/IBPS/state PSCs, or any new
  automated collector â€” explicitly out of scope for V19.1 (belongs to
  V19.2+). The ingestion *framework* (adapters, normalize, dedupe,
  publish-to-review) already existed pre and needed no new code
  to satisfy this requirement; V19.1 only adds the standing
  `SourceRegistry` catalog on top of it.
- Government-specific notifications/alerts â€” out of scope, per the
  prompt's explicit "DO NOT TOUCH: Notifications" and stop condition.

## New API surface

All mounted under `/api/v1/government` (see `app/api/government_core.py`):

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/organizations` | public | List/search government organizations |
| GET | `/organizations/{id}` | public | Fetch one organization |
| POST | `/organizations` | admin | Create an organization |
| PATCH | `/organizations/{id}` | admin | Update an organization |
| DELETE | `/organizations/{id}` | admin | Soft-delete (status â†’ `inactive`) |
| POST | `/duplicate-check` | admin | Preflight duplicate check before manual curation |
| GET | `/moderation/queue` | admin | Government-scoped view of the review queue |
| GET | `/sources` | admin | List the source registry |
| POST | `/sources` | admin | Register a new source |
| PATCH | `/sources/{id}` | admin | Update a source's schedule/status |
| POST | `/sources/{id}/sync-runs` | admin | Roll IngestionRun history into this source's summary |
| GET | `/dashboard/extended` | public | Latest Results / Latest Admit Cards cards |

Existing endpoints this builds on, unchanged:

- `GET /government/home`, `GET /government/sections/{section}`,
  `GET /government/coverage`, `GET /jobs/{id}/timeline` (`app/api/platform.py`)
- `GET /admin/review`, `POST /admin/jobs/{id}/publish`,
  `POST /admin/jobs/{id}/reject`, `POST /admin/jobs/{id}/updates`,
  `POST /admin/ingest`, `POST /admin/ingest/bulk` (`app/api/admin.py`)

## Database

See `migrations/v19_1_government_core.sql` and `SOURCE_REGISTRY.md`.
Every change is additive (`CREATE TABLE IF NOT EXISTS`,
`ADD COLUMN IF NOT EXISTS`) and backward compatible â€” no existing
column, table, or row is altered destructively.

## Frontend

- `frontend/src/app/admin/government/page.tsx` â€” new admin console
  (Organizations / Moderation queue / Source registry tabs), reusing
  the existing admin auth pattern (`X-Admin-Key` header or an
  admin-role session) from `frontend/src/app/admin/page.tsx`, and the
  existing global CSS classes (`.card`, `.btn`, `.field`, `.jobs`,
  `.chip`, ...) rather than introducing a new design system.
- `frontend/src/components/Nav.tsx` â€” one new nav link ("Govt Admin"),
  gated behind the same `role==="admin"||"super_admin"` check as the
  existing "Admin" link.
- The existing public Government Hub (`frontend/src/app/government/page.tsx`)
  was not modified.

