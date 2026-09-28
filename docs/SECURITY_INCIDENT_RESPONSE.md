# Security Incident Response

Operational runbook for the eight scenarios below. It is a starting procedure written from
the code base; **it has never been rehearsed** (NOT VERIFIED) and contains no external legal
or regulatory reporting deadlines â€” those depend on your jurisdiction, contracts and
customers, and must be added by your legal/compliance owner. Do not treat this file as
advice on what you are obliged to report or when.

## 0. Roles, severity, first hour

* **Incident lead** (decides, keeps the timeline), **operator** (executes changes),
  **communicator** (internal/customer messages). One person may hold several roles.
* Severity uses the same scale as [`VULNERABILITY_MANAGEMENT.md`](./VULNERABILITY_MANAGEMENT.md)
  (CRITICAL/HIGH/MEDIUM/LOW). Treat any confirmed cross-tenant data exposure, credential
  compromise or admin takeover as CRITICAL until proven otherwise.
* **First hour, always:** (1) open a timestamped incident log; (2) preserve evidence *before*
  changing things â€” export `audit_logs`/`platform_audit_logs`, application logs, proxy logs,
  database and volume snapshots; (3) contain; (4) only then investigate and remediate.
  Do not delete logs, and do not run destructive database commands.

### Tools the platform already provides

| Need | Mechanism |
|---|---|
| Sign one user out everywhere | `POST /api/v1/admin/rbac/users/{user_id}/force-logout` (V25.6: takes effect on the very next request â€” access tokens are bound to their session) |
| Revoke one session | `POST /api/v1/admin/sessions/{session_id}/revoke`; list with `GET /admin/users/{id}/sessions` |
| Suspend / deactivate a user | `POST /admin/users/{id}/suspend`, `/deactivate` (platform), `POST /admin/rbac/users/{id}/suspend` |
| Force a password reset | `POST /admin/rbac/users/{id}/reset-password` |
| Suspend an organization / a job | `POST /admin/organizations/{id}/suspend`, `POST /admin/jobs/{id}/suspend` |
| Maintenance mode | platform setting `maintenance_mode` via `PUT /admin/settings/{key}`; V25.6: only a *valid* admin credential bypasses it |
| Read audit / security events | `GET /admin/audit` (platform), `GET /admin/audit-logs`, `GET /admin/rbac/audit-logs/export`, `GET /admin/security/events`, `/admin/security/failed-logins`, `/admin/security/locked-accounts`, `/admin/security/abuse-signals`; organization admins: `GET /organizations/{id}/audit-log` |
| Disable the shared admin key | `ADMIN_KEY_AUTH_ENABLED=false` (restart) |
| Sign **everyone** out | rotate `JWT_SECRET` (restart) â€” invalidates every access token and OTP in flight; refresh tokens are hashed random values and are revoked separately (below) |
| Revoke every session in the database | operator-run SQL, only with approval: `UPDATE user_sessions SET revoked_at = NOW() WHERE revoked_at IS NULL;` plus the matching `refresh_tokens` update. (V25.6 access-token session checks then reject all tokens immediately.) |

### Credential rotation (used by several scenarios)

1. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
2. Update the secret store / `.env` (never commit it). Production start-up rejects
   placeholders, short values, and `JWT_SECRET == ADMIN_API_KEY`.
3. Restart the affected service (`docker compose -f docker-compose.production.yml up -d
   backend`). Confirm `/ready` is healthy and that the old value no longer works.
4. Record who rotated what and when in the incident log.

| Secret | Effect of rotation |
|---|---|
| `JWT_SECRET` | all access tokens invalid; in-flight OTP/reset codes invalid (they are HMAC-keyed with it) |
| `ADMIN_API_KEY` | every user of the shared key must be given the new one |
| `POSTGRES_PASSWORD` / `DATABASE_URL` | change in Postgres first, then the app; the `migrate` service uses the same value |
| `SMTP_PASSWORD`, `CAREER_AI_ANTHROPIC_API_KEY`, `METRICS_TOKEN`, partner API keys | rotate at the provider / re-issue partner key (`/admin/partners`), then update config |

## 1. Suspected account compromise (a user or a recruiter)

*Signals:* logins from unexpected places, `login_failed` bursts followed by success, session
list showing unknown devices, refresh-token-reuse events, user report.

1. **Contain:** force-logout the user; suspend the account if the attacker may still hold the
   password; for a recruiter, also review organization membership and remove unknown members.
2. **Investigate:** list their sessions (IP, user agent, created time); search audit logs for
   their `actor_id` across the suspected window; check for password-reset emails, role changes
   and new invitations they issued.
3. **Scope:** for a recruiter, list everything reachable through `team_owner_ids`
   (jobs/applicants/notes) â€” that is the exposure set. For a candidate: profile, applications,
   documents, notifications.
4. **Recover:** verified owner resets password (`forgot-password`), unsuspend, review data
   changes and revert with backups/audit trail where needed.
5. **Follow-up:** if a password-reuse or credential-stuffing pattern is visible, tighten rate
   limits and check the lockout settings.

## 2. Leaked API key or secret (JWT, admin key, provider, partner)

1. Assume it is in use. **Rotate immediately** (table above) â€” do not wait to confirm abuse.
2. Remove it from wherever it leaked (repository history, ticket, chat, logs). A key in git
   history must be treated as compromised even after deletion.
3. **Investigate:** for `ADMIN_API_KEY`, audit rows with actor `shared admin key` during the
   exposure window (they carry no personal identity â€” this is the weakness of the shared key);
   for `JWT_SECRET`, an attacker could forge tokens for any user id: review audit trails for
   admin/role/permission changes and any actor you cannot account for; for a provider key,
   check the provider's usage console; for a partner key, review `/admin/partners` submissions.
