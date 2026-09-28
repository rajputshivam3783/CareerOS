# CareerOS Security Policy & Secure-Development Guide

> **Status language.** This document says what the code does. It does not claim any
> certification (SOC 2, ISO 27001, GDPR or otherwise) and it does not claim a penetration
> test took place. Where something depends on your deployment, or could not be verified in
> the V25.6 environment, it is marked **NOT VERIFIED**. The evidence and gaps live in
> [`V25_FINAL_SECURITY_AND_COMPLIANCE_AUDIT.md`](./V25_FINAL_SECURITY_AND_COMPLIANCE_AUDIT.md)
> and [`SECURITY_CONTROL_MATRIX.md`](./SECURITY_CONTROL_MATRIX.md).

## 1. Reporting a vulnerability

Email the maintainers privately (do **not** open a public issue) with: affected route or
file, reproduction steps, impact, and any proof-of-concept. Expect an acknowledgement and a
severity classification per [`VULNERABILITY_MANAGEMENT.md`](./VULNERABILITY_MANAGEMENT.md).
Operators: publish your own monitored security contact here before going live
(**NOT VERIFIED** â€” no contact address is configured in this repository).

## 2. Authentication

| Topic | Behaviour | Code |
|---|---|---|
| Password hashing | Argon2id via `pwdlib` | `app/core/security.py` |
| Password policy | strength check, history, common-password rejection | `app/core/password_policy.py` |
| Access token | HS256 JWT, 15-minute default, `exp` and `sub` **required**, carries `sid` | `decode_access_token` |
| Refresh token | 384-bit random, stored only as a hash, rotated on every use, reuse revokes the whole session and emits `refresh_token_reuse_detected`, row-locked during rotation | `app/core/sessions.py` |
| Session binding | every authenticated request checks the token's `sid` session is not revoked â€” logout, logout-all, force-logout, admin revoke and password reset take effect immediately | `access_token_session_is_active` |
| Email OTP | 6 digits, HMAC-SHA256 keyed with the server secret, 10-minute expiry, single use, 5 wrong attempts invalidate it, resend cooldown | `app/core/otp_security.py`, `app/api/auth.py` |
| Password reset | OTP-based, single use, per-account cooldown, revokes all sessions on success | `app/api/auth.py` |
| Lockout | progressive account lockout on repeated failures | `app/core/account_lockout.py` |
| Enumeration | login and forgot-password return uniform responses; unknown-email login burns an Argon2 verification so timing matches. Registration still answers 409 for an existing email (accepted trade-off, F-26). | `app/api/auth.py` |

Never logged: passwords, OTP values (the OTP is passed to the mail provider only and never
persisted â€” `EmailMessage.variables_json` stores a redacted variable set), tokens, secrets.
A redacting log filter (V25.6, `app/core/hardening.py::RedactingFilter`) masks bearer
tokens, JWT-shaped strings, `password=`/`token=`/`otp=`-style pairs, provider API keys and
credentials inside URLs as a backstop. **Development only:** `EMAIL_MODE=console` prints
the rendered email â€” including the OTP â€” to the log; production start-up refuses that mode.

**Browser storage of tokens.** The frontend keeps the access and refresh tokens in
`localStorage` (F-22). That is readable by any script that runs on the page, so an XSS bug
becomes an account takeover. V25.6 did **not** move to HttpOnly cookies because that would
introduce a second session system (explicitly out of scope) and change every API client.
Mitigations shipped: the XSS bugs found (F-01/F-02) are fixed, a CSP is shipped (report-only
until enforced), and access tokens are short-lived and now revocable. Treat this as an
accepted, documented risk until a cookie-based design is scheduled.

**CSRF.** Not applicable in the current design: authentication is an `Authorization: Bearer`
header set by JavaScript, never an ambient cookie, so a cross-site request cannot carry
credentials. If cookies are ever introduced for sessions, add SameSite=Lax/Strict, Secure,
HttpOnly and a CSRF token *at that time*. No redundant CSRF mechanism was added.

## 3. Authorization and tenant isolation

* **Roles.** `candidate`, `recruiter`, `admin`, `super_admin` (platform); per-organization
  `OWNER`, `ADMIN`, `RECRUITER` (`OrganizationMember`). The two systems are derived from
  different tables by different modules and never grant each other anything.
* **Organization membership is read from the database, never from the request.**
  `require_organization_membership` (`app/core/organizations.py`) returns 404 (not 403) for
  an organization the caller does not belong to.
* **Recruiter data scope** is `team_owner_ids` (`app/core/team_access.py`). V25.6: an
  organization in which the caller is SUSPENDED/REMOVED is never used, even if a legacy
  `owner_user_id`/`CompanyTeamMember` row still points at it.
