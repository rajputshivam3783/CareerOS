# V22 Bug Report

Only real issues found during the V22.5 stabilization audit are
listed below, each with severity, component, description, fix, and
verification status. See `docs/V22_PRODUCTION_AUDIT.md` for the full
audit this report was produced from.

---

## Issue 1 — Undocumented environment variables for document storage

- **Severity**: Low (operational/documentation gap, not a security or
  correctness defect — the settings had safe defaults and worked
  correctly; they just weren't discoverable in `.env.example`)
- **Component**: V22.3 Application Documents, `backend/.env.example`
- **Description**: `app/core/config.py` has carried
  `application_document_max_upload_mb` and
  `application_document_storage_dir` since V22.3, but
  `backend/.env.example` was never updated to document them —
  someone configuring a new deployment from the example file alone
  would have no way to discover or override the document upload size
  cap or storage location.
- **Reproduction**: `grep application_document backend/.env.example`
  returned nothing prior to this fix, despite both settings being
  live and in use since V22.3.
- **Fix**: Added both variables to `backend/.env.example`, with a
  comment explaining the storage-location security model (matching
  the pattern every other documented setting in that file already
  follows).
- **Verification status**: PASS (visually confirmed the lines are now
  present and match the actual `Settings` field names/defaults in
  `app/core/config.py`) — not covered by an automated test, since
  `.env.example` completeness isn't something the test suite checks.

---

## Issue 2 — Application documents not persisted across container recreation in production

- **Severity**: High (data loss risk in the default production
  deployment path)
- **Component**: V22.3 Application Documents, `docker-compose.
  production.yml`
- **Description**: V22.3's document storage writes raw file bytes to
  `settings.application_document_storage_dir`
  (`var/uploads/application_documents`, relative to the backend
  container's `/app` working directory). This was the first feature
  in the project to write files to local disk (the earlier V17
  resume-upload feature stores extracted *text* in the database, not
  raw files, so there was no existing precedent/volume for this).
  `docker-compose.production.yml`'s `backend` service had no volume
  mounted for that path, so the directory lived on the container's
  writable layer — every container recreate (redeploy, image update,
  `docker compose up --build`, etc.) would silently lose every
  previously uploaded document, while its `ApplicationDocument`
  database row would survive untouched. The practical symptom: a
  candidate's previously-successful document download would start
  404ing (`DocumentNotFoundError` — see
  `app/applications/documents.py::get_document_path`'s
  `path.is_file()` check) after any redeploy, with nothing in the API
  response indicating why.
- **Reproduction** (traced, not executed — no Docker daemon in this
  sandbox): read `docker-compose.production.yml`'s `backend` service
  definition; no `volumes:` key existed for it prior to this fix,
  while `db` already had one (`careeros_pg`) for exactly this reason
  (Postgres data persistence).
- **Fix**: Added a named volume, `careeros_app_documents`, mounted at
  `/app/var/uploads/application_documents` on the `backend` service,
  declared under the file's top-level `volumes:` alongside the
  existing `careeros_pg`/`careeros_redis` volumes.
- **Verification status**: NOT VERIFIED by actually running Docker
  (no daemon available in this sandbox) — the fix is a one-line,
  standard Compose volume declaration, and its correctness was
  confirmed by comparing it against the existing `careeros_pg` volume
  pattern already proven to work for Postgres in this same file, but
  "the container survives a recreate with the file intact" was not
  actually exercised end-to-end.

---

## Issue 3 — Stale version metadata across the project

- **Severity**: Low (cosmetic/informational — did not affect
  functionality, but violated the "final version consistency"
  requirement for this release)
- **Component**: `backend/app/main.py`, `frontend/package.json`,
  `frontend/package-lock.json`, `PROJECT_STATUS.md`
- **Description**: The FastAPI app's OpenAPI `version`, and the
  version strings returned by `GET /` and `GET /health`, were all
  hardcoded to `"16.0.0"` — stale since V16, never updated through
  V17–V22.4 despite many releases landing in between.
  `frontend/package.json` and its lockfile were similarly stuck at
  `"12.0.0"`. `PROJECT_STATUS.md`'s opening line still said "This
  build spans V1 through V22.1", not mentioning V22.2–V22.4 at all.
- **Reproduction**: `grep -rn '"16.0.0"\|"12.0.0"'` across the repo
  returned hits in all four locations prior to this fix.
- **Fix**: Bumped all four to `22.5.0` (backend `app/main.py`'s three
  occurrences, `frontend/package.json`, both `version` fields in
  `frontend/package-lock.json`), and updated `PROJECT_STATUS.md`'s
  opening paragraph to reference V22.5 and point to `CHANGELOG.md`/
  `docs/V22_RELEASE_NOTES.md` for everything from V22.2 onward,
  matching how `README.md` already handles versions from V16 on.
- **Verification status**: PASS (grepped the whole repo again after
  the fix; zero remaining `"16.0.0"`/`"12.0.0"` matches anywhere).

---

## Issue 4 — Audit tooling false positive (informational only, not a real defect)

- **Severity**: Informational (no code changed; noting this for
  transparency about the audit process itself)
- **Component**: N/A — a bug in this pass's own ad-hoc audit script,
  not in the application
- **Description**: A quick Python script written during this audit to
  diff `ApplicationAIInsight`'s SQLAlchemy model fields against
  `v22_4_ai_application_intelligence.sql`'s columns initially
  reported `context_key`, `provider`, and `content_json` as "only in
  model, missing from SQL." Manual inspection of the raw migration
  file showed all three columns are present and correct — the
  script's own line-splitting logic (splitting on `",\n"`) broke on
  lines with an inline SQL comment after the comma (e.g. `context_key
  VARCHAR(64) NOT NULL,   -- content hash...`), merging several
  column definitions into one "line" and only capturing the first
  token of the merged blob.
- **Reproduction**: re-run the diff script described in
  `docs/V22_PRODUCTION_AUDIT.md` section 2 against
  `v22_4_ai_application_intelligence.sql`.
- **Fix**: N/A — no application code was wrong; the migration file
  was correct as originally written. Documented here only so this
  audit's own false-positive doesn't get mistaken for an unresolved
  schema defect by a future reader.
- **Verification status**: PASS (manually confirmed via `cat -A` on
  the raw migration file that all three columns are present with
  correct types/constraints).

---

## Not a bug, noted for transparency

During this pass's code-quality review, `app/applications/ai/
context.py` was re-read line by line as part of the circular-import
and attribute-access checks. It correctly references
`Application.job_title`. An earlier draft of this same file, written
during V22.4's own development, briefly referenced a nonexistent
`Application.role` attribute; that mistake was caught and corrected
by the author before the V22.4 deliverable was ever produced, so it
never shipped in any delivered zip and is not a defect in the
released V22.4 code. It's mentioned here only in the interest of a
complete, honest record of the codebase's history, per this release's
"no fake validation" requirement — not because it's an open issue.

---

## Summary

Four items found this pass: one Low (docs gap, fixed), one High (data
persistence, fixed), one Low (version metadata, fixed), one
informational (audit-tooling artifact, no code change needed). No
other confirmed unresolved defects were found during the performed
audit (see `docs/V22_PRODUCTION_AUDIT.md` for the full scope of what
was and wasn't checked, and its Method section for why execution-
based checks are marked NOT VERIFIED rather than PASS).
