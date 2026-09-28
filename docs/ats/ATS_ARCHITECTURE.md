# CareerOS ATS Architecture

Status: describes what is implemented as of this document's writing (V16b
through V18.5). Several items from the original V18 "Enterprise Recruiter
ATS" scope are **not yet built** â€” see "Not yet implemented" at the end.
This file is the map for future work, not a claim that the full V18 spec
is done.

## 1. Scope and boundaries

The ATS is additive on top of the existing CareerOS platform. It deliberately
does **not** touch:

- Authentication (`app/api/auth.py`, `app/core/security.py`)
- Security / RBAC (`app/core/security.py`, `app/api/admin_rbac.py`)
- Government Hub (public jobs ingestion/search)
- AI, Search, Notifications, Analytics (platform-wide), Deployment/Docker

Every ATS module reuses the existing `User` model and role system
(`role='recruiter'`, `recruiter_status='approved'`, gated by
`require_recruiter` in `app/core/security.py`) rather than introducing a
parallel account system.

## 2. Modules and where they live

| Module | Backend | Frontend | Migration(s) |
|---|---|---|---|
| Recruiter jobs/applicants/pipeline/interviews/offers/analytics | `app/api/recruiter.py` | `frontend/src/app/recruiter/*` | `v16b_recruiter_ats.sql`, `v18_2_job_management.sql` |
| Company profile & directory | `app/api/company.py` | `frontend/src/app/recruiter/company`, `frontend/src/app/companies` | `v18_1_company.sql` |
| Team management (roster + shared job access) | `app/api/company.py`, `app/core/team_access.py` | `frontend/src/app/recruiter/company/team` | `v18_4_team_management.sql` |
| Email templates | `app/api/email_templates.py` | `frontend/src/app/recruiter/company/email-templates` | `v18_5_email_templates.sql` |

All routers are mounted from `app/api/routes.py`. Models live in one shared
file, `app/models/domain.py` (SQLAlchemy declarative, `Base.metadata` is
used by tests on SQLite; PostgreSQL uses the versioned `.sql` files under
`backend/migrations/`, applied by `backend/scripts/run_migrations.py`).

## 3. Data model (ATS-relevant tables)

- `jobs` â€” pre-existing table, extended with recruiter-only lifecycle
  fields (`JOB_LIFECYCLE_STATUSES` in `app/core/constants.py`: draft,
  review, published, closed, archived, rejected). `organization` stays a
  free-text string (used by government ingestion/search) â€” a `Company`
  profile is a separate, optional record a recruiter attaches jobs to via
  ownership, not a required foreign key.
- `applicants` / `applicant_notes` â€” candidate applications to a job, plus
  private recruiter notes.
- `interviews` â€” scheduled interviews per applicant (`interview_type`,
  date/time, interviewer, meeting link, status).
- `offer_letters` â€” one active offer per applicant, with status
  (draft/sent/accepted/rejected/expired).
- `organizations` / `company_branches` / `company_team_members` â€” the
  Company module (profile, office locations, roster).
- `email_templates` â€” one row per `(company_id, template_type)`, seeded
  lazily from `EMAIL_TEMPLATE_DEFAULTS` on first read/edit.

Pipeline stages (`PIPELINE_STAGES` in `app/core/constants.py`): applied,
shortlisted, screening, interview, technical_round, hr_round, offer,
accepted, rejected, withdrawn. This is a richer, Kanban-facing vocabulary
layered on top of the older `Applicant.status` field rather than replacing
it. The Kanban board itself â€” full HTML5 drag-and-drop between stage
columns, with an optimistic move that rolls back on a failed API call â€”
lives at `frontend/src/app/recruiter/jobs/[id]/pipeline/page.tsx`, linked
from each job's row in `/recruiter/jobs`. (The older `/recruiter`
dashboard page has a separate, simpler status-button applicant list from
before the pipeline board existed â€” that one predates Kanban and isn't
part of it.)

## 4. Ownership and access model

- A job belongs to a recruiter via `Job.owner_user_id`
  (`app.api.recruiter._owned_job_or_404`).
- A company profile belongs to a recruiter via
  `Organization.owner_user_id` (`app.api.company._owned_company_or_404`).
- **V18.6 â€” team-shared job access.** `app.core.team_access.team_owner_ids`
  resolves, for any recruiter, the full set of user_ids whose jobs they
  can read/manage: their own id, plus â€” if they own or belong to a
  company â€” every other member of that company's team
  (`CompanyTeamMember`). `_owned_job_or_404`, `list_my_jobs`,
  `/recruiter/dashboard`, and `/recruiter/analytics` all use this instead
  of a bare `== recruiter.id` check, so any teammate can see, edit, move
  through the pipeline, schedule interviews for, and send offers on any
  job owned by anyone on the same team â€” not just the job's original
  creator. A solo recruiter with no company/team sees identical behavior
  to before this change (the set is just `{their own id}`).
  Company profile management (branches, roster, verification) and
  **email templates stay owner-only** â€” deliberately not widened in this
  pass, since customizing shared wording/branding is a different kind of
  decision than working an applicant pipeline together.

## 5. Email templates

`app/api/email_templates.py` gives each company one editable copy of five
template types: `application_received`, `interview_invitation`,
`interview_reminder`, `offer`, `rejection`.

- Defaults and placeholder text live in `EMAIL_TEMPLATE_DEFAULTS`
  (`app/core/constants.py`); a company's row is created lazily the first
  time it's read or edited, so adding a new type later needs no backfill
  migration.
- Placeholders use `{{variable_name}}` syntax
  (`EMAIL_TEMPLATE_VARIABLES`: candidate_name, job_title, company_name,
  recruiter_name, interview_type, interview_date, interview_time,
  meeting_link). `render_template()` in the same file does the
  substitution; unmatched placeholders are left as-is rather than blanked.
- Endpoints: `GET /recruiter/company/email-templates` (list, seeds all
  five), `GET`/`PUT .../{type}`, `POST .../{type}/reset`,
  `POST .../{type}/preview` (renders against sample data or caller-supplied
  overrides, does not persist), `GET .../email-templates-meta/variables`.
- **This module stores and renders text only â€” it does not send email.**
  Wiring template selection into the actual send path (application
  received, interview scheduling, offer, rejection) is future work that
  will need to touch Notifications, which V18 scope explicitly excludes.

## 6. Applicant exports

`GET /recruiter/jobs/{job_id}/applicants/export` (CSV) and
`GET /recruiter/jobs/{job_id}/applicants/export.xlsx` (Excel) share one
row-building helper (`_applicant_export_rows` in `app/api/recruiter.py`)
so the two formats can't drift apart on columns. The Excel version is
built in-memory with `openpyxl` (added to `backend/requirements.txt`) â€”
bold header row, auto-sized columns, no temp file on disk â€” and streamed
back the same way the CSV already was. Both respect the V18.6 team-shared
ownership check.

## 7. Not yet implemented (open Phase 3 items)

Carried over from the original V18 spec and not built in this pass:

- Email templates and company-profile management still owner-only (see
  Â§4 â€” deliberate, not an oversight, but open if you want it widened too).
- Approval workflow UI beyond the existing submit-for-review/approve/reject
  states already in `JOB_LIFECYCLE_STATUSES` and `app.api.admin`.
- OpenAPI examples/Swagger polish beyond FastAPI's default schema.
- Full regression pass across V16/V17 candidate, recruiter, and admin flows
  in a real (non-sandboxed) environment â€” this pass could not run
  `pytest`/`next build` here because the sandbox has no network access to
  install dependencies; see TEST_REPORT-equivalent notes in the PR/commit
  description instead.

