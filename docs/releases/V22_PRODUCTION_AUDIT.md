# V22 Production Audit — CareerOS Application System

Covers V22.1 (Application Tracking Infrastructure), V22.2 (Smart
Dashboard & Kanban), V22.3 (Timeline, Notes & Documents), and V22.4
(AI Application Intelligence & Follow-ups) as one coherent system.
This is the audit itself; see `docs/V22_BUG_REPORT.md` for issues
found and fixed, `docs/V22_RELEASE_CHECKLIST.md` for the item-by-item
PASS/FAIL/NOT VERIFIED checklist, and `docs/V22_RELEASE_NOTES.md` for
a plain-language summary of the whole release.

**Method.** This sandbox has no network egress — `pip install` and
`npm install` both fail with 403 from their registries (re-confirmed
at the start of this pass). No prior V22.x test suite, and none of
V22.5's own additions, could actually be executed here. The audit
below is therefore a *static* one: full-repo syntax compilation, a
model-to-migration-SQL diff, and a manual, evidence-based read of the
actual code at every point this document makes a claim — not a
guess, not an assumption carried over from earlier design docs. Every
"PASS" below reflects something actually checked; anything that would
require execution is marked NOT VERIFIED, per the explicit "no fake
validation" instruction for this release.

## 1. Application architecture (confirmed by reading the code)

One `Application` table (V7, extended by V22.1) is the single
application entity throughout — V22.2's dashboard/Kanban, V22.3's
notes/interviews/tasks/documents/timeline, and V22.4's AI layer all
key off `application_id` and reuse `app.applications.service.
get_application()` for ownership, rather than introducing a second
application concept. Confirmed by reading `app/applications/service.py`
and every module built on top of it (`notes.py`, `interviews.py`,
`tasks.py`, `documents.py`, `timeline.py`, `app/applications/ai/*`) —
each calls the same function, none reimplements ownership checking.