4. **Prevent recurrence:** set `ADMIN_KEY_AUTH_ENABLED=false` once named admin accounts exist;
   add secret scanning to CI.

## 3. Database credential exposure

1. Rotate the database password (Postgres, then application config); restart backend,
   `migrate`, and any job/scheduler using it.
2. Restrict network access (the database must not be published on a public interface;
   `docker-compose.production.yml` does not publish it).
3. **Investigate:** database server logs for connections from unknown hosts, unusual queries,
   bulk reads of `users`, `applicants`, `resumes`, `email_messages`, `audit_logs`; compare row
   counts with a recent backup to detect modification/deletion.
4. **Assume a full read** of the database: password hashes (Argon2id), hashed OTP/refresh
   tokens, and all personal data are exposed. Force-logout everyone (rotate `JWT_SECRET` and
   revoke sessions) and consider forcing password resets.
5. Note: the application currently uses a single database role for both migrations and
   runtime (F-31). A least-privilege runtime role is recommended.

## 4. Cross-tenant data leak (Organization A saw Organization B)

Highest priority â€” the tenant boundary is the core promise of V25.1.

1. **Contain:** if the affected endpoint is known, disable it at the proxy or enable
   maintenance mode; suspend the organization(s) if needed (reversible, nothing is deleted).
2. **Preserve evidence:** request logs with `X-Request-ID`, audit rows, `cross_tenant_access_attempt`
   events.
3. **Root-cause:** identify the resolution path â€” most recruiter/candidate scoping goes through
   `team_owner_ids` (`app/core/team_access.py`) and `_owned_*_or_404` helpers; organization
   endpoints through `require_organization_membership`. Reproduce with a two-organization test
   and add it to `tests/test_v25_6_security_compliance.py` **before** fixing.
4. **Affected-user identification:** reconstruct from request logs which records were returned
   to which authenticated user during the window; list the organizations and candidates whose
   data was disclosed.
5. **Recover:** ship the fix, redeploy, verify with the regression test, then reactivate.
6. **Notify** per your own legal/contractual obligations (not defined here).

## 5. Malicious file upload

1. Locate the file: `application_documents` row (`stored_filename`) and the volume
   `var/uploads/application_documents`. Files are named by random UUID, never executed, and
   served only as attachments with `nosniff`.
2. **Contain:** delete the DB row via the owner's normal delete flow (or suspend the user) and
   quarantine the file (move, do not open). If recruiters or staff could have opened it,
   treat their devices as potentially exposed.
3. **Investigate:** which account uploaded it, when, from which IP (audit/session records);
   whether any other user could download it (downloads require ownership â€” verify in logs).
4. **Prevent:** V25.6 validates magic bytes and DOCX archive structure but performs **no
   malware scanning** â€” add scanning (e.g. ClamAV) before any feature exposes candidate files
   to recruiters.

## 6. AI data leakage or prompt-injection incident

*Signals:* an AI answer contains another user's data; the Career Agent performed an action the
user did not intend; text in a resume/job/note appears to have steered the model.

1. **Contain:** disable the affected AI feature via platform/AI configuration (or unset the
   provider key) â€” deterministic fallbacks keep the product usable.
2. **Investigate:** find the conversation and `career_agent_actions` rows (status, payload,
   timestamps); identify the untrusted source (resume, job description, notes, tool result).
   Confirm that no WRITE/HIGH_RISK action ran without an explicit confirm call (they must be
   `PENDING_CONFIRMATION` until the owner confirms).
3. **Scope:** the model only ever receives context assembled for the requesting user through
   whitelisted tools; identify what context was in the prompt for that request.
4. **Fix:** treat as a code defect â€” add the payload as a regression test for
   `wrap_untrusted`/`wrap_tool_result` behaviour; never rely on prompt wording alone.
5. **Provider side:** review what was sent to the provider and the provider's retention terms
   (NOT VERIFIED â€” outside this repository).

## 7. Unauthorized admin access

1. **Contain:** rotate `ADMIN_API_KEY` and `JWT_SECRET`; force-logout and suspend the suspicious
   admin account(s); set `ADMIN_KEY_AUTH_ENABLED=false` if named accounts exist.
2. **Investigate:** platform audit (`GET /admin/audit`, filterable by action), especially
   role changes, permission grants (`/admin/rbac/...`), user suspend/reactivate, organization
   or job suspension, platform setting changes, data exports, partner key issuance.
3. **Revert** unauthorized changes using the audit trail; re-verify who holds `admin` /
   `super_admin` roles directly in the database.
4. **Note:** actions taken with the shared key are attributed to "shared admin key" only.

## 8. Service or host compromise

1. **Isolate** the host/container from the network; do not reboot (preserve memory/disk).
2. Snapshot disks/volumes; collect proxy, application and database logs.
3. **Assume every secret on the host is exposed**: rotate all of them (table above) and any
   credential the host could reach (registry, cloud, SMTP, provider APIs).
4. Rebuild from a known-good image and a reviewed commit; restore data from a backup taken
   before the compromise if integrity is in doubt (backup/restore is deployment-owned â€”
   **NOT VERIFIED**).
5. Investigate initial access (exposed ports, vulnerable dependency, leaked credential) and
   review whether the attacker could reach the database or uploads volume.

## After every incident

Within a week hold a blameless review: timeline, root cause, what detection worked or failed,
what would have made containment faster, and the regression tests / controls to add. Update
this runbook, `SECURITY_CONTROL_MATRIX.md` and the vulnerability register. Record unresolved
issues openly; do not remove them from the register.