* **Object-level checks.** Owned resources are loaded through ownership-filtered helpers
  and return 404 on mismatch (applications, documents, notes, tasks, interviews, plans,
  notifications, AI conversations, Career Agent actions). ~15 lookups were spot-checked in
  the V25.6 audit; the inventory is in [`API_SECURITY_INVENTORY.md`](./API_SECURITY_INVENTORY.md).
* **Never trust the client** for `organization_id`, `user_id`, `owner_id`, `role`,
  `permission`, `status`: request models do not accept them for privileged fields (the
  V24.1 profile model deliberately excludes `email`/`role`), and role changes go through
  admin-only endpoints.
* **Platform admin â‰  organization owner.** Enforced by separate dependencies
  (`guard`/`require_platform_permission` vs `require_organization_*`).
* **Admin credentials.** Named admin accounts (JWT) or the shared break-glass `X-Admin-Key`.
  The shared key has no per-person identity; set `ADMIN_KEY_AUTH_ENABLED=false` in
  production once named admin accounts exist (V25.6 switch, default `true` for backward
  compatibility). All three admin guards honour the switch.

## 4. Secure coding rules for contributors

1. Every new route declares its authentication dependency. Run
   `python backend/scripts/security_route_inventory.py`; a new `PUBLIC` route needs a review
   note in `API_SECURITY_INVENTORY.md`.
2. Load owned objects with the owner id in the query, or check ownership immediately after
   `db.get`. Return 404, not 403, for other tenants' objects.
3. Never build SQL from strings. Use SQLAlchemy expressions/parameters (the code base has no
   raw-SQL execution outside migrations).
4. Every URL a user, partner or scraper can supply is validated with
   `app.core.validators.http_url_validator` (API input â†’ 422). A last-line ORM guard
   (`app/core/url_guard.py`) nulls `javascript:`/`data:`/`vbscript:`/`file:`/`blob:` values
   on any URL-like column. The browser app refuses non-http(s) hrefs (`frontend/src/lib/safe.ts`).
5. Never put user-controlled text into `dangerouslySetInnerHTML`. The two JSON-LD sites use
   `safeJsonLd`. Never write a new one without an escaping helper.
6. Uploads go through `app.core.uploads.read_upload_limited` (size, extension, content type,
   magic bytes, DOCX archive-bomb checks); stored under a server-generated name; served only
   as attachments with `nosniff`.
7. Log identifiers, not secrets or personal data. Audit `detail` must never contain a
   credential.
8. New background/AI features are opt-in, rate limited, and treat every retrieved string as
   data (see Â§8).
9. Add a regression test to `tests/test_v25_6_security_compliance.py` (or a new file) for
   every security fix.

## 5. Dependency updates

Backend `requirements.txt` uses compatible-range pins with **no lock file and no hashes**
(F-24), so builds are not reproducible. Frontend has a `package-lock.json`. Process:
[`VULNERABILITY_MANAGEMENT.md`](./VULNERABILITY_MANAGEMENT.md). The V25.6 environment had no
network, so **no advisory scan (`pip-audit`, `npm audit`, image scan) was run â€” NOT VERIFIED.**
Run them in CI before release.

## 6. Secrets

* `.env` is never committed (`.gitignore`, both `.dockerignore` files); `.env.example`
  contains placeholders only. A regex scan of the repository found no real keys,
  private keys or credentials.
* Production start-up **refuses** (`app.core.hardening.production_config_findings`):
  placeholder/`.env.example` secrets, secrets under 32/24 characters, `JWT_SECRET ==
  ADMIN_API_KEY`, non-PostgreSQL databases, missing SMTP, wildcard or malformed
  `FRONTEND_ORIGIN`, `AUTO_VERIFY_EMAIL_IN_TESTS=true`, `EMAIL_MODE != smtp`.
* Generate secrets with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
  Rotation steps: [`SECURITY_INCIDENT_RESPONSE.md`](./SECURITY_INCIDENT_RESPONSE.md).
* Rotating `JWT_SECRET` signs everyone out (and invalidates in-flight OTP codes).

## 7. Logging, monitoring and audit

* Every request has a sanitized `X-Request-ID` (V25.6: only `[A-Za-z0-9._-]{8,64}` is
  accepted from clients) carried into logs, errors and audit rows.
* Audit rows record actor, timestamp, action, target, request id and IP
  (`audit_logs`, and `platform_audit_logs` for platform actions). No route in the codebase
  updates or deletes them; only the account-erasure workflow rewrites the *actor label*.
  **The database does not enforce immutability** (no trigger / no separate app role â€” F-29);
  see the checklist.
* Security events surfaced to admins: failed logins, OTP failures, lockouts, refresh-token
  reuse (now emitted), privilege-escalation and cross-tenant attempts, invalid invitations,
  suspended-account access, platform setting changes, failed re-authentication on account
  closure.
