# V25 Final Security & Compliance Audit (V25.6)

**Read this first.** This is an honest report of a *static code audit plus hardening pass*
performed in an environment with **no network access, no application dependencies (FastAPI,
SQLAlchemy, pydantic, pytest, psycopg), no PostgreSQL and no `node_modules`.** Consequently the
application itself was never started, no migration was run, no frontend build was made and no
dynamic security test was executed. Everything marked **NOT VERIFIED** is exactly that: no claim
is made either way. CareerOS holds **no** SOC 2, ISO 27001, GDPR or other certification, and
**no penetration test** (formal or informal) has been performed; §32-style "penetration-style
testing" of the specification could not be carried out beyond code review. This report does not
declare the platform production-ready.

## 1. Executive summary

* **Scope:** entire backend (`backend/app`, ~50k lines, 476 routes), frontend (`frontend/src`),
  Docker/compose, configuration, dependency manifests, existing security docs.
* **Method:** reading the code; an AST-based route inventory; targeted searches (secrets, raw SQL,
  unsafe HTML, generic column dumps, protected-attribute usage); comparing behaviour against the
  existing tests; writing and executing unit tests for the new pure helpers.
* **Result:** 35 findings (F-01…F-35): 3 High, 15 Medium, 13 Low, 4 Informational (some
  Medium/Low items are architectural or deployment items that were documented rather than changed).
  Most were **fixed in code**; the fixes are **unexecuted at application level**. No CRITICAL
  finding was identified by review; that is not the same as "none exist" (no dynamic testing).
* **Highest-impact fixes:** stored XSS through job JSON-LD (F-01); script-scheme URLs (F-02); a
  tenant-isolation gap for suspended/removed members (F-03); access tokens surviving logout/revocation
  (F-04); Career Agent exactly-once confirmation (F-06); recruiter job deletion cascading to
  applicants (F-35).
* **What you must do before trusting V25.6:** run the backend suite, the new integration tests,
  the frontend build, `pip-audit`/`npm audit`, a Postgres migration on a clean database, and a
  browser check of the CSP; then work through `PRODUCTION_SECURITY_CHECKLIST.md`.

## 2. V25 architecture (as audited)

| Phase | What it is | Security-relevant property |
|---|---|---|
| V25.1 Multi-tenancy | `Organization`, `OrganizationMember` (OWNER/ADMIN/RECRUITER, ACTIVE/SUSPENDED/REMOVED/PENDING), single-use invitations, org audit view | org access derived from DB membership; foreign org → 404 |
| V25.2 Governance | platform permissions (`require_platform_permission`), user/org/job lifecycle, `platform_audit_logs`, typed settings, maintenance mode | platform authority is independent of org roles |
| V25.3 Data intelligence | deterministic analytics reusing existing calculations; AI only explains numbers | no new personal-data collection |
| V25.4 Career Agent | fixed tool whitelist, state machine, confirmation for WRITE/HIGH_RISK | LLM never touches the DB |
| V25.5 Scale & reliability | observability, dead-letter table `failed_job_records`, health/readiness | `/metrics` was public (fixed) |
| V25.6 (this) | hardening, account lifecycle, retention, docs | — |

Auth model: bearer-header JWT (15 min) + rotating hashed refresh tokens + `UserSession` rows;
role from the database; platform admin via named admin JWT or the shared `X-Admin-Key`.

## 3. Security findings (prioritised)

Severity is my judgement from code review. "Status" describes the code change; see §15 for what
was and was not executed. Full register with statuses: `VULNERABILITY_MANAGEMENT.md` §5.

### CRITICAL
None identified by review (no dynamic testing was possible).

### HIGH
| ID | Finding | Evidence | Status |
|---|---|---|---|
| F-01 | **Stored XSS.** `jobs/[id]/page.tsx` and `Breadcrumbs.tsx` put `JSON.stringify(...)` into `dangerouslySetInnerHTML`; `<` is not escaped, so a job title/description/organization/location containing `</script><script>…` executes on a public page. Data comes from recruiters, partners and ingestion (review-gated, but the payload is plain text). Tokens in `localStorage` make this an account-takeover path. | code; helper test | FIXED — `safeJsonLd` (escapes `< > & U+2028/9`) |
| F-02 | **Unvalidated URLs rendered as links.** `apply_url`, `official_url`, `notification_url`, `admit_card_url`, `result_url`, company/social URLs were free strings; only application-tracker URLs were validated. 32 frontend `href` sites used them raw. | code | FIXED — API allow-list (422) on recruiter/partner/admin/company/org/register models; ORM deny-list guard on every URL-like column; frontend `safeHref` |
| F-03 | **Tenant-isolation gap.** `suspend_member`/`remove_member` only change `OrganizationMember`; a user who was also the legacy `Organization.owner_user_id` or had a `CompanyTeamMember` row still resolved to the organization in `team_owner_ids` and received all active members' jobs/candidates/pipeline/analytics. | code | FIXED — explicit non-ACTIVE membership now wins. Residual: user's own id always in scope |

