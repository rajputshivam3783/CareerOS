# CareerOS roadmap — target plan vs. this build

This maps the requested version plan to what already exists in this ZIP, so
the gap to close for each version is clear.

| Version | Focus | Target scope | Status in this ZIP |
|---|---|---|---|
| V1.0 | Foundation | UI, backend, PostgreSQL, search/filter, core opportunity system | **Done** — FastAPI + SQLAlchemy + Next.js, SQLite (zero-config) and PostgreSQL both supported, `/jobs` search/filter/pagination |
| V2.0 | Government jobs | Real official sources + automated collection | **Built, sources disabled by default** — generic RSS adapter + configurable HTML listing-page adapter, a source registry (`app/ingestion/sources.py`), an in-process scheduler for recurring runs, an on-demand admin trigger, and per-run history (`ingestion_runs` table). *What's intentionally not done:* no source ships pre-enabled — every listed source's selectors are placeholders that must be verified against the live site before switching it on (see `sources.py` and the "V2 details" note below) |
| V3.0 | Private careers | Jobs, internships, apprenticeships | **Built** — dedicated fields (employment type, work mode, industry, experience, stipend, duration), a partner submission API for employers/aggregators, and real public-API collectors for Greenhouse/Lever-hosted company boards. Frontend job-type filter chips added. *Ships with example sources disabled* — see "V3 details" below |
| V4.0 | Personalization | Login, profile, saved jobs, personalized feed | **Done** — JWT auth, profile CRUD, saved jobs; recommendations endpoint acts as the personalized feed |
| V5.0 | Eligibility AI | "Am I eligible?", notification/PDF parsing, eligibility rules | **Built** — dedicated eligibility engine (`app/services/eligibility.py`) with qualification + age-limit + indicative reservation-category relaxation checks, a heuristic PDF notification parser (`app/ingestion/services/pdf_parser.py`) wired to `POST /admin/ingest/pdf`, and a readable "Am I eligible?" result in the frontend. Always reports uncertainty where the source data can't support a real answer — see "V5 details" below |
| V6.0 | Career intelligence | AI job matching, recommendations, Career AI, semantic search | **Built** — `GET /search/semantic` (TF-IDF cosine-similarity search), a blended match-score engine (skill-token overlap + TF-IDF text similarity), and `GET /career-ai/{job_id}` combining eligibility + match + skill-gap with an optional LLM-narrated summary (template fallback with no API key). See "V6 details" below for what "semantic"/"AI" honestly mean here |
| V7.0 | Application OS | Tracker, deadlines, alerts, exams/admit cards/results | **Built** — application tracker, exam-lifecycle fields on jobs (admit card, result), an idempotent in-app notification scan (deadline reminders, admit-card/result releases, and saved-search alert matches) running hourly, and a notifications inbox in the frontend. *In-app only, not email/SMS* — see "V7 details" below for why and the upgrade path |
| V8.0 | Career growth | Resume-JD matching, skill-gap analysis, learning roadmap, exam prep | **Built** — PDF/DOCX resume upload + skill detection, resume-vs-job matching (skill overlap + TF-IDF similarity), a phased learning roadmap, and admin-curated exam-prep resources (syllabus/previous papers/mock tests/cutoffs) per job or organization. See "V8 details" below for why exam-prep content is curated, not generated |
| V9.0 | Platform | Recruiter/admin/platform features | **Built** — admin-granted recruiter role (`POST /admin/users/{id}/role`), a recruiter-facing job posting + editing API that still goes through the same review queue, and a candidate-facing apply flow with an applicant pipeline (submitted/shortlisted/interview/rejected/hired) recruiters manage for their own jobs only. Real role-based auth (JWT + role check), not the shared admin key — see "V9 details" below |
| V10.0 | Scale | Production-grade, optimized, scaled | **Built** — CI (lint + tests on every push), pagination on every list endpoint that could grow unbounded, configurable Postgres connection-pool sizing, a migration runner (`scripts/run_migrations.py`), a hardened production Docker Compose (fails closed on missing secrets, non-root containers, healthchecks — fixed a real bug where it never set `ENVIRONMENT=production`, leaving `/docs` exposed), and a load-test starting script. See "V10 details" below for what's still honestly out of scope for a codebase (real hosting, monitoring, an actual executed load test) |

## Bug review pass — critical fix

A later review of this codebase (after all ten versions were built)
found one **critical, app-breaking bug** and one real architectural
risk, both now fixed:

1. **App wouldn't start at all.** `app/services/resume_match.py` (V8)
   imported a function `text_similarity` from
   `app/services/semantic_search.py` (V6) that was never actually
   defined there — that module only had `rank_by_similarity`. Since
   `platform.py` imports `resume_match` at module level, and
   `main.py` → `routes.py` → `platform.py` runs at startup, this
   `ImportError` would have crashed the **entire API**, not just
   resume matching — every endpoint, not only V8's. This is exactly
   the class of bug a syntax-only check (`py_compile`) can't catch,
   since the file itself was valid Python; it only breaks at import
   time. Fixed by adding the missing `text_similarity` function to
   `semantic_search.py`. Verified with a script that parses every
   `app.*` import across the codebase and confirms the imported name
   actually exists in its target module — zero remaining issues.
2. **Scheduler duplication risk with multiple workers.** The V10 pass
   set the backend Dockerfile to run 2 worker processes
   (`WEB_CONCURRENCY=2`) for throughput, without noticing that the
   in-process background scheduler (V2 ingestion + V7 notifications)
   would then run **once per worker** — duplicating outbound ingestion
   requests, and creating a real race condition where two workers
   could both pass the "already notified?" check before either
   commits, producing duplicate notification rows. Fixed: added
   `SCHEDULER_ENABLED` (default `true`), changed the Dockerfile default
   back to `WEB_CONCURRENCY=1` (safe out of the box), and documented in
   `app/scheduler.py`, the Dockerfile, and `docker-compose.production.yml`
   that raising worker/replica count requires setting
   `SCHEDULER_ENABLED=false` on all but one.

