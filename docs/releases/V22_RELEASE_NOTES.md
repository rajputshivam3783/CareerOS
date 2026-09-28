# CareerOS V22 Release Notes

**Application System — complete release, V22.1 through V22.5.**

This release turns CareerOS's application tracker from a single
status-tracked list into a full candidate workspace with AI-assisted
guidance, then hardens the whole thing for production. Five
sub-releases, summarized here; each has its own detailed doc linked
below.

---

## V22.1 — Application Tracking Infrastructure

The foundation everything else in V22 builds on: a canonical
application lifecycle (`SAVED → PLANNING_TO_APPLY → APPLIED →
ASSESSMENT → INTERVIEW → OFFER → {ACCEPTED, REJECTED, WITHDRAWN,
GHOSTED}`), an immutable `ApplicationStatusHistory` audit trail,
"Track Application"/"Mark as Applied" actions, and dashboard
statistics. Extends the existing V7 `Application` model in place —
no second application table was ever created, in this release or any
that followed it. See `docs/V22_1_APPLICATION_TRACKING.md`.

## V22.2 — Smart Application Dashboard & Kanban

A visual home for the tracker: dashboard stats, a Kanban board with
drag-and-drop status changes (optimistic UI with rollback on
failure), an accessible non-drag "Change Status" alternative, upcoming
deadlines, and recent activity. No new tables — reuses V22.1's
`Application`/`ApplicationStatusHistory` entirely.

## V22.3 — Application Timeline, Notes & Documents

Turned each application into a full workspace: private notes,
interview-round tracking, application-specific tasks/follow-ups,
secure document storage, and a unified timeline. Five new tables, all
additive, all owned through the same ownership check V22.1 already
established. Documents are stored under a server-generated UUID
filename — never the uploader's original filename — so a client can
never influence where a file lands on disk. See
`docs/V22_3_APPLICATION_WORKSPACE.md`.

## V22.4 — AI Application Intelligence & Follow-ups

Layered AI-assisted guidance on top, built on the existing V20.1 AI
Gateway (no second AI framework introduced): a deterministic (zero-
LLM) health/priority/next-action/risk/action-plan engine, plus three
AI-assisted features — narrative analysis, follow-up email drafts,
and interview preparation suggestions — that explain and extend the
deterministic numbers without ever being allowed to override them.
Every AI call degrades gracefully on provider failure, timeout, or a
malformed response; the core application workspace never depends on
AI succeeding. Nothing in this feature sends an email, changes an
application's status, or deletes anything on its own. See
`docs/V22_4_AI_APPLICATION_INTELLIGENCE.md`.

## V22.5 — Production Stabilization (this release)

A full audit of V22.1–V22.4 as one coherent system — database,
API/security, AI reliability, document security, frontend, Docker/
production configuration, environment variables, and code quality —
plus fixes for what it found. See `docs/V22_PRODUCTION_AUDIT.md` for
the full audit and `docs/V22_BUG_REPORT.md` for what was found and
fixed:

- **Fixed**: uploaded application documents had no persistent storage
  volume in the production Docker Compose file, so they'd be lost on
  every container redeploy. Added a named volume.
- **Fixed**: two V22.3 environment variables
  (`APPLICATION_DOCUMENT_MAX_UPLOAD_MB`,
  `APPLICATION_DOCUMENT_STORAGE_DIR`) were live in code since V22.3
  but never documented in `.env.example`.
- **Fixed**: version metadata (FastAPI app version, `package.json`,
  `package-lock.json`) had been stuck at `16.0.0`/`12.0.0` since well
  before V22 started; bumped to `22.5.0` everywhere, and
  `PROJECT_STATUS.md` updated to stop saying "V1 through V22.1."
- Everything else audited — database schema/migrations, API
  ownership/IDOR/mass-assignment, document security, AI context
  isolation and failure handling, Kanban optimistic-update rollback,
  frontend error handling — checked out clean; see the audit and
  checklist docs for the full, itemized results.
- No new features were added in V22.5, per its own stabilization-only
  scope.

**Honest caveat**: this release's environment had no network egress,
so no test suite or build could actually be executed — every result
above is either a static code check (full-repo syntax compilation,
manual line-by-line review, a scripted model-to-migration diff) or is
explicitly marked NOT VERIFIED. See `docs/V22_RELEASE_CHECKLIST.md`
for the itemized PASS/FAIL/NOT VERIFIED breakdown, and run the full
backend/frontend test and build suites in an environment with
dependency access before treating this as deployment-verified.

---

## What a candidate can do with V22, end to end

1. Save or apply to a job; track it through every stage on a list or
   Kanban board.
2. Open any application to see its full workspace: overview, AI
   insights, timeline, notes, interviews, documents, tasks.
3. See a deterministic health score and priority, and a plain-
   language AI explanation of what they mean.
4. Get a next-best-action suggestion and, when appropriate, an
   AI-drafted (never auto-sent) follow-up email they can edit.
5. Get AI interview-preparation suggestions for a scheduled interview
   — clearly labeled as suggestions, never guaranteed questions.
6. See a prioritized action plan and add any item to their tasks with
   one click.
7. Upload and securely manage application documents (resume, cover
   letter, offer letter, ...).

All of it behind the same authentication and per-application
ownership check established in V22.1, all built on infrastructure
this release reused rather than duplicated (the AI Gateway, the
upload-validation helper, the rate limiter, the moderation service),
and none of it able to take an irreversible action — send an email,
change a status, delete a record — without the candidate doing it
themselves.
