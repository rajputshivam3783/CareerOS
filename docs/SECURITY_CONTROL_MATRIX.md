# Security Control Matrix â€” compliance **readiness**, not certification

CareerOS holds **no** SOC 2, ISO 27001, GDPR or other certification or attestation, and no
independent penetration test has been performed. This matrix maps engineering controls to
where they live in the code and how well each is evidenced. Use it as input to your own
compliance program, not as a claim about it.

## How to read the Status column

| Status | Meaning here |
|---|---|
| **IMPLEMENTED** | the control exists in code, was inspected in V25.6, **and** has automated tests (existing suites or V25.6 unit tests). "Existing suites" were run in earlier phases per their reports and were **not re-run in V25.6**, because the environment had no application dependencies. |
| **PARTIAL** | the control exists but a material part is missing, changed in V25.6 without a runtime test having been executed, or depends on operator action. |
| **NOT VERIFIED** | depends on deployment/infrastructure or something that could not be checked here. No claim is made either way. |
| **NOT APPLICABLE** | the control does not apply to this architecture (reason given). |

Evidence tags: **[C]** code inspected in V25.6 Â· **[U]** unit test *executed* in V25.6
(`tests/test_v25_6_hardening_unit.py` 90 pass, `npm run test:security`) Â· **[T]** test exists
but was **not executed** in V25.6 Â· **[R]** prior-phase report says passed (not re-verified) Â·
**[S]** static analysis executed in V25.6 (compile, stub-import, route inventory).

## Matrix