3. **The migration runner itself was silently corrupting almost every
   migration.** `scripts/run_migrations.py`'s statement splitter
   rejected an entire SQL statement whenever a comment line preceded
   it with no semicolon in between (which is how every migration file
   in this project is written — a `--` header comment directly above
   the first statement). Concretely, on a real PostgreSQL database
   this would have: dropped `ALTER TABLE jobs ADD COLUMN ... status`
   from `v1_safe_upgrade.sql`; **entirely failed** `v2_ingestion_runs.sql`
   (its `CREATE TABLE ingestion_runs` was dropped, so the following
   `CREATE INDEX ... ON ingestion_runs(...)` errored against a
   nonexistent table, aborting that file's transaction) — which would
   have stopped the whole migration run before V3/V5/V7/V8/V9 ever
   applied, since the script exits on the first failure; and separately
   dropped `employment_type` (V3), `reservation_category` (V5),
   `admit_card_url` (V7), and `owner_user_id` (V9) even if the runner
   had gotten that far. Verified concretely (simulated the exact
   statement list that would reach Postgres) rather than just reading
   the code — the `CREATE INDEX` on a table that was never created is
   what would have surfaced this immediately on first deployment.
   Fixed by rewriting the splitter to strip only comment *lines* from
   within each statement chunk instead of discarding the whole chunk
   when it starts with one; re-verified every migration file now
   produces exactly as many statements as it has semicolons.

All three fixes are reflected in the code below.

## V2 details — what was actually built this session

- `app/ingestion/collectors/http_client.py` — shared fetcher with a
  real identifying user-agent, timeout, and a best-effort
  `robots.txt` check.
- `app/ingestion/collectors/rss_adapter.py` — generic RSS/Atom
  adapter (stdlib XML parsing, no new trust-boundary dependency).
- `app/ingestion/collectors/html_list_adapter.py` — generic,
  *configured* HTML listing-page scraper (BeautifulSoup +
  `html.parser`, pure Python).
- `app/ingestion/sources.py` — the source registry. **Every source
  ships `enabled=False`.** This is deliberate: government page layouts
  change without notice, and shipping "confirmed working" selectors
  I can't personally re-verify against today's live markup would be
  the same kind of false certainty the project's own README already
  warns against for V2. Enabling a source is a one-line flip once
  someone has actually checked the current page.
- `app/scheduler.py` — APScheduler background job, gated by
  `INGESTION_ENABLED` (off by default), running every
  `INGESTION_INTERVAL_MINUTES`.
- New admin endpoints: `GET /admin/ingest/sources`,
  `POST /admin/ingest/run[?source=...]`, `GET /admin/ingest/runs`.
- New `ingestion_runs` table (+ `migrations/v2_ingestion_runs.sql`)
  recording discovered/created/skipped counts and errors per run.
- `scripts/run_ingestion_now.py` — CLI entry point for manual runs or
  an external cron, for multi-replica deployments where you don't want
  the in-process scheduler running on every instance.

Collected data still always lands in the review queue — automation
changes *how notices get discovered*, not the requirement that a human
verifies and publishes them.

## V3 details — private careers, internships, apprenticeships

- **New `Job`/`JobRecord` fields:** `employment_type`, `work_mode`,
  `industry`, `experience_required`, `stipend`, `duration` — plus a
  shared vocabulary in `app/core/constants.py` (`JOB_TYPES`,
  `EMPLOYMENT_TYPES`, `WORK_MODES`) so the API can validate these
  instead of accepting arbitrary free text.
- **`app/ingestion/adapters/generic_metadata.py`** — one reusable
  metadata adapter for private/internship/apprenticeship listings
  (parameterized by organization + job_type), replacing the idea of a
  separate hardcoded adapter per employer, which doesn't make sense
  when there are many employers rather than one fixed commission.
- **`app/api/partners.py` — the V3 intake channel.** Employers or
  authorized aggregators register as a `Partner` (`POST
  /admin/partners`, admin-guarded, returns a one-time API key whose
  hash is stored — never the key itself) and submit listings directly
  via `POST /partners/jobs` with `X-Partner-Id`/`X-Partner-Key`
  headers. This is the deliberate alternative to scraping commercial
  job boards: **LinkedIn, Naukri, Internshala, and similar platforms'
  terms of service generally prohibit automated scraping**, so
  building a scraper against them isn't a "V3 adapter," it's a ToS
  violation. Direct submission is the legitimate path.
- **Real, permitted public APIs for private-sector automated
  collection:** `collectors/greenhouse_adapter.py` and
  `collectors/lever_adapter.py`. Greenhouse's job-board API and
  Lever's postings API are public, documented, unauthenticated
  endpoints that companies using those ATSes expose specifically so
  external sites can read their open roles — reading them isn't a
  scraping/ToS problem the way reading LinkedIn would be. Both ship as
  disabled example entries in `sources.py` with placeholder tokens;
  enabling one for a real company means swapping in that company's
  actual `board_token`/`site_slug` from their public careers URL.
- **Frontend:** `jobs/page.tsx` now has job-type filter chips
  (Government/Private/Internship/Apprenticeship) and displays
  employment type, work mode, and stipend/duration when present.
- **Migration:** `migrations/v3_private_careers.sql` (additive columns
  + new `partners` table).

## V5 details — eligibility AI

- **`app/services/eligibility.py`** — a dedicated engine (split out
  from the old combined `career.py`) covering:
  - **Qualification check** — same keyword-level matching as before,
    reports `None` (not a false "no") when the source qualification
    text is just "See official notification".
  - **Age check** — parses the job's `age_limit` free text into a
    (min, max) range via regex covering the common phrasings ("18-27
    years", "Between X and Y years", "Not exceeding X years",
    "Minimum X years"), computes the candidate's age as-on the job's
    deadline/exam date (matching the standard government-exam
    convention), and applies an **indicative** age-relaxation estimate
    based on the candidate's self-reported reservation category
    (`General`/`EWS`/`OBC`/`SC`/`ST`) and PwD status. These relaxation
    years are widely-used SSC/UPSC-style conventions, not a guaranteed
    figure for every exam — the response always says so explicitly.
  - Combined verdict: `eligible` is `True` only if neither check
    failed and at least one passed; `None` when the underlying data is
    too vague to check; `False` only on a clear mismatch.
  - New optional `Profile` fields: `reservation_category`, `is_pwd` —
    self-reported by the candidate, used only for this estimate, never
    inferred or required (see `migrations/v5_eligibility.sql`).
  - Unit-tested in `tests/test_eligibility.py` (age parsing, age math
    across birthdays, relaxation applying correctly, and the
    "unverifiable → None, not False" behavior).
- **`app/ingestion/services/pdf_parser.py`** — heuristic extraction of
  qualification/age-limit/vacancies/fee/deadline/exam-date from an
  uploaded notification PDF's text (via `pypdf`, previously an unused
  dependency). Explicitly heuristic: returns which fields were
  actually found (`fields_found`) so a reviewer isn't misled into
  trusting an apparently-complete record, and returns nothing (no
  crash) for a scanned-image PDF with no extractable text.
- **`POST /admin/ingest/pdf`** — uploads a PDF + title/organization,
  runs the parser, and sends the result through the same
  normalize → dedupe → review pipeline as every other source — a
  parsed PDF is never auto-published either.
- **Frontend:** the Career AI page now renders a readable eligibility
  verdict (qualification/age reasons, computed age, relaxation applied,
  a disclaimer) instead of raw JSON; the dashboard profile form gained
  date-of-birth, reservation category, and PwD fields — and a real bug
  is fixed here: the old form was overwriting `date_of_birth` with
  `null` on every save regardless of what was entered.