**Lifecycle** (`app/applications/status.py`): `SAVED →
PLANNING_TO_APPLY → APPLIED → ASSESSMENT → INTERVIEW → OFFER →
{ACCEPTED, REJECTED, WITHDRAWN, GHOSTED}`. Every transition is
recorded in the immutable `ApplicationStatusHistory` table (V22.1) —
V22.3's timeline reads this table directly rather than duplicating it
into a second log; V22.4's health engine reads it to compute "days
since last activity." Confirmed by reading `app/applications/ai/
signals.py::_last_activity_at` and `app/applications/timeline.py`.

## 2. Database audit

**Migrations reviewed**: every file under `backend/migrations/`, in
natural-sort order (`scripts/run_migrations.py`'s
`_version_sort_key`), specifically the V22 files:
`v22_1_application_tracking.sql`, `v22_3_application_workspace.sql`,
`v22_4_ai_application_intelligence.sql`. (There is no `v22_2` file —
correct: V22.2 was dashboard/Kanban only, reusing V22.1's tables,
no schema change.)

- Ordering: PASS — natural-sort places v22_1 < v22_3 < v22_4 correctly.
- No duplicate migrations: PASS — each defines distinct tables, no
  filename collision, no re-declaration of an existing table.
- Foreign keys: PASS — every V22.3/V22.4 child table
  (`application_notes/interviews/tasks/documents/events/
  ai_insights`) has `application_id REFERENCES applications(id) ON
  DELETE CASCADE` in both the model and the SQL — verified by an
  automated column-and-cascade diff between `app/models/domain.py`
  and the migration files during this pass (see below).
- Indexes: PASS — every child table indexes `(application_id, <its
  primary time column>)`, matching the model's `Index(...)` /
  `mapped_column(..., index=True)` declarations.
- Model ↔ migration column parity: PASS — a scripted diff (regex-
  extracted model field names vs. migration column names) found zero
  real mismatches for all six V22.3/V22.4 tables. (One false
  positive from the diff script's own comment-handling bug was
  manually verified against the raw file and confirmed spurious —
  see `docs/V22_BUG_REPORT.md` item 4, filed as informational since
  it was a flaw in the audit tooling, not the migration.)
- Historical migrations (V1–V21): untouched — PASS by construction
  (no edits made to any file dated before V22.1).
- Rollback strategy: NOT VERIFIED as "tested" (no down-migrations
  exist in this project for *any* version, V1 included — this is a
  pre-existing, project-wide convention, not something introduced or
  regressed in V22). Documented as a known limitation below.
- Actually applying the migrations against a live PostgreSQL
  instance: NOT VERIFIED — no Postgres instance and no network to
  install `psycopg` in this sandbox.

## 3. Application data integrity

Traced by reading code (not by running it, given the environment
limits above):

- Status change → `ApplicationStatusHistory` row: written inside
  `app/applications/service.py`'s status-change path (V22.1,
  unmodified this release).
- → Timeline: `app/applications/timeline.py::get_timeline()` reads
  that same history table directly (no second write, no duplication).
- → AI health engine: `app/applications/ai/signals.py` reads the
  latest of `ApplicationStatusHistory.changed_at` and
  `ApplicationEvent.occurred_at` for "days since last activity", so a
  status change is reflected in the *next* AI read without any
  explicit sync step.
- → AI cache: `ApplicationSignals.fingerprint()` includes `status`, so
  a status change changes the cache `context_key`, naturally
  invalidating stale AI narrative/follow-up/prep output (verified by
  a dedicated test in `test_v22_4_ai_application_intelligence.py`;
  execution itself is NOT VERIFIED per the environment note above,
  but the test's logic was manually traced against the actual cache
  code and is correct).
- Notes/interviews/tasks/documents each write one `ApplicationEvent`
  row at creation (and, for interviews/tasks, on specific
  transitions) via the shared `app/applications/events.py::
  record_event()` — confirmed a single call site per feature, no
  duplicate/competing event-writing path found.

No orphaned-record risk found: every child table cascades on
`Application` deletion, and nothing in V22.2/V22.3/V22.4 creates a
second Application-like entity.

## 4. API audit

Reviewed `app/api/applications.py`, `application_workspace.py`, and
`application_ai.py` in full.

- Authentication: PASS — every endpoint depends on `current_user`
  (JWT), consistent across all three files.
- Ownership / IDOR: PASS — every endpoint resolves
  `application_id` (and, for notes/interviews/tasks/documents,
  the child id) through `service.get_application()` /
  each module's own `_get_owned()` helper before touching data;
  mismatched ownership is always 404, never a raw DB result. This is
  covered by explicit cross-user tests in both
  `test_v22_3_application_workspace.py` and
  `test_v22_4_ai_application_intelligence.py` (execution NOT
  VERIFIED; logic manually traced and correct).
- Mass assignment: PASS — every write endpoint uses an explicit
  Pydantic model (`NoteIn`, `TaskUpdateIn`, `InterviewIn`, etc.),
  never `**request.json()` or an unvalidated dict; a client cannot
  set a field the schema doesn't declare.
- user_id/application_id trust: PASS — `user_id` always comes from
  the verified JWT (`current_user`), never a request body/query
  param; `application_id` is a URL path param but is always
  re-verified against the authenticated user's own applications
  before use, everywhere.
- Pagination/filtering/sorting: PASS on `GET /applications`
  (`limit`/`offset` bounded 1–200, `status`/`company`/`source`/
  `date_from`/`date_to`/`search` filters, `sort_by`/`sort_dir`).
  Child-resource lists (notes/interviews/tasks/documents on *one*
  application) are intentionally unbounded — reviewed and accepted:
  these are scoped to a single application, where realistic
  cardinality is dozens at most, not the thousands pagination exists
  to protect against. Adding pagination there would be complexity
  without evidence of need (explicitly out of scope per this
  release's "do not prematurely complicate architecture" guardrail).
- SQL injection: PASS — grepped the entire backend for any raw
  string-interpolated SQL (`execute(f"..."`, `.format()` +
  `SELECT`, `%` string SQL); found none. Every query in V22
  (and the rest of the codebase) goes through SQLAlchemy's
  parameterized `select()`/ORM layer.
- Excessive response data: PASS for documents (list/detail never
  include `stored_filename` or a filesystem path — verified by
  reading `_document_out()` and by an explicit test asserting
  `"stored_filename" not in doc`). See section 6 for the full
  document-security audit.
- Error handling / status codes: PASS — 404 for not-found-or-not-
  owned (never 403, which would leak existence), 400/422 for
  validation, 413 for oversized uploads, 429 for rate limiting — all
  consistent across V22.1/V22.3/V22.4.
- OpenAPI documentation: PARTIAL — every V22 endpoint is registered
  under a versioned tag (`V22.1 Application Tracking Infrastructure`,
  `V22.3 Application Timeline, Notes & Documents`, `V22.4 AI
  Application Intelligence & Follow-ups`) and FastAPI auto-generates
  request/response schemas from the Pydantic models used for
  *requests*. Several endpoints return a hand-built `dict` rather
  than a declared `response_model` (e.g. `_note_out`, `_signals_out`
  helpers) — this is the same pattern already used throughout
  V22.1/earlier CareerOS endpoints (not a V22.3/22.4-specific
  regression), so responses are correct at runtime but their exact
  shape isn't machine-documented in the OpenAPI schema. Left as-is
  this release (adding `response_model` to every endpoint across the
  whole API is a real but large, pre-existing-pattern change, not a
  V22 stabilization item — see Known Limitations).

## 5. Security audit

- Path traversal (documents): PASS — `stored_filename` is always a
  fresh `uuid4().hex` + a pre-validated extension; the client's
  `original_filename` is never used to build a filesystem path at
  all (not sanitized — structurally excluded). Re-read
  `app/applications/documents.py` line by line this pass; unchanged
  from V22.3 and still correct.
- MIME/extension validation: PASS — allowlist of 7 extensions and a
  matching content-type allowlist, reusing
  `app.core.uploads.read_upload_limited` (the same helper V17's
  resume upload already used).
- Upload size limits: PASS — enforced while streaming the read (not
  after buffering an unbounded body), capped by
  `APPLICATION_DOCUMENT_MAX_UPLOAD_MB` (10 MB default). **Found and
  fixed this pass**: this setting existed in code since V22.3 but was
  never documented in `backend/.env.example` — see Bug Report item 1.
- Secure file access / download authorization: PASS — download
  endpoint re-resolves ownership on every call via
  `documents.get_document_path()`, never trusts a bare document id.
- Authentication/authorization: PASS (see section 4).
- CSRF: N/A as designed — this API uses bearer-token (JWT) auth, not
  cookie-based sessions, so it is not CSRF-vulnerable in the way a
  cookie-authenticated app would be; this is a pre-existing,
  project-wide design choice (V4/V17), not a V22-specific concern.
- XSS-safe rendering: PASS by construction — the frontend is React,
  which escapes all interpolated text by default; grepped
  `components/applications/workspace/*.tsx` and
  `app/applications/[id]/page.tsx` for `dangerouslySetInnerHTML` —
  none found anywhere in V22's frontend code.
- Safe error messages: PASS — API error responses are FastAPI
  `HTTPException(status, "plain message")` throughout V22; none echo
  a raw exception/stack trace or internal detail to the client.
- Secret handling: PASS — grepped the entire backend for hardcoded
  passwords/API keys/secrets; found none. Production secrets
  (`JWT_SECRET`, `ADMIN_API_KEY`, SMTP credentials, AI provider keys)
  are all environment-variable-only, and
  `docker-compose.production.yml` uses Compose's `${VAR:?message}`
  syntax to hard-fail startup if any required one is missing (see
  section 15).
- Logging privacy: PASS for AI — `app.ai.observability` (used by
  every V22.4 AI call via `completion_service.generate()`) logs only
  token counts, cost estimate, latency, and success/failure; grepped
  it this pass to confirm it never logs prompt or response text.

## 6. Document security (explicit audit, per spec section 6)

| Check | Result |
|---|---|
| Only the owner can access a document | PASS — `_get_owned()` re-checks `application_id` ownership on every list/download/delete call |
| A deleted file cannot be accessed afterward | PASS — `delete_document()` removes the DB row first (inside the same transaction as the response), then best-effort removes the on-disk file; a request for the deleted id 404s from the DB check alone, independent of whether the disk removal succeeded |
| Filenames cannot escape the storage directory | PASS — `stored_filename` is never derived from client input (see section 5) |
| Malicious extensions are rejected | PASS — allowlist, not a blocklist (`.pdf .docx .doc .txt .png .jpg .jpeg` only) |
| Oversized files are rejected | PASS — 413, enforced during the streamed read |
| Unsafe MIME types are handled | PASS — content-type allowlist alongside the extension allowlist |
| Storage paths are not exposed | PASS — verified `_document_out()` never includes `stored_filename` or any path; download is a redirect-free `FileResponse` built server-side |
| Download endpoint is authorized | PASS — same ownership re-check as list/delete |
| **File persistence in production** | **FAIL → FIXED this pass** — see Bug Report item 2: the production Docker Compose file had no volume for the document storage directory, so uploaded files would be lost on every container recreate even though their DB rows survived. Added a named volume; see `docker-compose.production.yml`. |

## 7. AI security & reliability audit

- Prompt/context isolation: PASS — `app/applications/ai/context.py`
  builds a per-application, per-request context; nothing caches or
  carries context across applications or users.
- No cross-user context: PASS — `context.build()` takes one
  `Application` (already ownership-checked) and that application's
  own notes/interview; `career_copilot.context_engine.build(db,
  user_id)` (used for interview-prep's resume summary) takes the
  *same, already-authenticated* `user_id` — never another user's.
- No secret leakage: PASS — grepped `signals.py`/`context.py`/
  `narrative.py`/`followup.py`/`interview_prep.py` for anything
  resembling a password/token/key field; the `Application`/
  `ApplicationInterview` models don't carry such fields at all.
- Bounded context size: PASS — notes capped to 5 items × 500 chars;
  everything else is a handful of scalar fields; the shared
  `completion_service.generate()` also enforces
  `settings.ai_max_context_tokens` underneath, independent of this
  feature.
- Bounded response size: PASS — every `_parse_and_validate()` in
  `narrative.py`/`followup.py`/`interview_prep.py` truncates every
  string/list field to an explicit length/count cap.
- Structured response validation: PASS — every AI call requires the
  actual required field(s) to be present and non-empty; a
  parse/validation failure returns the degraded fallback rather than
  a partially-trusted result.
- Provider timeout handling: PASS — verified `timeout_seconds` is
  threaded through every provider adapter
  (`app/ai/providers/{anthropic,openai,gemini,openrouter}_provider.py`)
  down to the actual HTTP client call in each; V22.4 does not
  override or bypass this — it calls the same `completion_service.
  generate()` every other AI feature uses.
- Provider failure handling: PASS — `AllProvidersFailedError` →
  `CompletionError` → caught in all three V22.4 modules → degraded
  fallback, verified by a dedicated test with the failure path
  mocked (execution NOT VERIFIED; logic traced and correct).
- Malformed response handling: PASS — non-JSON or schema-incomplete
  text → `_parse_and_validate()` returns `None` → degraded fallback
  (same test file, same NOT-VERIFIED-execution caveat).
- Rate/cost controls: PASS — `enforce_rate_limit()` on all three
  AI-calling endpoints (20/60s per client IP, shared
  `application-ai-generate` bucket); the two deterministic endpoints
  never touch the LLM at all.
- Core app resilience: PASS by construction — `signals.py` (health/
  priority/next-action/risks/action-plan) contains zero LLM calls,
  confirmed by reading the file in full; a total AI outage degrades
  only the "AI Analysis"/"Smart Follow-up"/"Interview Preparation"
  cards in the frontend, never the rest of `/applications/[id]`.

## 8. AI data privacy

See `app/applications/ai/context.py`'s own docstring (unchanged this
pass, re-read and confirmed accurate) for the authoritative list.
Summary: the AI context sent per request is exactly — company, job
title, status, deadline, the already-computed deterministic signals,
up to 5 recent notes (capped, moderation-screened, wrapped as
untrusted/non-instruction content), and — for interview prep only —
the target interview's own fields plus a resume/skills *summary*
already computed by Career Copilot (not a full resume re-fetch).
Never included: passwords, hashes, tokens, API credentials, another
user's or another application's data, or internal ids beyond
`application_id` itself. Prompts/responses are never logged (section
5). This was independently re-verified this pass by reading
`context.py`, `narrative.py`, `followup.py`, and `interview_prep.py`
line by line — no field not on this list is referenced anywhere in
building a prompt.

## 9–10. Frontend & Kanban audit

Read (not executed — see Method) `KanbanBoard.tsx`,
`StatusChangeControl.tsx`, and every V22.3/22.4 tab component.

- Kanban optimistic update + rollback: PASS — `moveCard()` snapshots
  `previous = items`, applies the move optimistically, and on any
  API failure calls `onItemsChange(previous)` plus a user-visible
  error message ("it stayed in its previous column") — traced this
  pass and confirmed correct; no code path silently drops a failed
  move.
- Accessible Change Status alternative: PASS — `StatusChangeControl`
  is a standalone, non-drag control used on every card and the
  detail page's Overview tab; Kanban drag/drop is not the only way to
  change status.
- Loading states: PASS — every V22.3/22.4 tab renders `SkeletonLines`
  while its initial fetch is in flight.
- Empty states: PASS — every list-type tab (Notes/Interviews/Tasks/
  Documents/Timeline) has an explicit `.emptystate` block with
  actionable copy, not a blank area.
- Error states: PASS — every fetch/mutation is wrapped in try/catch
  setting a string `error` state rendered via `<p className="error">`
  — see "no `[object Object]`" below.
- No `[object Object]`: PASS — grepped every `catch` block across
  `components/applications/workspace/*.tsx` and
  `app/applications/[id]/page.tsx` (25 total); all 25 use the
  `e.message || "<fallback string>"` pattern, none render a raw
  Error/object into JSX.
- No `dangerouslySetInnerHTML`/XSS risk: PASS (section 5).
- Responsive/mobile: PASS by construction — `.worktabs` has explicit
  mobile overflow-x handling and the underlying `.card`/`.grid2`
  system (pre-existing, V19-era) already targets the project's
  responsive breakpoints; no new fixed-width elements introduced in
  V22.3/22.4.
- Accessibility: PASS — tab buttons use `role="tablist"`/
  `role="tab"`/`aria-selected`; the Modal component
  (`components/common/Modal.tsx`) has `role="dialog"`,
  `aria-modal`, `aria-label`, closes on Escape, and moves focus to
  the panel on open; destructive actions (delete note/interview/
  task/document) all confirm via `window.confirm()` before acting.
- Optimistic-update rollback outside Kanban: reviewed — V22.3/22.4
  tabs (Notes/Interviews/Tasks/Documents/AI) intentionally do NOT do
  optimistic updates; they show a loading/busy state and re-fetch
  on success, which sidesteps the rollback problem entirely for
  those simpler CRUD flows. Kanban is the one place optimism is used
  (drag/drop needs to feel instant), and it's the one place rollback
  was verified above.
- Actual browser rendering / console errors / production build: NOT
  VERIFIED — no network to `npm install`, so nothing could actually
  run in a browser or bundler this pass. A brace-balance sanity
  check was run against every new/changed `.tsx`/`.ts` file (not a
  substitute for `tsc`/`next build`, but catches gross truncation).

## 11–12. Performance & API response audit

- N+1 queries: reviewed every V22.3/22.4 list endpoint — each issues
  one `select()` per resource type per request (e.g. `GET .../
  timeline` issues exactly two queries: status history + events,
  merged in Python) — no per-row query loop found.
- Indexes: see section 2 — present on every child table's
  `(application_id, <time column>)`.
- Oversized responses: documents list/detail never include file
  bytes (metadata only, section 6); AI responses are capped
  string/list lengths (section 7).
- Repeated AI requests: the content-hash cache (section 3) means an
  unchanged application never re-triggers a provider call on repeat
  reads.
- Realistic-dataset load testing: NOT VERIFIED — no running database
  in this sandbox to load-test against.

## 13. Test suite

See `docs/V22_RELEASE_CHECKLIST.md` for the itemized results.
Summary: **NOT VERIFIED for execution** (network-dependent
dependency install unavailable in this sandbox, both for backend
`pytest` and frontend `npm run build`/type-check/lint). What *was*
verified this pass: every backend `.py` file (221 app files + 45 test
files) compiles cleanly (`python -m py_compile`); a scripted model-
to-migration diff found no real mismatches; SQLite's `NULLS LAST`
support (used by `interviews.py`/`tasks.py` ordering) was confirmed
directly against the bundled SQLite 3.45.1; every frontend file
touched by V22.3/22.4 was brace-balance-checked.

## 14. Regression audit

No file outside `app/applications/`, `app/api/application*.py`,
`app/models/domain.py` (additive only), `backend/migrations/`,
`backend/tests/test_v22_*`, the two `docker-compose*.yml` files,
`backend/.env.example`, `backend/app/main.py` (version strings only),
`frontend/package.json`/`package-lock.json` (version strings only),
`frontend/src/lib/application*.ts`,
`frontend/src/components/applications/workspace/*`,
`frontend/src/components/common/Modal.tsx`,
`frontend/src/app/applications/[id]/page.tsx`, `PROJECT_STATUS.md`,
`README.md`, `CHANGELOG.md`, and the `docs/V22_*` files was modified
this pass or any prior V22.x pass. Every other V16–V21 subsystem
(Auth, Candidate, Recruiter, Admin, Jobs, Government Jobs, Saved
Jobs, Resume, AI Resume Intelligence, Career Copilot, Interview
system, Search, Recommendations, Personalization) is therefore
unaffected by construction — confirmed by scoping every edit made
this pass and every prior V22.x pass to the paths above, not by
re-running their test suites, which was not possible in this
sandbox. Their own existing test files (45 total, listed in section
13) all still compile.

## 15. Docker / production audit

- `docker-compose.production.yml` requires PostgreSQL: PASS — the
  `db` service always runs `postgres:17-alpine`; there is no SQLite
  fallback path in this file at all (SQLite is only ever used when
  `DATABASE_URL` is left unset, which this file never does — every
  required variable uses Compose's `${VAR:?message}` hard-fail
  syntax: `POSTGRES_PASSWORD`, `FRONTEND_ORIGIN`, `JWT_SECRET`,
  `ADMIN_API_KEY`, `SMTP_HOST`, `SMTP_FROM_EMAIL`,
  `NEXT_PUBLIC_API_URL`).
- Migrations run as a separate, blocking step before the API starts
  serving traffic: PASS — the `migrate` service runs
  `python -m scripts.run_migrations` and `backend` has `depends_on:
  migrate: condition: service_completed_successfully`.
  Automatically picks up `v22_3`/`v22_4` (natural-sort, no hardcoded
  filename list) — confirmed by reading `run_migrations.py`.
- Health checks: PASS — `db` (`pg_isready`), `backend` (`GET
  /health`), both with sensible intervals/retries.
- Non-root containers: PASS — both Dockerfiles create and switch to
  an unprivileged user.
- `/docs`/`/redoc` disabled in production: PASS — `app/main.py` sets
  `docs_url=None, redoc_url=None` when `settings.is_production`.
- Document storage persistence: **FAIL → FIXED this pass** — see Bug
  Report item 2 and section 6.
- Real container build/boot: NOT VERIFIED — no Docker daemon
  available in this sandbox to actually build/run the images.

## 16. Environment variable audit

`backend/.env.example` reviewed variable-by-variable against
`app/core/config.py`'s actual `Settings` fields.

- **Found and fixed this pass**: `application_document_max_upload_mb`
  and `application_document_storage_dir` (added in V22.3) were never
  added to `.env.example` — see Bug Report item 1. Fixed.
- Every other setting referenced by V22.1/V22.3/V22.4 code
  (`resume_max_upload_mb`-style file-size caps, `AI_*` provider keys,
  `ai_moderation_enabled` via its existing default) was already
  documented or has a safe default requiring no new env var (V22.4
  added no new settings — it reuses the V20.1 `AI_*` block entirely).
- No secrets committed: PASS — every value in `.env.example` is
  either empty, a placeholder string, or a non-sensitive default.
- Dev vs. production defaults: PASS — the file's SQLite
  `DATABASE_URL` default is explicitly commented as a dev-only
  zero-config path, with the Postgres production form shown
  immediately above it.

## 17. Code quality audit

- Debug prints: PASS — none found in any `app/` file (a naive grep
  for `print(` only matched `.fingerprint(` calls — false positive,
  manually confirmed).
- TODO/FIXME/XXX: PASS — none found in `app/`.
- Hardcoded secrets/URLs: PASS — none found (see section 5).
- Unused imports (V22.3/22.4 files specifically): PASS — a scripted
  AST-based check found zero real unused imports across all 15
  new/changed `app/applications/`, `app/applications/ai/`, and
  `app/api/application*.py` files (the only flagged name,
  `annotations`, is the `from __future__ import annotations` line —
  a false positive of the check, not a real unused import).
- Duplicate services/models/routes: PASS — no second `Application`-
  like model, no second timeline/notes/interview/task/document
  system, no route path registered twice (`app/api/routes.py`
  reviewed in full).
- Circular imports: PASS — `app/applications/ai/*` imports from
  `app/applications/service.py` and `app/career_copilot/*`, never the
  reverse; `app/api/application_ai.py` imports from
  `app/applications/ai/*`, never the reverse. No cycle found.
- Re-verified (not newly found) this pass: `app/applications/ai/
  context.py` correctly references `Application.job_title` (an
  earlier draft during V22.4 development referenced a nonexistent
  `Application.role` attribute; that was caught and fixed before the
  V22.4 zip was delivered, so it never shipped — re-confirmed clean
  by re-reading the file this pass, not a new fix).

## 18. API / OpenAPI audit

Every V22.1/V22.3/V22.4 endpoint is registered under a version-
labeled tag and reachable through `app.main.app`'s router; request
bodies are fully schema'd via Pydantic (so OpenAPI request examples
are accurate). Response shapes for several endpoints are hand-built
dicts rather than declared `response_model`s (see section 4) —
functionally correct, but not machine-documented; called out as a
known limitation rather than fixed wholesale this release, since
declaring `response_model` for dozens of pre-existing endpoints
across the whole API (not just V22) is outside "stabilization only."

## Known limitations (carried into the release notes)

1. No down-migrations exist anywhere in this project (V1 onward) —
   rollback is "restore from backup," not "run a reverse migration."
   Pre-existing, not V22-specific.
2. Several endpoints return hand-built dict responses rather than
   declared `response_model`s, so their exact shape isn't in the
   OpenAPI schema even though it's correct at runtime. Pre-existing
   pattern, not fixed wholesale this release.
3. Child-resource lists (notes/interviews/tasks/documents) are
   unbounded per application by design (see section 4) — fine at
   realistic single-application cardinality, would need pagination
   if that assumption ever changes.
4. Nothing in this audit was actually executed against a running
   database, browser, or container — see Method above. All PASS
   results are static/code-review verifications, clearly distinguished
   from execution-based ones throughout this document.
