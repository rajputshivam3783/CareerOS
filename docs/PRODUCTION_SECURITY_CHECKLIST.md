# Production Security Checklist

Markers â€” only `[x]` means *verified with evidence in V25.6*:

* `[x]` verified in V25.6 (evidence named)
* `[~]` implemented in code, **not verified at runtime** â€” verify before go-live
* `[ ]` operator action / deployment item / **NOT VERIFIED**

A green checklist here is not a certification and not a statement that CareerOS is
production-ready. The V25.6 environment could not run the application, so most items are
`[~]` or `[ ]` by design.

## Identity and access
- [~] **Authentication** â€” Argon2id, OTP, lockout, uniform failures. Run `tests/test_v17_1_auth_core.py`, `test_v17_2_security_hardening.py`.
- [~] **Session security** â€” access tokens bound to live sessions; logout/logout-all/force-logout effective immediately. Run the updated `test_v17_3_rbac.py` and `test_v25_6_security_compliance.py::test_logout_*`. Decide on the localStorage token risk (F-22).
- [~] **Authorization** â€” run `test_v17_3_rbac.py`, `test_v25_2_admin_platform_governance.py`.
- [~] **Tenant isolation** â€” run `test_v25_1_multi_tenant_organizations.py` and the V25.6 suspension/removal tests. Manually try Org A â†’ Org B ID swaps on jobs, applicants, notes, analytics, audit log.
- [~] **RBAC** â€” confirm candidate â‰  recruiter, recruiter â‰  org admin, org owner â‰  platform admin with two real accounts each.
- [ ] Named admin accounts exist; then set `ADMIN_KEY_AUTH_ENABLED=false` (retire the shared `X-Admin-Key`).
- [ ] MFA for admin accounts â€” **not implemented**; use network-level controls (VPN/IP allow-list) on `/admin` meanwhile.

## Application security
- [~] **API security** â€” `python backend/scripts/security_route_inventory.py` (476 routes at V25.6; 30 public, reviewed in `API_SECURITY_INVENTORY.md`). Dynamic IDOR/mass-assignment testing not executed.
- [~] **Input validation** â€” script-scheme URLs rejected (API 422 + ORM guard + frontend). Run `test_v25_6_security_compliance.py::test_recruiter_job_rejects_script_urls_*`.
- [~] **File security** â€” magic-byte checks and ownership on download. Test with a real PDF/DOCX/PNG/JPEG/TXT from your users; add malware scanning if recruiters will open candidate files (**not implemented**).
- [~] **AI security** â€” run `test_v25_4_ai_career_agent.py`, `test_v20_6_ai_production_stabilization.py`, V25.6 agent tests; try prompt-injection text in a resume, job description and note against your real provider.
- [~] **Career Agent security** â€” confirm exactly-once, expiry (`CAREER_AGENT_ACTION_TTL_MINUTES`) and honest completion text in the UI.
- [~] **Rate limiting** â€” `test_v16d_rate_limit.py`; confirm limits on login, OTP, reset, registration, partner key, account lifecycle, AI/search under your traffic. Legitimate-flow load test not executed.
- [ ] Reverse proxy sets `X-Forwarded-For`; backend `FORWARDED_ALLOW_IPS` = proxy address only (never `*` with an exposed backend port). Verify a request from two different clients gets different rate-limit buckets.

## Transport and browser
- [ ] **HTTPS/TLS** terminated with modern protocols; HTTP â†’ HTTPS redirect; HSTS observed on real responses (**NOT VERIFIED â€” deployment**).
- [~] **Security headers** â€” check `curl -I` on API and frontend for nosniff, frame protection, Referrer-Policy, Permissions-Policy, CSP, HSTS.
- [ ] **Frontend CSP** â€” leave Report-Only, open key pages (jobs, job detail, login, recruiter, admin, career-ai) with the console open, fix violations, then build with `CSP_ENFORCE=true`.
- [~] **CORS** â€” `FRONTEND_ORIGIN` = exact HTTPS origin(s), no wildcard (start-up refuses it). Test a real preflight from the browser app, including admin and download flows.
- [x] **CSRF** â€” not applicable to bearer-header auth (documented in `SECURITY.md`); reconsider if cookie sessions are added.

## Secrets and configuration
- [x] **Repository secret scan** â€” regex scan of the archive found no real keys/private keys/credentials; `.env` absent; `.env.example` placeholders only. (Git history not available; scan it.)
- [~] **Secrets** â€” production start-up refuses placeholders (unit-tested rules); confirm the real values come from a secret store, are â‰¥ 32/24 random characters, distinct, and rotated per `SECURITY_INCIDENT_RESPONSE.md`.
- [~] `METRICS_TOKEN` set and Prometheus scrapes with a bearer token (otherwise `/metrics` is 403 in production).
- [ ] Development-only settings off in production: `AUTO_VERIFY_EMAIL_IN_TESTS`, `EMAIL_MODE=console`, docs endpoints.

## Data
- [ ] **Database security** â€” TLS to Postgres; not internet-reachable; separate migration and runtime roles (runtime without DDL) â€” currently one role (F-31).
- [ ] **Encryption at rest** for database, uploads volume and backups (**NOT VERIFIED â€” infrastructure**).
- [~] **Data retention** â€” decide periods for hiring records and audit logs (not auto-purged); enable the opt-in purge only after legal sign-off; dry-run `python backend/scripts/retention_purge.py`.
- [~] **Data deletion** â€” run the erasure tests against Postgres **with foreign keys enforced**; test with a candidate who has applications + documents + an applicant record, and with a sole organization owner.
- [ ] **Backup** â€” automated, encrypted, restore rehearsed; note that erased data persists in backups until expiry.
- [ ] **Disaster recovery** â€” RPO/RTO defined and tested.
- [~] **Audit logging** â€” consider DB-level append-only protection (trigger or role without UPDATE/DELETE) on `audit_logs` / `platform_audit_logs` (F-29).

## Operations
- [ ] **Monitoring / alerting** â€” alert on `login_failed` bursts, `refresh_token_reuse_detected`, `cross_tenant_access_attempt`, `privilege_escalation_attempt`, `account_lifecycle_auth_failed`, 5xx rate, `/ready` failures. **No alert routing exists in the repository.**
- [ ] **Incident response** â€” owners named, contact published in `SECURITY.md`, runbook rehearsed once.
- [ ] **Dependency security** â€” `pip-audit`, `npm audit --omit=dev`, container scan run and triaged (**not run in V25.6**); backend lock file with hashes (F-24).
- [ ] **Regression tests** â€” full backend suite, `npm run test:security`, frontend production build, ruff `E,F` all green in CI. (`README` mentions `.github/workflows/ci.yml`; it is not in the provided archive.)
- [ ] **Deployment security** â€” `docker compose -f docker-compose.production.yml config` validates; images built from pinned tags/digests; containers run non-root (Dockerfiles do), `no-new-privileges`, `cap_drop: ALL` applied; only the reverse proxy is public (`BACKEND_BIND`/`FRONTEND_BIND` = 127.0.0.1 when proxied).
- [ ] Load/performance check of authenticated endpoints after the V25.6 per-request session lookup (**not measured**).