## V6 details — career intelligence

**What "semantic" honestly means here:** `GET /search/semantic` and the
new similarity component in match scoring both use **TF-IDF cosine
similarity** (`app/services/semantic_search.py`), a classical
statistical text-similarity technique — not a neural embedding model.
It beats exact keyword `LIKE` search at handling paraphrasing and
shared vocabulary (a query for "remote data analyst role" will surface
a posting titled "Data Analyst — Work From Home" if their text shares
enough words), but it won't recognize true semantic equivalence
between completely different wording with no shared vocabulary at
all. The docstring in that module documents the upgrade path to a
real embedding model without changing the calling contract, for when
that dependency weight is worth it.

- **`GET /search/semantic?q=...`** — public endpoint, ranks published
  jobs by similarity to a free-text query.
- **`match_score()` (V6, in `services/career.py`)** — rebalanced to
  blend the existing skill-token overlap with a TF-IDF similarity
  between the candidate's whole profile text and the job's text,
  returning a `breakdown` of each component so the score stays
  explainable rather than becoming a single opaque number.
- **`GET /career-ai/{job_id}`** — one combined view: eligibility (V5),
  match score (V6), and skill gap (V8), plus `advice`: a short
  natural-language summary. **What "AI" honestly means here:** the
  summary only narrates numbers/reasons the deterministic engines
  already computed — see `app/services/career_ai.py`'s docstring. With
  no `CAREER_AI_ANTHROPIC_API_KEY` set, it returns a clear
  template-built summary from the same data (`"source": "template"`)
  so the feature works with zero external calls and zero cost; setting
  a key switches to an LLM-narrated version (`"source": "anthropic"`)
  that's explicitly instructed to use only the given facts and never
  invent eligibility criteria.
- **Frontend:** Jobs page has a "Semantic: on/off" toggle next to
  search; Career AI page now calls the one combined endpoint and shows
  a readable verdict, reasons, skills to build, and the summary instead
  of raw JSON dumps per endpoint.
- **Tests:** `tests/test_v6_career_intelligence.py` — semantic ranking
  puts the relevant job first, empty-input handling, and the
  template-fallback path when no API key is set.

## V7 details — Application OS

- **Exam lifecycle on `Job`:** `admit_card_url`, `admit_card_date`,
  `result_url`, `result_date` — filled in later via
  `PATCH /admin/jobs/{id}` as a recruitment progresses, rather than
  requiring the full record to be known at initial ingestion.
- **`app/services/notifications.py` — one idempotent scan, three
  triggers:**
  1. **Deadline reminders** — anyone who saved or applied to a job
     gets notified once its deadline is within
     `DEADLINE_REMINDER_DAYS` (default 3).
  2. **Admit-card / result releases** — notified once
     `admit_card_date`/`result_date` is reached.
  3. **Saved-search alerts** — the pre-existing `Alert` model (a
     saved query) is now actually wired up: newly-published jobs
     matching an enabled alert's search term notify its owner, using
     the same title/organization/description/qualification match as
     `GET /jobs`. Each alert tracks its own `last_checked_at`
     watermark so nothing is re-notified or missed on a gap.
  Every path is deduplicated per (user, job, notification type), so
  running the scan repeatedly — every hour via the scheduler, or
  immediately after a `PATCH /admin/jobs/{id}` lifecycle update — never
  creates duplicate notifications.
- **Delivery is in-app only.** No SMTP/SMS credentials are configured
  or assumed anywhere in this project, and claiming to have emailed or
  texted someone without an actual verified provider wired up would be
  a worse failure than an honest in-app inbox. The upgrade path (call
  a real provider inside `_notify_once`, keep the in-app row as the
  fallback record) is documented in the module itself.
- **Scheduler consolidation:** the V2 ingestion scheduler and the new
  V7 notification scan now share one `BackgroundScheduler` instance
  (`app/scheduler.py`) instead of running two separate ones — the
  notification scan runs unconditionally (it's DB-only, no outbound
  requests), while ingestion stays gated by `INGESTION_ENABLED` as
  before.
- **New endpoints:** `GET /notifications`, `GET
  /notifications/unread-count`, `POST /notifications/{id}/read`,
  `POST /notifications/read-all`, plus admin-side
  `POST /admin/notifications/scan` to trigger a pass on demand.
- **Frontend:** a Notifications inbox page, an unread-count badge in
  the nav, and `PATCH`-driven admin lifecycle updates that trigger an
  immediate scan rather than waiting for the next scheduled run.
