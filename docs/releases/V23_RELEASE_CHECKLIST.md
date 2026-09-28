# V23.5 — Release Checklist

Every item is PASS only after actual validation in this environment.
NOT VERIFIED means the check genuinely could not be performed here
(no external dependency available) — never a guess presented as PASS.

## Backend tests

| Area | Result |
|---|---|
| Full backend suite, run per-file in isolation (the only methodology proven reliable — see bug report's Known Limitations item 4) | **PASS** — 49/49 files, 711/711 tests |
| Notifications (creation/retrieval/unread/mark read/unread/mark-all/pagination/filtering/category/priority) | **PASS** — 14/14 |
| Events (application/interview/job-alert/deadline/AI/system -> notification) | **PASS** (within test_v23_1 + test_v22_* suites) |
| Preferences | **PASS** |
| Email templates (13 templates, escaping, required-variable validation) | **PASS** — 14/14 |
| Email queue / retries | **PASS** |
| Job alerts (CRUD/matching/threshold/preview/history) | **PASS** — 37/37 |
| Matching / deduplication | **PASS** |
| Reminders (interview/deadline/task) | **PASS** — 17/17 |
| Daily digest | **PASS** |
| Timezone | **PASS** (scope: quiet-hours only — see production audit section 12) |
| Quiet hours | **PASS** |
| Communication center | **PASS** |
| Authorization / IDOR | **PASS** — live-tested across every Communication Center + Job Alerts endpoint |
| Concurrency (simulated same-process races) | **PASS** |
| Concurrency (real multi-process/multi-machine workers) | **NOT VERIFIED** — no such environment available |
| Failure recovery | **PASS** — deactivated-owner and broken-alert scenarios both verified isolated, non-crashing |
| Full regression (V16-V23.4) | **PASS** — see Regression section below |

## Frontend

| Check | Result |
|---|---|
| Type checking (`tsc --noEmit`) | **PASS** |
| Production build (`next build`) | **PASS** — 57/57 routes |
| Linting | **NOT VERIFIED** — no lint script or config exists in this project |
| Configured tests | **NOT VERIFIED** — no test framework (jest/vitest/etc.) exists in this project; no test files present |
| Browser console errors | **NOT VERIFIED** — no real browser available in this environment |
| Accessibility / keyboard navigation | **NOT VERIFIED** — no browser/automated a11y tooling available |
| Responsive/mobile usability | **NOT VERIFIED** — same reason |

## Database

| Check | Result |
|---|---|
| Clean create from empty DB (SQLite dev/test path, `create_all()`) | **PASS** (after BUG-1's fix) |
| Migration files parse into valid statements | **PASS** (via project's own `_split_statements` helper) |
| Migration execution against live Postgres | **NOT VERIFIED** — no Postgres server available in this environment |
| Foreign keys / cascade / orphan prevention | **PASS** — reviewed and confirmed correct for all V23.3/V23.4 tables |
| Uniqueness/idempotency constraints under concurrent insert | **PASS** — simulated races confirmed correct |
| `EXPLAIN`-based query plan analysis | **NOT VERIFIED** — SQLite's query planner differs materially from production Postgres; index presence was verified by schema read instead (see production audit section 23) |

## API / OpenAPI

| Check | Result |
|---|---|
| `GET /openapi.json` returns valid schema | **PASS** |
| All V23.3/V23.4 paths present in schema | **PASS** |
| Request validation (422 on bad input) | **PASS** |
| Ownership enforcement (404, not 403, on not-owned) | **PASS** |
| Rate limiting on expensive/abuse-prone endpoints | **PASS** (after BUG-5's fix) |

## Security

| Check | Result |
|---|---|
| IDOR across Communication Center + Job Alerts APIs | **PASS** — live-tested |
| Email header injection | **PASS** — empirically confirmed rejected by the stdlib `EmailMessage` class in use |
| Email recipient source (server-derived only) | **PASS** — every call site audited |
| Action URL / open-redirect / SSRF via action URLs | **PASS** — allowlist + no server-side fetch of stored URLs |
| Template/HTML injection | **PASS** — variable escaping confirmed via test |
| SQL injection | **PASS** — no raw string-interpolated SQL found in any V23.1-V23.4 code |
| Mass assignment | **PASS** — explicit pydantic schemas on every write endpoint |
| Secrets in repository | **PASS** — `.env.example` contains only placeholder/example values; no real credentials found in any tracked file |
| Rate limiting on alert execution endpoints | **PASS** (after BUG-5's fix) |
| Sensitive data in logs (passwords/tokens/OTP codes) | **PASS** — reviewed logging call sites in the audited subsystems; none log a raw secret |

## Docker / production configuration

| Check | Result |
|---|---|
| Backend Dockerfile | **PASS** — reviewed; non-root user, documented `WEB_CONCURRENCY` scheduler-safety constraint |
| Frontend Dockerfile | **PASS** — reviewed, standard Next.js production build |
| `docker-compose.production.yml` | **PASS** — reviewed; health checks present, migration-before-start ordering, no hardcoded secrets |
| Migration-on-startup | **PASS** — `docker-entrypoint.sh` runs `scripts.run_migrations` when `ENVIRONMENT=production` |
| `.env.example` completeness | **PASS** (after this release's fix — added the previously-undocumented `JOB_ALERTS_INTERVAL_MINUTES`, `COMMUNICATION_REMINDER_INTERVAL_MINUTES`, `COMMUNICATION_DIGEST_INTERVAL_MINUTES`) |
| Actual container build/run | **NOT VERIFIED** — no Docker daemon available in this environment |

## Documentation

| Check | Result |
|---|---|
| `docs/V23_PRODUCTION_AUDIT.md` | **PASS** — created |
| `docs/V23_RELEASE_CHECKLIST.md` | **PASS** — this document |
| `docs/V23_BUG_REPORT.md` | **PASS** — created |
| `docs/V23_RELEASE_NOTES.md` | **PASS** — created |
| README / CHANGELOG updated | **PASS** |

## Regression (V16-V23.4 major functionality, per spec section 25)

All run as part of the 49-file/711-test isolated full-suite pass
above. Explicitly named systems and their test files:

| System | Result |
|---|---|
| Authentication | **PASS** |
| Candidate | **PASS** |
| Recruiter | **PASS** (`test_v16b_recruiter_ats.py`, incl. BUG-3's fix) |
| Admin | **PASS** |
| Jobs / Government Jobs | **PASS** |
| Saved Jobs | **PASS** |
| Resume / AI Resume Intelligence | **PASS** |
| Career Copilot | **PASS** |
| Interview | **PASS** |
| Search | **PASS** |
| Recommendations | **PASS** |
| Personalization | **PASS** |
| Application Tracking / Dashboard / Kanban / Timeline / Notes / Documents / Tasks | **PASS** (`test_v22_1`, `test_v22_3`) |
| AI Application Intelligence | **PASS** (`test_v22_4`, incl. BUG-4's fix) |
| Notifications | **PASS** (incl. BUG-2's fix) |
| Email | **PASS** (incl. 2 test-ordering fixes) |
| Smart Job Alerts | **PASS** (incl. BUG-5's fix) |
| Communication Center | **PASS** (incl. 2 test fixes) |
| Reminders | **PASS** |

No regression found in any of the above.