| Control | Implementation | Evidence | Status | Notes |
|---|---|---|---|---|
| Authentication | register/login (candidate, recruiter, admin), email OTP, password reset, progressive lockout, uniform failures, timing equalised | [C] `app/api/auth.py`, `core/otp_security.py`, `core/account_lockout.py`; [T] `test_v17_1_auth_core`, `test_v17_2_security_hardening`; [R] | IMPLEMENTED | V25.6 changes (HMAC OTP hash, reset cooldown, timing) are [T]-only. No MFA at login (see gaps). |
| Password security | Argon2id (`pwdlib`), strength policy, history, common-password rejection | [C] `core/security.py`, `core/password_policy.py`; [T] v17.x | IMPLEMENTED | no signed-in change-password endpoint (F-28). |
| Session security | 15-min access JWT (`exp`,`sub` required), hashed rotating refresh tokens, reuse detection + event, idle/absolute timeouts, per-request session-revocation check | [C] `core/security.py`, `core/sessions.py`; [T] v17.x + updated `test_v17_3_rbac`, `test_v25_6_security_compliance` | PARTIAL | revocation check and row lock are new in V25.6 and unexecuted; tokens live in `localStorage` (F-22). |
| Authorization / RBAC | platform roles + permissions, org roles OWNER/ADMIN/RECRUITER, permission dual guard | [C]; [T] `test_v17_3_rbac`, `test_v25_1`, `test_v25_2`; [R] | IMPLEMENTED | Ownerâ‰ Adminâ‰ Recruiter, Org roles â‰  platform admin: see audit Â§7. Privilege-escalation tests not re-run. |
| Tenant isolation | membership-derived org access (404 on foreign org), `team_owner_ids` scope, owner-filtered lookups | [C]; [T] `test_v25_1` cross-tenant tests, V25.6 suspension/removal tests | PARTIAL | V25.6 fix for suspended/removed members unexecuted; residuals F-03/F-27; no dynamic cross-tenant test executed in V25.6. |
| Object-level authorization (IDOR) | ownership checks + 404 | [C] ~15 lookups sampled; [T] `test_v22_3` (IDOR across child resources) | PARTIAL | sampled, not exhaustive over 476 routes. |
| API route inventory | AST inventory, public-route review, guard test | [S] `scripts/security_route_inventory.py`; `docs/API_SECURITY_INVENTORY.md` | IMPLEMENTED | static: proves a dependency is declared, not that it is correct. |
| Input validation (URLs) | `validate_http_url` allow-list at API (422), deny-list ORM guard, frontend `safeHref` | [U] validators + scheme deny-list + `safe.ts`; [T] endpoint/ORM tests | PARTIAL | wiring into 8 request models and the ORM listener unexecuted. |
| SQL injection | SQLAlchemy expressions/parameters; only raw SQL is a constant `SELECT 1` health probe (grep of `text(`/`execute(`) | [C][S] | IMPLEMENTED | migrations are trusted SQL files. No injection fuzzing executed (NOT VERIFIED dynamically). |
| XSS (frontend) | React escaping; the two `dangerouslySetInnerHTML` sites now use `safeJsonLd`; `safeHref`; CSP report-only | [U] `safe.ts`; [C] | PARTIAL | pages not rendered/built here; CSP needs `'unsafe-inline'`; tokens in `localStorage` amplify XSS. |
| CSRF | bearer-header auth, no ambient cookies | [C] | NOT APPLICABLE | revisit if cookie sessions are ever added. |
| File security | size/extension/MIME allow-lists, magic bytes, DOCX bomb/traversal checks, UUID storage, ownership on download, attachment + nosniff | [U] signatures/zip checks; [C]; [T] `test_v22_3`, V25.6 upload tests | PARTIAL | no malware scanning; wiring unexecuted; unauthorised-download test unexecuted. |
| Encryption in transit | HSTS header in production; TLS termination by proxy | [C] headers | NOT VERIFIED | deployment infrastructure. |
| Encryption at rest | none in the application layer | â€” | NOT VERIFIED | database, volume and backup encryption are deployment-owned. |
| Secret management | env-only secrets; `.env` ignored; placeholder-refusing production guard; log redaction filter | [U] guard rules + redaction; [C] repo regex scan (no real secrets found) | PARTIAL | production secret provisioning/rotation NOT VERIFIED; git history was not available to scan. |
| Security headers | API: nosniff, frame deny, referrer, permissions, CSP `default-src 'none'`, HSTS(prod); Next: same family, CSP report-only | [U] header builder; [C] `main.py`, `next.config.ts` | PARTIAL | not observed on a live response; frontend CSP unverified in a browser. |
| CORS | explicit origins from config, wildcards refused in production, explicit methods/headers | [U] rule; [C] | PARTIAL | not exercised with a real preflight. |
| Rate limiting | per-IP limiter (memory or Redis) on auth, admin key, OTP, partner key (new), account lifecycle (new); bounded memory | [C]; [T] `test_v16d_rate_limit` | PARTIAL | correct client IP requires `FORWARDED_ALLOW_IPS`; AI/search/analytics limiter coverage not re-audited; legitimate-flow test unexecuted. |
| Audit logging | actor/time/action/target/request id/IP for platform and org events | [C]; [T] `test_v16_hardening`, `test_v25_2` | PARTIAL | not DB-immutable (F-29); IP retained after erasure by policy. |
| Security monitoring | security-event taxonomy + admin views; reuse event now emitted | [C] | PARTIAL | no alert routing configured (NOT VERIFIED). |
| Data minimisation / privacy | sensitive profile fields optional and used only by eligibility; no protected-attribute use elsewhere (code search); AI usage logs hold no prompt text | [C] | PARTIAL | privacy notice/consent UX not reviewed. |
| Data retention | documented policy; opt-in configurable purge for 4 low-risk categories | [C] `core/retention.py`; [T] retention test | PARTIAL | purge never executed; hiring records/audit logs intentionally not auto-purged (operator decision). |
| Data deletion | deactivation vs erasure, in-place anonymisation, sole-owner guard, job-with-applicants guard | [C]; [T] | PARTIAL | never executed against a database; no export; backups/third parties out of scope. |
| Incident response | runbook for 8 scenarios | `docs/SECURITY_INCIDENT_RESPONSE.md` | PARTIAL | not rehearsed; no external reporting obligations defined. |
| Dependency security | ranges (backend), lockfile (frontend) | [C] declared versions only | NOT VERIFIED | no advisory scan possible offline; backend not locked/hashed (F-24). |
| Vulnerability management | process + register | `docs/VULNERABILITY_MANAGEMENT.md` | PARTIAL | process documented, not yet operating. |
| AI security (prompt injection) | untrusted-content wrapping with delimiter neutralising; whitelisted tools; output guards; timeouts/limits from V20.6 | [U] neutraliser; [C]; [R] `docs/AI_SECURITY_AUDIT.md` | PARTIAL | no adversarial prompts executed against a live model in V25.6. |
| Career Agent security | ownership-scoped actions, explicit confirmation, atomic exactly-once, expiry, honest completion text | [C]; [T] `test_v25_4`, V25.6 agent tests | PARTIAL | V25.6 changes unexecuted. |
| Responsible AI | no auto-reject/hire; recruiter-AI output filter; protected attributes not used | [C] | PARTIAL | filter is a coarse regex safety net, not a fairness guarantee; no bias testing executed. |
| Container / Docker | non-root users, no-new-privileges, cap_drop ALL, healthchecks, DB not published, proxy-aware env | [C]; YAML parsed | PARTIAL | images not built or scanned; base tags not digest-pinned. |
| Database security | ORM parameterisation, migrations idempotent, no destructive migration | [C] | PARTIAL | one DB role for app and migrations (F-31); TLS to DB and least privilege NOT VERIFIED; migrations not run on a clean DB. |
| Secure development | route-inventory guard, unit + integration security tests, lint config (ruff E,F) | [C]; [S] | PARTIAL | `README` references `.github/workflows/ci.yml` but no workflow is in the provided archive (NOT VERIFIED). |
| Backup / recovery | none in the repository | â€” | NOT VERIFIED | deployment-owned; restore never tested. |
| Disaster recovery | none in the repository | â€” | NOT VERIFIED | |
| Vendor / provider management | email (SMTP) and LLM provider are configurable; no DPAs or reviews recorded | â€” | NOT VERIFIED | operator responsibility. |

## Known gaps (controls that do not exist)

Multi-factor authentication at login Â· malware scanning of uploads Â· personal-data export Â·
signed-in change-password Â· database-enforced audit immutability Â· least-privilege database
roles Â· alert routing Â· httpOnly-cookie sessions Â· nonce-based CSP Â· dependency lock with hashes
for the backend.

## Reading this against common frameworks

The matrix supports *readiness conversations* about access control, data minimisation, audit
logging, encryption, retention, incident response, secure development and vendor management.
A framework assessment needs evidence of controls **operating over time** (reviews, tickets,
logs, training, vendor contracts) that no repository can provide.