- **Migration:** `migrations/v7_application_os.sql` (additive job
  columns, new `notifications` table, `alerts.last_checked_at`).
- **Tests:** `tests/test_v7_application_os.py` — a deadline
  notification is created once and not duplicated on a second scan,
  and mark-read/mark-all-read both work correctly.

## V8 details — career growth

- **Resume upload & parsing** (`app/services/resume_parser.py`) — PDF
  (via `pypdf`) and DOCX (via `python-docx`, including table cells,
  since many resumes lay out skills/experience in tables), with a
  plain-text fallback for anything else. A scanned-image resume with
  no text layer is rejected with a clear 422 explaining why, rather
  than silently storing an empty resume.
- **One resume per candidate** (`Resume` model) — uploading again
  replaces the previous extraction; this is a working document for
  matching, not a version history.
- **Resume-JD matching** (`app/services/resume_match.py`) — same
  explainable blend as V6 job matching: skill-token overlap (using the
  same `SKILLS` vocabulary as everywhere else) plus TF-IDF text
  similarity between the resume and the job's own text, with the
  breakdown returned so neither number is a black box.
- **Learning roadmap** — phased (immediate/medium-term/long-term)
  suggestions built from the missing-skills list. Deliberately generic
  rather than naming specific courses/providers: a specific course
  recommendation is an opinion this project isn't positioned to stand
  behind, and specific URLs go stale. Where a *link* claim is
  appropriate (an exam's official syllabus/paper actually exists at a
  URL), that's the curated exam-prep path below instead.
- **Exam-prep resources** (`ExamPrepResource` model) — admin-curated
  links (syllabus, previous-year papers, mock tests, cutoffs, study
  material) attached to a job or, more durably, to an
  organization+exam name so they survive past one year's specific
  posting. Deliberately **curated, not generated**: fabricating
  syllabus or previous-year-paper content for a real high-stakes exam
  risks being confidently wrong in a way that could actually hurt
  someone's preparation — this project only ever links to something an
  admin has verified exists.
- **New endpoints:** `POST /resume`, `GET /resume`, `DELETE /resume`,
  `GET /resume-match/{job_id}`, `GET /jobs/{job_id}/exam-prep`
  (public), plus admin `POST/GET/DELETE /admin/exam-prep`.
- **Frontend:** a Resume page (upload, view detected skills, run a
  match, see the roadmap) and an "Exam prep resources" panel on the
  Career AI page.
- **Migration:** `migrations/v8_career_growth.sql` (new `resumes` and
  `exam_prep_resources` tables).
- **Tests:** `tests/test_v8_career_growth.py` — upload → skill
  detection → match → roadmap → delete, rejecting an empty upload,
  requiring a resume before matching, and the admin exam-prep
  create/list/candidate-read flow.

## V9 details — platform (recruiter accounts + admin)

- **Real role-based auth, not the shared key.** `app/core/security.py`
  gained `require_recruiter` alongside the existing `require_admin` —
  both check the logged-in user's JWT-derived `role`, separate from
  the `X-Admin-Key` header the V2/V3/V5 admin endpoints use. A
  candidate can't self-elevate: `POST /auth/register` always creates
  role="candidate"; only `POST /admin/users/{id}/role` (admin-key
  guarded) can grant "recruiter" or "admin" — the same trust boundary
  V3's partner onboarding already established.
- **`Job.owner_user_id`** — set when a recruiter posts a job via
  `POST /recruiter/jobs`; stays `NULL` for everything else (government
  ingestion, admin manual entry, V3 partner submissions). Recruiter
  postings go through `normalize_job` → `publish_to_review` exactly
  like every other source — **a recruiter account does not skip
  review**; an admin still has to publish it.
- **Recruiter API** (`app/api/recruiter.py`): create/list/edit/delete
  their own postings, list applicants for a job they own, and update
  an applicant's pipeline status. Every endpoint re-checks ownership
  (`_owned_job_or_404`) so one recruiter can never see or touch
  another's jobs or applicants — verified in
  `test_recruiter_cannot_see_or_edit_another_recruiters_job`.
- **`Applicant` — deliberately separate from `Application`.** The
  existing `Application` model (V4/V7) is a candidate's private
  tracker of roles they're pursuing anywhere, including free-text
  notes never meant for an employer to see. `Applicant` is the other
  side of a real submission: created only when a candidate calls
  `POST /jobs/{id}/apply` on a CareerOS-hosted (recruiter-owned)
  listing, and only then is a resume snapshot/cover note/contact info
  visible to that job's owner. The two were never merged, to avoid
  accidentally exposing private tracker notes to a recruiter.