### MEDIUM
| ID | Finding | Status |
|---|---|---|
| F-04 | Access tokens carried `sid` but no path checked it: logout (without refresh token), logout-all, force-logout, admin revoke and reset left tokens valid ≤ 15 min; `exp` not a required claim; four separate token decoders | FIXED — `decode_access_token` (exp+sub required) + `access_token_session_is_active` in every guard; logout revokes the caller's own session. **Behaviour change** |
| F-05 | forgot-password had no per-account cooldown (inbox flooding; each request consumed the victim's valid code) | FIXED |
| F-06 | Career Agent `confirm_action` accepted any status not in {COMPLETED, REJECTED, FAILED} (so EXECUTING could re-run), no atomic claim (race → double execution), no expiry | FIXED |
| F-07 | Agent reported "Done — that's been completed" for `submit_application` / `send_recruiter_message`, which only prepare a link/draft | FIXED |
| F-08 | `wrap_untrusted` / `wrap_tool_result` embedded content verbatim; the footer marker inside a resume/job text closed the "data only" block | FIXED (one place, ~25 call sites) |
| F-09 | Production guard accepted `.env.example` secrets (33/36 chars pass length checks), wildcard CORS with credentials, `AUTO_VERIFY_EMAIL_IN_TESTS=true` | FIXED |
| F-10 | Shared `X-Admin-Key`: no identity, three separate guards, no off switch, 500 on non-ASCII header (`compare_digest(str)`) | PARTIAL — switch + bytes-safe compare; still enabled by default |
| F-11 | Maintenance mode bypassed by *any* `X-Admin-Key` value | FIXED |
| F-12 | `/metrics` public; inbound `X-Request-ID` unvalidated (log injection); API CSP allowed `'unsafe-inline'`/`'unsafe-eval'`/`connect-src https:` | FIXED |
| F-13 | Partner API key verifiable with unlimited attempts | FIXED |
| F-14 | No account deactivation / erasure | FIXED (implemented) |
| F-22 | Access + refresh tokens in `localStorage` | ACCEPTED (documented) |
| F-23 | Browser CSP needs `'unsafe-inline'` scripts; shipped Report-Only | PARTIAL |
| F-27 | Members of a platform-suspended organization keep recruiter-side ATS access (`team_owner_ids` ignores `is_active`) | OPEN — product decision; not fully verified |
| F-35 | Any team member could hard-delete a job; `applicants.job_id` is `ON DELETE CASCADE` → all applicant records lost | FIXED — 409 when applicants exist |

### LOW / INFORMATIONAL
F-15 unbounded in-memory rate-limit table and proxy-dependent client IP · F-16 refresh-rotation race ·
F-17 login timing enumeration · F-18 OTP stored as bare SHA-256 · F-19 reuse event never emitted,
V25.5 table missing SQL migration · F-20 no upload content validation, DOCX archive bombs · F-21
stale versions, no root `.gitignore`, no frontend healthcheck · F-24 backend dependencies unpinned/
unaudited · F-25 `/ai/health`, `/notification-template-keys` public · F-26 registration reveals
existing emails · F-28 no signed-in change-password/export · F-29 audit tables not DB-immutable ·
F-30 agent text mentions "reply yes" · F-31 single DB role · F-32 admin key in `sessionStorage` ·
F-33 forgot-password timing · F-34 `X-Total-Count`/`Content-Disposition` not CORS-exposed.

## 4. Vulnerabilities fixed — where

| Change | Files |
|---|---|
| Frontend escaping/URL helpers, 32 links, 2 JSON-LD sites | `frontend/src/lib/safe.ts`, 13 pages/components, `components/Breadcrumbs.tsx`, `app/jobs/[id]/page.tsx` |
| Browser security headers | `frontend/next.config.ts` |
| Hardening primitives | `backend/app/core/hardening.py` (stdlib only), `core/validators.py`, `core/url_guard.py` |
| Token/session binding | `core/security.py`, `core/sessions.py`, `api/admin.py`, `core/rbac.py`, `core/platform_admin.py`, `core/maintenance.py`, `api/auth.py` |
| Tenant scope | `core/team_access.py`, `api/recruiter.py` (delete guard) |
| Career Agent / AI | `career_agent/actions.py`, `career_agent/agent_service.py`, `career_agent/system_prompt.py`, `career_copilot/system_prompt.py` |
| Config / startup / headers / metrics | `main.py`, `core/config.py`, `core/logging.py`, `core/rate_limit.py`, `api/partners.py` |
| Uploads | `core/uploads.py`, `applications/documents.py` |
| Account lifecycle, retention | `core/account_lifecycle.py`, `api/account.py`, `core/retention.py`, `scripts/retention_purge.py`, `core/security_events.py` |
| Deployment | `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.production.yml`, `.gitignore`, `.env.example` files |
| Migration | `backend/migrations/v25_6_security_compliance.sql` (idempotent, non-destructive) |

**Behaviour changes to expect** (each is deliberate): revoked-session tokens → 401 (one existing
test, `test_v17_3_rbac::test_admin_force_logout_…`, previously asserted the opposite and was updated);
OTP codes issued before deploy stop verifying; script/relative URLs → 422 on recruiter/company/
organization/partner/admin inputs; content that does not match an upload's extension → 400;
`/metrics` → 403 in production without `METRICS_TOKEN`; forgot-password within 60 s of the
last code sends nothing (same response); CORS now uses explicit method/header lists; a job with
applicants cannot be deleted (409).

## 5. Remaining risks

Tokens in `localStorage` (F-22) · `'unsafe-inline'` scripts in the browser CSP (F-23) · shared admin
key still on by default (F-10) · F-27/F-03 residuals · no MFA · no malware scanning · no
DB-level audit immutability · one DB role · unpinned backend dependencies and **no advisory scan**
· no alert routing · encryption at rest/backups/DR/TLS are deployment-owned. Also: **the V25.6
code itself is unexecuted at application level and may contain defects** — the largest
unverified pieces are `_delete_where` in `account_lifecycle.py` (generic FK-ordered deletion),
`install_url_guards` (SQLAlchemy listeners) and the atomic UPDATE in `confirm_action`.

## 6. Tenant-isolation verification

| Resource (spec §2) | Isolation mechanism | Evidence in V25.6 |
|---|---|---|
| Organization endpoints (read/patch/invite/members/audit) | `require_organization_membership` → 404 for non-members | [C]; [T] `test_v25_1` (`test_org_a_cannot_*` pattern) — not executed |
| Jobs | `_owned_job_or_404` via `team_owner_ids` | [C]; [T] `test_v9_platform` (B cannot edit/delete A's job → 404); new suspension/removal tests |
| Applicants/pipeline/interviews/offers/notes | `_owned_applicant_or_404` → underlying job ownership | [C] |
| Candidates (discovery) | `candidate_searchable` opt-in; recruiter scope | [C] not deeply reviewed |
| Applications, resumes, documents, notes, tasks | owner-filtered lookups; document files UUID-named, ownership re-checked | [C] sampled; [T] `test_v22_3` IDOR tests |
| Analytics | derived from owner-scoped data (V24.4/V25.3) | [C] not deeply reviewed |
| Notifications | owner check on every read/update | [C] sampled |
| Audit logs | org audit limited to that org's entity id; platform audit admin-only | [C] |
| AI context / Career Agent data | context assembled per requesting user; actions/conversations owner-scoped (`_get_owned`) | [C]; [T] new agent test |

ID-manipulation cases (`GET /organizations/B/...`, `PATCH organization_id=B`, POST with foreign
ids) were **reviewed in code, not executed**. No dynamic cross-tenant test result exists for V25.6.

## 7. RBAC verification

| Separation | Mechanism | Status |
|---|---|---|
| Candidate ≠ Recruiter | `require_recruiter` checks DB role + approval; candidate endpoints ownership-scoped | [C] |
| Recruiter ≠ Org Admin | org endpoints need `OrganizationMember` role ADMIN/OWNER; RECRUITER cannot invite/manage (existing test) | [C][T] |
| Org Admin ≠ Org Owner | `can_manage_role`: ADMIN cannot grant/edit OWNER; last owner protected | [C][T] |
| Org Owner/Admin ≠ Platform Admin | `/admin/*` uses `guard` / `require_platform_permission` on `User.role`, never on membership | [C][T] `test_org_owner_cannot_suspend_users_or_organizations` |
| Platform Admin has no org backdoor | org endpoints require membership even for admins | [C][T] `test_platform_admin_has_no_implicit_backdoor_into_org_endpoints` |
| Role/permission from client | request models exclude privileged fields; roles change only via admin endpoints | [C] |

Privilege-escalation attempts were not executed dynamically in V25.6.

## 8. AI security verification

* Prompt-injection: all untrusted text is wrapped; delimiter breakout **fixed** and unit-tested
  (`neutralize_prompt_delimiters`, 3 tests). No adversarial prompt was run against a real model.
* Tool authorisation/validation: fixed whitelist; parameters validated by the registry; the
  handler runs only after confirmation for WRITE/HIGH_RISK. **Confirmation now exactly-once and
  expiring** ([T]).
* Ownership: actions/conversations fetched with `user_id` (`_get_owned`) [C][T].
* Unauthorised external actions: none exist — the two HIGH_RISK tools only prepare a link/draft
  and now say so.
* Output validation, timeouts, token limits, provider fallbacks: V20.x/V20.6 (`docs/AI_SECURITY_AUDIT.md`), reviewed at declaration level only.
* Recruiter AI: prompt forbids protected characteristics and hiring decisions; regex output guard
  withholds violations (coarse safety net).
* Responsible AI: no route in the inventory auto-rejects, auto-advances or auto-hires; status
  changes are recruiter-initiated. Sensitive profile fields are read only by the eligibility
  engine. Not tested for bias.

## 9. Privacy controls

Data map and minimisation notes: `DATA_RETENTION_AND_DELETION.md` §1. Key points: optional
sensitive profile fields used only for the candidate's own eligibility check; OTP values never
persisted; AI usage logs contain no prompt text; resumes stored as extracted text only;
redacting log filter as a backstop; account erasure (§10). **Gaps:** no data export; no
consent/notice review; DPAs with providers unknown.

## 10. Data retention and deletion

Policy table, opt-in purge, deactivation vs erasure semantics, and organization lifecycle are in
`DATA_RETENTION_AND_DELETION.md`. Erasure keeps the anonymised `users` row (cascades would otherwise
destroy organization hiring records), removes personal data, scrubs applicant content, ends
memberships, keeps audit rows with the identity replaced, and refuses when the user is a sole
organization owner. **Never executed against a database.**

## 11. Dependency audit

| Ecosystem | Declared | Audit result |
|---|---|---|
| Python (`requirements.txt`) | fastapi ≥0.115<1, uvicorn ≥0.34<1, pydantic ≥2.10<3, sqlalchemy ≥2.0<3, psycopg ≥3.2<4, httpx ≥0.28<1, PyJWT ≥2.10<3, pwdlib[argon2] ≥0.2<1, python-multipart ≥0.0.20<1, pypdf ≥5<7, python-docx ≥1.1<2, openpyxl ≥3.1<4, apscheduler ≥3.10<4, scikit-learn ≥1.5<2, numpy ≥1.26<3, anthropic ≥0.40<1, redis ≥5<6, **pytest ≥8<9 (in runtime file)** | **NOT VERIFIED** — no network, so no advisory database lookup; ranges without a lock file or hashes; installed versions unknown |
| npm (`package-lock.json`, 99 packages) | next 16.2.11, react/react-dom 19.2.4, typescript 5.9.3 (+ Tailwind 4, `@types/*`) | **NOT VERIFIED** — `npm audit` not run; **no ESLint configured** (no `lint` script) |
| Images | `python:3.13-slim`, `node:22-alpine`, `postgres:17-alpine`, `redis:7-alpine` | **NOT VERIFIED** — not built/scanned; tags not digest-pinned |

Vulnerabilities found: none *known* — because none could be looked up. Upgrades made: none.
Deferred: everything, pending the scans in `VULNERABILITY_MANAGEMENT.md` §1/§4.

## 12. Infrastructure security

Backend container already ran non-root; V25.6 adds `PYTHONDONTWRITEBYTECODE/UNBUFFERED`, documents
`FORWARDED_ALLOW_IPS`, adds `no-new-privileges` + `cap_drop: ALL` to backend and frontend,
frontend `HEALTHCHECK`, configurable bind addresses, `CSP_ENFORCE` build arg. The database is not
published; production compose fails closed on missing secrets. YAML parses; images were **not
built**; the migration `entrypoint` behaviour was not altered. **NOT VERIFIED:** TLS, network
policy, secrets store, DB encryption/roles, backups, DR (all deployment-owned).

## 13. Compliance readiness

Controls, evidence and gaps are in `SECURITY_CONTROL_MATRIX.md` (access control, data
minimisation, audit logging, encryption, retention, incident response, secure development,
vendor/provider management). No certification is claimed. Principal gaps: MFA, evidence of controls
operating over time, vendor agreements, backup/DR, alert routing, dependency assurance, DB-enforced
audit immutability.

## 14. Performance regression

**Not measured. No numbers are reported because none were obtained.** Analysis only: the one
change on the hot path is a primary-key lookup of `UserSession` per authenticated request (plus a
row-lock on refresh, an extra `SELECT` in `team_owner_ids` only for users with a legacy row in an
excluded org, a bounded rate-limiter prune, and a regex log filter that runs only on emitted log
lines). Argon2 timing equalisation adds one dummy verification **only on failed logins for unknown
emails**. Measure `auth/me`, search, applications, recruiter pipeline, analytics, admin and Career Agent
before/after in a staging environment; if the extra lookup matters, `ACCESS_TOKEN_SESSION_CHECK=false`
restores the old behaviour (at the cost of F-04).

## 15. Regression and test results

### Executed in V25.6
| Check | Result |
|---|---|
| `python backend/tests/run_pure_tests.py` (tests/test_v25_6_hardening_unit.py) | **90 passed, 0 failed** |
| `node --experimental-strip-types frontend/scripts/safe.test.mjs` (`npm run test:security`) | **passed** (JSON-LD escaping round-trip; 12 hostile URL forms rejected) |
| `python -m py_compile` on every changed/new Python file | passed |
| Import smoke with third-party packages stubbed (all `app.*` modules) | 250 modules import; the 26 failures are stub artefacts and are **identical to the unmodified V25.5 baseline (244 ok)** |
| `scripts/static_name_check.py` on changed files (undefined names / unused imports) | clean except an unused import already in V25.5 |
| `scripts/security_route_inventory.py` | 476 routes: ADMIN 152, AUTHENTICATED 210, RECRUITER 65, ORG-SCOPED 15, OPTIONAL-AUTH 4, PUBLIC 30 |
| `docker-compose.production.yml` YAML parse | passed |

### NOT executed (NOT VERIFIED)
Backend suites V1–V25.5 and `tests/test_v25_6_security_compliance.py` · database migrations
(clean DB and upgrade) · frontend production build, type-check and
lint (no lint configured) · OpenAPI generation/validation (two routes added: `POST /account/deactivate`,
`POST /account/delete`; URL fields now 422) · dependency audits · performance tests · Docker builds ·
CSP in a browser · every dynamic security test (IDOR, privilege escalation, tenant escape,
authentication bypass, session, XSS, SQLi, path traversal, redirects, SSRF, upload attacks, API abuse,
prompt/tool injection, confirmation bypass). **No security test result other than the unit and frontend
tests above exists for V25.6.**

## 16. NOT VERIFIED — consolidated list

Application behaviour of every V25.6 change (see §5 for the riskiest three) · full regression ·
migrations on a clean/upgraded PostgreSQL · frontend build · dependency vulnerabilities (backend,
frontend, images) · performance · tenant-isolation and RBAC dynamic tests · AI adversarial tests ·
file-upload attack tests · TLS/HSTS in deployment · database/volume/backup encryption · backup and
restore · DR · alert routing · vendor agreements · CI pipeline (README references
`.github/workflows/ci.yml`, not present in the archive) · the frontend CSP in a browser · whether
`Organization.is_active` should gate recruiter data access (F-27) · response-field review of public
job/company endpoints.

## 17. Production recommendations

1. Run the full backend suite and `tests/test_v25_6_security_compliance.py` on Postgres and SQLite;
   fix what fails (expect some tests to need small adjustments — they were written blind).
2. Run `_delete_where`/erasure against Postgres with FKs enforced, with a candidate that has every
   kind of data; confirm hiring records survive and no orphan rows remain.
3. `pip-audit`, `npm audit --omit=dev`, container scan; add a backend lock file with hashes.
4. Build the frontend; exercise key pages with the CSP Report-Only console open; then
   `CSP_ENFORCE=true`.
5. Create named admin accounts, then `ADMIN_KEY_AUTH_ENABLED=false`; put `/admin` behind
   network controls; add MFA when feasible.
6. Configure `FORWARDED_ALLOW_IPS`, `METRICS_TOKEN`, TLS, encrypted database/volumes/backups; rehearse
   restore.
7. Decide (product/legal): hiring-record and audit-log retention, IP retention after erasure, F-27,
   personal-data export.
8. Consider DB-enforced audit immutability, least-privilege DB roles, upload malware scanning,
   and (longer term) HttpOnly-cookie sessions with CSRF protection and a nonce-based CSP.
9. Commission an independent penetration test before handling real candidate data at scale.
10. Wire alert routing for the security events listed in the checklist; publish a security contact.
