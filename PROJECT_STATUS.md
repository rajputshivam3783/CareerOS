# CareerOS implementation status

This build spans V1 through V22.5 (Application System Production
Stabilization — the final V22 release). For what was built in each
version and why specific design choices were made (especially around
what's deliberately *not* auto-generated or auto-published), see
[ROADMAP.md](./ROADMAP.md) — this file is a quick summary; ROADMAP.md
is the source of truth. Full original per-version write-ups live in
[`docs/archive/`](./docs/archive/). The version table below was last
updated through V22.1; V22.2 onward (dashboard/Kanban, timeline/notes/
documents, AI intelligence, and this production-stabilization pass)
are documented in [`CHANGELOG.md`](./CHANGELOG.md) and
[`docs/V22_RELEASE_NOTES.md`](./docs/V22_RELEASE_NOTES.md) instead of
here, matching how README.md already handles everything from V16 on.

| Version | Status | Summary |
|---|---|---|
| V1 | Done | FastAPI + Next.js platform, SQLite (zero-config) or PostgreSQL, search/filter, core opportunity system |
| V2 | Built, sources disabled by default | RSS + configurable HTML government-site collectors, a scheduler, admin on-demand trigger — every listed source ships disabled until its selectors are verified against the live site |
| V3 | Built | Private/internship/apprenticeship fields, a partner submission API for employers/aggregators, real public-API collectors for Greenhouse/Lever-hosted boards |
| V4 | Done | JWT auth, profile, saved jobs |
| V5 | Built | Qualification + age-limit + indicative reservation-category relaxation eligibility engine, heuristic notification-PDF parsing |
| V6 | Built | TF-IDF semantic search, blended (skill + text-similarity) match scoring, Career AI narrative summary (optional LLM, deterministic fallback) |
| V7 | Built | Application tracker, exam-lifecycle fields (admit card/result), idempotent in-app notification scan (deadlines/admit-cards/results/saved-search alerts) |
| V8 | Built | PDF/DOCX resume upload + skill detection, resume-JD matching, phased learning roadmap, admin-curated exam-prep resources |
| V9 | Built | Admin-granted recruiter role, recruiter job posting (review-gated, same as every other source), candidate apply flow, applicant pipeline |
| V10 | Built | CI pipeline, paginated list endpoints, Postgres connection-pool sizing, a migration runner, hardened production Docker Compose (fails closed on missing secrets, non-root containers, healthchecks), a load-test starting script |
| V16 | Built | Backend hardening (per-actor audit trail, dual-mode admin auth, rate-limited admin key, request-ID middleware, `/live` + `/metrics`, an RBAC permission layer not yet wired into routes); recruiter ATS (required reject reasons, private applicant notes, interview scheduling, offer letters); government hub expansion (5 new post-result lifecycle stages, 3 new category-filtered opportunity sections, 8 new unverified ingestion sources, bulk manual ingest); DevOps (real optional Redis-backed rate limiting, CI Docker-build job) — see `CHANGELOG_V16.md` |
| V17.1 | Built | Enterprise Authentication Core — role-scoped registration/login for all four roles, refresh-token rotation with reuse detection, multi-device sessions, hashed OTPs, password history/confirmation/minimum length — see `AUTH_CORE.md`, `CHANGELOG_V17_1.md` |
| V17.2 | Built | Enterprise Security Hardening — account lockout (progressive delay + escalating temporary lock + admin permanent lock/unlock), OTP max-attempts + resend cooldown, session idle/absolute timeout, admin security endpoints (locked accounts, failed logins, session list/revoke), stricter rate-limit buckets for admin login and profile updates, a centralized security-event taxonomy with a real (unused by default) SIEM/webhook extension point — see `docs/archive/CHANGELOG_V17_2.md`, `SECURITY_ARCHITECTURE.md` |
| V17.3 | Built | Enterprise RBAC — 22 granular permissions across roles, 4 new enterprise roles, system-wide session visibility for admins, account suspension distinct from lockout/deactivation, audit-log export — see `RBAC_ARCHITECTURE.md`, `docs/archive/RELEASE_NOTES_V17_3.md` |
| V18.1 | Built | Company module — extends the pre-existing `organizations` table into a full ATS company profile, plus branch offices |
| V18.2 | Built | Recruiter ATS — job wizard, draft/clone/archive lifecycle, Kanban applicant pipeline stage |
| V18.3 | Built | Recruiter candidate detail view, applicant CSV export, recruiter analytics (built entirely on existing Applicant/Interview/OfferLetter/Resume data, no new tables) |
| V18.4 | Built | Team management — recruiters as company team members, backfilled "owner" row for pre-existing companies |
| V18.5 | Built | Recruiter email templates — per-company editable copies of the 5 ATS notification templates |
| V18.6 | Built | Team-shared job/applicant access — teammates on the same company can see/manage jobs a colleague created |
| V18.7 | Built | Applicants Excel (.xlsx) export alongside the existing CSV export |
| V19.1 | Built | Government Recruitment Core — structured organization catalog, advertisement number/answer key fields, 12 additional lifecycle stages, source registry, stronger duplicate detection, government-scoped moderation queue — see `GOVERNMENT_CORE_ARCHITECTURE.md` |
| V19.2 | Built | Official Source Adapter Framework — sources become config-driven, runnable/monitorable (health %, latency, circuit breaker) rows rather than bespoke per-org scraper classes — see `SOURCE_ADAPTER_ARCHITECTURE.md` |
| V19.3 | Built | Government Portal — 16 dedicated section pages, advanced search, redesigned landing/detail pages, built entirely on the V19.1/V19.2 pipeline; Auth, Security, ATS, AI, Notifications, Analytics, Deployment, Docker explicitly untouched |
| V19.4 | Built | Government Automation & Notification Engine — subscriptions (organization/exam/category/qualification/state/level), 20 lifecycle-event triggers, in-app + email delivery, admin-editable templates, reminder rules, per-user notification preferences/digest, delivery log + admin retry — see `NOTIFICATION_ENGINE.md`, `AUTOMATION_ENGINE.md`, `REMINDER_SYSTEM.md` |
| V19.5 | Stabilization pass | No new features. Removed 3 dead imports (`backend/app/services/automation.py`, `backend/app/api/admin.py`); archived 25 version-dated docs to `docs/archive/`; consolidated root documentation. See `TEST_REPORT.md` for exactly what was verified and how, and its limitations. |
| V20.1 | Built | AI Infrastructure & LLM Framework — provider-agnostic abstraction, centralized AI services, usage observability. See `CHANGELOG_V20_1.md`. |
| V20.2 | Built | AI Resume Intelligence — deterministic resume scoring, explainable job matching/skill-gap, grounded generative suggestions with deterministic fallback. See `CHANGELOG_V20_2.md`. |
| V20.3 | Built | AI Career Copilot — chat-based career guidance grounded in real profile/resume/application/job data; deterministic recommendations/eligibility, only chat calls the AI Gateway. See `CHANGELOG_V20_3.md`. |
| V20.4 | Built | AI Interview & Mock Interview System — structured sessions, deterministic scoring, generative question/feedback support. See `CHANGELOG_V20_4.md`. |
| V20.5 | Built | AI Learning & Skill Intelligence — skill-gap analysis, phased learning roadmap. See `CHANGELOG_V20_5.md`. |
| V20.6 | Stabilization pass | AI Production Stabilization & Final V20 Release — no new features, no architecture redesign. See `CHANGELOG_V20_6.md`. |
| V21.1 | Built | Unified Search Infrastructure — centralized Search Service, no other system touched. See `CHANGELOG_V21_1.md`. |
| V21.2 | Built | Advanced Job Search & Discovery — built on V21.1, no new search engine or duplicated model. See `CHANGELOG_V21_2.md`. |
| V21.3 | Built | AI Job Recommendation Engine — "Jobs For You", deterministic and explainable, no new search/skill-gap engine. See `CHANGELOG_V21_3.md`. |
| V21.4 | Built | Advanced Personalization & Intelligent Ranking — behavioral signals, time decay, configurable weights, A/B testing foundation, personalization controls. See `CHANGELOG_V21_4.md`. |
| V21.5 | Stabilization pass | Search & Recommendation Production Release — final stabilization across V21.1-V21.4, no new features. See `CHANGELOG_V21_5.md`. |
| V22.1 | Built | Application Tracking Infrastructure — production-grade candidate application tracker (CareerOS + external jobs), canonical status lifecycle, immutable status history, "Track Application"/"Mark as Applied", dashboard stats. Extends the existing V7 `Application` model in place — no second application table. See `docs/V22_1_APPLICATION_TRACKING.md`, `CHANGELOG_V22_1.md`, `TEST_REPORT_V22_1.md`. |

## What's deliberately not claimed as done

- **Live automated scraping of specific government/private sites** —
  the collection *framework* exists (V2/V3), but no source ships
  pre-verified against today's live markup; that verification has to
  happen at enable-time, by a human, every time (see
  `backend/app/ingestion/sources.py`).
- **AI-generated exam content** — syllabus/previous-year papers/mock
  tests are admin-curated links (V8), never generated, since being
  confidently wrong about a real high-stakes exam could hurt someone's
  preparation.
- **Email/SMS delivery** — V7 notifications are still in-app only.
  V16 added real SMTP-backed transactional email (`app.services.
  email_service.send_email`) used for OTP plus applicant
  status-change/interview/offer notifications — but it requires SMTP
  to actually be configured in production (it raises rather than
  silently no-op'ing if it isn't); there's still no SMS, WhatsApp, or
  push channel anywhere in this project.
- **Full RBAC coverage** — V16 added a permission-based layer
  (`app.core.rbac`) alongside the existing role checks, but only the
  role checks are actually wired into routes today; migrating routes
  onto permissions is future work, not something this pass claims is
  done everywhere.
- **Scholarship/internship/fellowship sections have no write path
  yet** — V16 added `Job.category`-filtered government hub sections
  for these, and the read side works, but there's no admin API to set
  a job's category after creation, so nothing can populate them
  through the API today. See `docs/archive/GOVERNMENT_HUB_V16.md`.
- **Production hosting, DNS/TLS, and cloud observability accounts** —
  out of scope for a codebase; the Docker Compose files and `.env.example`
  files document what a real deployment needs to set.
- **A verified load-test result** — `scripts/load_test.py` is a
  starting point to run against a real deployment, not a benchmark
  this project has actually executed.
- **V19.5's own tests/build were not executed** — this stabilization
  pass ran in an environment with no network access, so `pytest` and
  the Next.js production build could not actually be run (dependencies
  aren't installed and can't be fetched). What was verified instead —
  full compile/parse checks, route cross-referencing, migration/model
  diffing — is listed precisely in `TEST_REPORT.md`. Run the real test
  suite and build in an environment with dependencies installed before
  treating this as deployable.

## Applying schema changes to PostgreSQL

SQLite (the zero-config default) creates its schema automatically from
the models on every app startup. For PostgreSQL, run:

```
cd backend
python -m scripts.run_migrations
```

This applies every file in `migrations/` in order; all of them are
written to be safe to re-run.

## Hardened build addendum
This build adds recruiter post-publication re-review, bounded document uploads, safer deduplication, centralized frontend API-error formatting, and production migration-on-start. See `TEST_REPORT.md` for executed checks and remaining operational limitations.

## V25.6 — Enterprise Security & Compliance (status)

| Item | Status |
|---|---|
| Security audit of the whole platform | Done as a **static code audit**; 35 findings recorded (F-01…F-35) in `docs/VULNERABILITY_MANAGEMENT.md` |
| Fixes for findings | Written; helper logic unit-tested and executed, application wiring **not executed** |
| Account deactivation / erasure, retention purge | Written; **not executed** against a database |
| Security docs | `docs/SECURITY.md`, `SECURITY_INCIDENT_RESPONSE.md`, `SECURITY_CONTROL_MATRIX.md`, `PRODUCTION_SECURITY_CHECKLIST.md`, `VULNERABILITY_MANAGEMENT.md`, `DATA_RETENTION_AND_DELETION.md`, `API_SECURITY_INVENTORY.md`, `V25_FINAL_SECURITY_AND_COMPLIANCE_AUDIT.md` |
| Full regression V1–V25.5, migrations, builds, lint, dependency audit, performance | **NOT VERIFIED** — run them before treating V25 as released |
| Certification / penetration test | **None** performed or claimed |