- **Resume snapshot, not a live link.** Applying copies the
  candidate's current `Resume.extracted_text` into
  `Applicant.resume_snapshot` at that moment — a later resume edit
  doesn't retroactively change what a recruiter already saw for that
  application.
- **New endpoints:** `POST/GET/PUT/DELETE /recruiter/jobs`,
  `GET /recruiter/jobs/{id}/applicants`,
  `PATCH /recruiter/applicants/{id}`, `GET /recruiter/dashboard`;
  candidate-side `POST/DELETE /jobs/{id}/apply`,
  `GET /my-submissions`; admin-side
  `POST /admin/users/{id}/role`, `GET /admin/users`.
- **Frontend:** a Recruiter dashboard (post a job, see its review
  status, view/manage applicants by pipeline stage) and an "Apply now"
  button on the Jobs page for postings that have a recruiter owner
  (as opposed to `apply_url`-only external listings).
- **Migration:** `migrations/v9_platform.sql` (`jobs.owner_user_id`,
  new `applicants` table).
- **Tests:** `tests/test_v9_platform.py` — role-gate enforcement
  before/after granting the recruiter role, the full post → publish →
  apply → shortlist pipeline, and cross-recruiter ownership isolation.

## V10 details — scale & production hardening

- **CI** (`.github/workflows/ci.yml`) — `ruff` lint + `pytest` on the
  backend, a Next.js build check on the frontend, on every push/PR.
  Not yet actually run against this exact codebase in a live GitHub
  Actions environment (no such environment is available here) — treat
  the first run as a real check, not a formality, and expect it might
  need a small follow-up fix the way any new CI setup does.
- **Pagination everywhere a list could grow unbounded:** `/saved-jobs`,
  `/alerts`, `/admin/review`, `/admin/partners`, `/admin/exam-prep`,
  `/recruiter/jobs`, `/recruiter/jobs/{id}/applicants` all gained
  `limit`/`offset` query params (capped at 200) — these were fine at
  small scale but would eventually return everything in one response.
- **Postgres connection pooling** (`app/db/session.py`) — `pool_size`,
  `max_overflow`, `pool_timeout`, `pool_recycle` are now configurable
  via settings instead of SQLAlchemy's defaults; SQLite (which doesn't
  support these) is left untouched. The docstring on `db_pool_size`
  spells out the real sizing consideration: `pool_size × replica count`
  must stay under the database's own `max_connections`.
- **Migration runner** (`scripts/run_migrations.py`) — applies every
  file in `migrations/` in filename order, idempotently. Previously
  there was only a one-off script hardcoded to a single (confusingly
  named) file. **Renamed** the original scaffold's `v10.sql`/
  `v10_safe_upgrade.sql` to `v1_baseline_schema.sql`/
  `v1_safe_upgrade.sql` — they were the *original* project's baseline
  schema files, named "v10" because the whole starting ZIP was called
  "V10 Integrated Final," which would have collided confusingly with
  this actual, versioned V10.
- **A real bug fixed:** `docker-compose.production.yml` never set
  `ENVIRONMENT=production`, so `/docs` and `/redoc` stayed exposed even
  in the "production" compose file (see the `is_production` check in
  `app/main.py`, added back in the original optimization pass — it was
  never actually wired to fire in this file). Fixed, and the file now
  fails closed with a clear error if `POSTGRES_PASSWORD`, `JWT_SECRET`,
  `ADMIN_API_KEY`, or `FRONTEND_ORIGIN` aren't set, instead of silently
  falling back to `change-me`-style defaults in what's supposed to be
  the production config.
- **Docker hardening:** both backend and frontend containers now run
  as a non-root user; the backend adds a healthcheck against `/health`
  and a configurable `WEB_CONCURRENCY` worker count.
- **Load-test starting point** (`scripts/load_test.py`) — a small
  async script hitting `/jobs` concurrently and reporting p50/p95
  latency. Explicitly a starting point: it has not been run against a
  real deployment as part of this project, since none exists in this
  environment — treat any numbers it produces as a baseline to compare
  future changes against, not a production-capacity claim.
- **`PROJECT_STATUS.md` rewritten** to reflect the actual current state
  across all ten versions instead of the original scaffold's summary,
  which had gone stale after V2–V9's real work this session.

## V11–V15 — authentication, recruiter approval, and government hub