* `/metrics` is disabled (403) in production unless `METRICS_TOKEN` is set.
* **NOT VERIFIED:** alert routing/paging â€” no alert destination is configured in the repo.

## 8. AI security

Applies to V20 (AI infrastructure, resume/interview/learning), V22 (application AI), V24
(recruiter AI), V25.3 (intelligence explanations) and V25.4 (Career Agent).

* **Untrusted text is data.** Resume text, job descriptions, recruiter/candidate notes,
  application text and tool results are wrapped by `wrap_untrusted` /
  `wrap_tool_result`. V25.6 fixes the delimiter-breakout flaw: text containing the closing
  marker could end the "data only" block early. Delimiter runs and marker phrases are now
  neutralized inside the content, in one place that covers ~25 call sites.
* **The model never touches the database.** The Career Agent selects from a fixed tool
  whitelist with validated parameters (`app/career_agent/tool_registry.py`); READ tools run
  immediately, WRITE and HIGH_RISK tools are stored `PENDING_CONFIRMATION` and run only when
  the owner calls the confirm endpoint. Free-text such as "yes" is not treated as
  confirmation.
* **Confirmation is exactly-once:** only `PENDING_CONFIRMATION` may be confirmed,
  the transition to `EXECUTING` is an atomic compare-and-set, and pending actions expire
  after `CAREER_AGENT_ACTION_TTL_MINUTES` (default 24 h). An action whose worker dies while
  `EXECUTING` is never re-run automatically.
* **No false claims of external effect.** `submit_application` and `draft_followup_message`
  only prepare a link/draft (`submitted:false` / `sent:false`); the agent's completion
  message now says so instead of "Done".
* Output validation, timeouts, per-provider token limits, rate limits and cost logs exist
  from V20.x/V20.6 (`docs/AI_SECURITY_AUDIT.md`). Provider outages fall back to
  deterministic templates.
* **Human decisions.** CareerOS assists; it never rejects, advances, ranks-out or hires a
  candidate automatically, and never infers protected characteristics (see Â§10).

## 9. File security

Resumes (8 MB), application documents (10 MB) and notification PDFs (10 MB) â€” limits are settings in `app/core/config.py`; extension allow-list,
declared-MIME allow-list, **magic-byte validation**, DOCX zip-bomb/path-traversal
checks, display filename sanitized, stored under `uuid.ext`, ownership
re-checked on every download, served as `attachment` with `nosniff` and a `default-src
'none'` CSP. No public URLs, no directory listing. **NOT VERIFIED / not implemented:** malware
scanning; if recruiters ever open candidate files, add scanning first. Notification "PDFs"
are generated on demand, not stored.

## 10. Privacy principles

* Collect only what a feature needs. Sensitive profile fields (`date_of_birth`,
  `reservation_category`, `is_pwd`) are optional, self-declared, used **only** by the
  candidate-facing V5 government-exam eligibility check (`app/services/eligibility.py`), and
  are never read by recommendation, ranking, recruiter search, recruiter analytics or AI
  prompt code (verified by search of the code base in V25.6). They are deleted on account
  erasure.
* No inference of protected characteristics. Recruiter AI prompts forbid them and an output
  filter (`app/recruiter_analytics/ai.py`) rejects responses that mention them.
* Retention, deletion and organization lifecycle:
  [`DATA_RETENTION_AND_DELETION.md`](./DATA_RETENTION_AND_DELETION.md).
* **Not implemented:** a machine-readable personal-data export. **NOT VERIFIED:** DPA/vendor
  agreements with the email and AI providers (operator responsibility).

## 11. Transport and headers

* API: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`,
  `Content-Security-Policy: default-src 'none'` (JSON API), HSTS in production, `Cache-Control:
  no-store` on credentialed requests.
* Browser app (`frontend/next.config.ts`): same family plus COOP; the full CSP is
  **Report-Only** by default (`CSP_ENFORCE=true` at build time to enforce) because it could
  not be exercised in a browser during V25.6, and it must allow `'unsafe-inline'` scripts
  for Next.js hydration, so it is defence-in-depth, not an XSS barrier.
* CORS: explicit origins from `FRONTEND_ORIGIN` (wildcards refused in production), credentials
  allowed, explicit method/header lists.
* TLS is terminated by your reverse proxy/load balancer â€” **NOT VERIFIED (deployment)**.
  The app sets HSTS but cannot enforce HTTPS itself.
* Client IPs/rate limits depend on `FORWARDED_ALLOW_IPS` being set to your proxy. Never `*`
  unless only the proxy can reach the backend port.

## 12. Encryption

Passwords: Argon2id. OTP/refresh tokens: hashed at rest. Secrets: environment only.
Database encryption at rest, backup encryption and disk encryption for the uploads volume:
**NOT VERIFIED â€” deployment infrastructure.** The application performs no field-level
encryption of personal data.