These versions were built in later sessions than the V1–V10 work above
(the other markdown files in the repo root — `FINAL_AUDIT_V13.md`,
`GOVERNMENT_HUB_V14.md`, `GOVERNMENT_COVERAGE_V15.md`,
`INDUSTRY_READINESS.md` — document them in more detail; this section
is a short pointer, not a duplicate).

- **V11 — real authentication.** Email-OTP verification on
  registration (`EmailVerification` table, `app/services/email_service.py`
  over stdlib `smtplib`, degrades to logging the code in
  non-production when SMTP isn't configured), password reset via the
  same OTP mechanism, and a genuine recruiter/candidate account split:
  recruiter registrations are created with `role="recruiter"` but
  `recruiter_status="pending"` until both email verification and admin
  approval (`POST /admin/recruiters/{id}/approve`) — a recruiter
  account can't log in via `/auth/recruiter/login` until both gates
  clear.
- **V12/V13 — production startup guards + security headers.**
  `app/main.py`'s lifespan now refuses to start in production without
  a strong `JWT_SECRET`/`ADMIN_API_KEY`, a real PostgreSQL
  `DATABASE_URL`, and SMTP configuration — and adds baseline
  `Permissions-Policy`/`Content-Security-Policy` headers plus HSTS in
  production.
- **V14 — government recruitment lifecycle.** A `RecruitmentUpdate`
  model attaches result/admit-card/answer-key/syllabus/exam-date/notice
  events to an *existing* recruitment instead of creating duplicate
  job postings for each follow-up notice, plus a public Government Hub
  frontend section (Latest Jobs/Results/Admit Cards/etc.) and a
  recruitment timeline on each government job's detail page.
- **V15 — an expanded, more resilient collector design
  (`SmartOfficialAdapter`)** that scans an official page's links for
  recruitment-relevant keywords instead of depending on brittle
  table-only CSS selectors — a real, worthwhile design improvement.
  **However**, a later review pass (documented just below) found this
  version's own source registry had drifted from the project's
  established honesty policy: four sources were shipped `enabled=True`
  and described as "live validated," and `ingestion_enabled` defaulted
  to `true` — neither claim was backed by an actual live check (no
  session working on this codebase has had internet access to make
  one), and both have been reverted.

## Bug review pass — V15 (this session)

A further review of the V15 zip found:

1. **A false "verified" claim, in two places, with an unsafe default
   attached.** `app/ingestion/sources.py` shipped four government
   collectors (`SmartOfficialAdapter`-based SSC/RRB/IBPS, plus the
   UPSC `HTMLListAdapter`) with `enabled=True` and comments/docs
   calling them "live validated official collectors" — while the
   module's own top-of-file docstring still said "each entry is
   disabled by default" and "nothing here is asserted as verified."
   Worse, `settings.ingestion_enabled` had been flipped from its
   documented `False` default to `True`. Combined, a fresh deployment
   with zero operator action would have started hitting live
   government sites with selectors nobody had actually confirmed
   against today's markup. The identical "verified" claim was
   duplicated in `app/ingestion/source_catalog.py` (`TIER_A`'s
   docstring) and surfaced publicly via `GET /government/coverage`'s
   response text. All four sources reverted to `enabled=False`,
   `ingestion_enabled` reverted to `False`, and both files' language
   corrected to state plainly that these are real implementations that
   have not been independently verified live — matching the
   honesty standard the rest of this project holds throughout.
2. **`docker-compose.production.yml` would have crashed on startup.**
   It set `ENVIRONMENT=production` but never passed `SMTP_HOST`/
   `SMTP_FROM_EMAIL`, which the new V12 startup guard requires in
   production — meaning the exact file shipped for production
   deployment would hit `RuntimeError("Production requires SMTP
   configuration...")` immediately. Fixed: added the required SMTP env
   vars, plus a dedicated `migrate` service (see next point).
2b. **Migrations still weren't actually wired into deployment.** The
   compose file relied solely on `Base.metadata.create_all()` at
   backend startup, which only creates a schema for a brand-new empty
   database — it doesn't add new columns to an existing one. Added a
   `migrate` one-off service with `depends_on: condition:
   service_completed_successfully` on the backend service, so
   `scripts/run_migrations.py` actually runs before the API starts.
   Also upgraded that script with a `schema_migrations` tracking table
   (filename + content checksum) so applied migrations are recorded
   and a since-edited migration file is flagged instead of silently
   ignored.
3. **A fragile test/production coupling.** `email_verified` was
   auto-set to `True` at registration based on whether `"test_careeros.db"`
   appeared as a *substring* of `DATABASE_URL` — a real but fragile
   way to let the existing test suite skip the OTP flow. Replaced with
   an explicit `AUTO_VERIFY_EMAIL_IN_TESTS` setting that only the test
   suite's own environment sets, so a production deployment can never
   end up here through an unlucky naming coincidence.

All fixes are reflected in the code; the corrected files' comments
explain each one in place.

## What this pass fixed (this session)

- Login didn't check `active` status on the user (inactive users could still log in) — fixed.
- Admin API key was compared with `!=`, which leaks timing information — switched to `hmac.compare_digest`.
- `PUT /applications/{id}` didn't validate `job_id` existed (unlike the create endpoint) — fixed for consistency.
- Search/location/category filters didn't escape `%`/`_`, so a search like `50%` behaved as a wildcard instead of literal text — fixed.
- No brute-force protection on `/auth/login` or `/auth/register` — added a lightweight in-memory rate limiter.
- Unhandled exceptions would surface raw tracebacks to the client — added structured exception handlers plus server-side logging.
- No baseline security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) — added.
- `CORSMiddleware` only accepted a single origin — `frontend_origin` now accepts a comma-separated list.
- `/jobs` had no total count for pagination — added an `X-Total-Count` response header (kept the response body as a plain array so the existing frontend doesn't break).
- Manual admin ingestion wasn't recorded in the audit log — fixed.
- Cleaned formatting/imports across the backend for readability (multi-line, docstrings, no unused imports) and tightened the `jobs/page.tsx` frontend page (loading/error states instead of an unhandled fetch).

## Honest next-step priorities

All ten planned versions now have working code behind them. What's left
isn't "build the feature" — it's the operational work only a real
deployment (and a human's judgment call) can actually do:

1. **Enable real V2/V3/V15 sources.** Government/private collection
   frameworks exist (RSS/HTML/SmartOfficialAdapter government
   adapters + scheduler; private Greenhouse/Lever collectors +
   partner submission API), but every listed source ships
   `enabled=False` (four government sources were found shipped
   `enabled=True` with an unverified "live validated" claim during
   this session's review — reverted; see the bug-review section
   above). For government sources, confirm the adapter's selectors or
   link-scanning behavior against today's live markup; for private
   sources, swap in a real company's board token; either way, run once
   via `POST /admin/ingest/run?source=...`, check `/admin/review`, then
   flip `enabled=True`. Separately, onboard real partners via
   `POST /admin/partners` and recruiters via
   `POST /admin/users/{id}/role` (or the new approval flow at
   `POST /admin/recruiters/{id}/approve`) once you have actual
   employers ready.
2. **Deploy with the now-fixed `docker-compose.production.yml`** — it
   previously would have crashed on startup (missing required SMTP env
   vars) and never actually ran `scripts/run_migrations.py` before
   starting the API; both are fixed this session (see above), but
   deploying it for real against actual Postgres/SMTP is still the
   step that would prove it end-to-end.
3. **Actually run the CI pipeline and fix whatever it finds.**
   `.github/workflows/ci.yml` exists but has never executed against
   this codebase in a real GitHub Actions runner — the first push is
   the first real signal on whether `ruff` or `pytest` catch anything.
4. **Point `DATABASE_URL` at a real managed PostgreSQL instance** and
   run `python -m scripts.run_migrations` against it, instead of the
   SQLite default this project has run against throughout development.
5. **Run `scripts/load_test.py` against that real deployment** and use
   the result to size `WEB_CONCURRENCY` (Dockerfile) and
   `db_pool_size`/`db_max_overflow` (settings) for actual expected
   traffic — the current defaults are reasonable starting points, not
   tuned numbers.
6. **Add real observability** — the structured logging is
   stdout-only; a production deployment should ship that to an actual
   log sink and add basic APM/error tracking (e.g. Sentry) before
   relying on this to run unattended.
7. **Extend SMTP delivery from auth emails to V7 job notifications.**
   V11 added real SMTP delivery (`app/services/email_service.py`), but
   only for account verification/password-reset OTPs — V7's
   deadline/admit-card/result/saved-search-alert notifications
   (`app/services/notifications.py`) are still in-app only. Wiring the
   same SMTP path into `_notify_once` (keeping the in-app row as the
   fallback/audit record either way) would close that gap.

No step above is fabricated as "already live" — each is a real, scoped
piece of work that depends on things this project can't do from inside
a codebase: a live server, a real domain, and someone's ongoing
attention. That boundary hasn't moved since V1; V10 just made the
codebase itself as ready as it can be for the day someone does that
deployment work.
