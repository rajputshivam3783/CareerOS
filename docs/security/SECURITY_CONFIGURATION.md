# SECURITY_CONFIGURATION.md â€” V17.2

Every value below lives in `backend/app/core/config.py` (env-var
overridable, uppercase field name â€” e.g. `ACCOUNT_LOCKOUT_THRESHOLD`).
None of this is hardcoded in route handlers.

## Rate limiting (`app.core.rate_limit`)

| Setting | Default | Applies to |
|---|---|---|
| `auth_rate_limit_attempts` / `auth_rate_limit_window_seconds` | 10 / 60s | register, login (candidate/recruiter, shared), verify-email, resend-otp, forgot-password, reset-password, refresh |
| `admin_login_rate_limit_attempts` / `_window_seconds` | 5 / 300s | admin/super_admin login (V17.2 â€” stricter, distinct budget) |
| `profile_update_rate_limit_attempts` / `_window_seconds` | 20 / 60s | `PUT /profile` |
| `redis_url` | unset (in-memory) | shared backend for all of the above across replicas; falls back to in-memory if unreachable |

## Account lockout (`app.core.account_lockout`) â€” V17.2

| Setting | Default | Meaning |
|---|---|---|
| `account_lockout_threshold` | 5 | failed logins before a temporary lock |
| `account_lockout_base_minutes` | 5 | first lock's duration |
| `account_lockout_max_minutes` | 240 | cap on escalating lock duration |
| `account_progressive_delay_after_attempts` | 3 | failures before inter-attempt delay kicks in |
| `account_progressive_delay_base_seconds` | 2 | delay base (doubles per attempt past the threshold) |
| `account_progressive_delay_max_seconds` | 30 | cap on that delay |
| `default_admin_lock_minutes` | 60 | default duration for an admin-issued temporary lock with no explicit `minutes` |

## OTP hardening (`app.core.otp_security`) â€” V17.2

| Setting | Default | Meaning |
|---|---|---|
| `otp_max_attempts` | 5 | wrong guesses before a code is invalidated |
| `otp_resend_cooldown_seconds` | 60 | minimum gap between resend requests |

## Session timeouts (`app.core.sessions`) â€” V17.2

| Setting | Default | Meaning |
|---|---|---|
| `session_idle_timeout_minutes` | 10080 (7 days) | no `/refresh` call within this window revokes the session |
| `session_absolute_timeout_days` | 90 | hard cap from session creation, regardless of activity |

## Already existing (V16/V17.1, unchanged by this pass)

| Setting | Default | Meaning |
|---|---|---|
| `jwt_secret` | â€” (required) | access-token signing key |
| `access_token_minutes` | â€” | access-token lifetime |
| `refresh_token_days` / `refresh_token_remember_me_days` | â€” | refresh-token lifetime, normal vs. "remember me" |
| `password_min_length` | â€” | minimum password length |
| `password_history_limit` | â€” | how many previous password hashes are checked for reuse |
| `admin_api_key` | â€” (required) | shared `X-Admin-Key` credential, still accepted alongside admin-user JWT |

## Changing these safely

All of the above are read once into the `settings` singleton at
process start (`app.core.config`). Changing an env var requires a
process restart to take effect â€” there is no hot-reload, by design
(a security threshold that can change mid-request-without-restart is
a change nobody explicitly reviewed at deploy time).

## V25.6 â€” Enterprise Security & Compliance settings

All are environment-overridable (uppercase field name) and default to backward-compatible
values. Full context: [`docs/SECURITY.md`](./docs/SECURITY.md).

| Setting | Default | Meaning |
|---|---|---|
| `access_token_session_check` | `true` | every authenticated request confirms the access token's `sid` session is not revoked (one PK lookup). `false` restores pre behaviour |
| `admin_key_auth_enabled` | `true` | allow the shared `X-Admin-Key`. Set `false` once named admin accounts exist; affects all three admin guards and the maintenance-mode bypass |
| `metrics_token` | unset | `/metrics` needs `Authorization: Bearer <token>`; unset â‡’ **403 in production**, open in development |
| `career_agent_action_ttl_minutes` | `1440` | how long a `PENDING_CONFIRMATION` action can still be confirmed |
| `password_reset_cooldown_seconds` | `60` | minimum gap between reset codes for one account |
| `retention_purge_enabled` | `false` | opt-in gate for `scripts/retention_purge.py --execute` |
| `retention_auth_artifacts_days` / `retention_notifications_days` / `retention_email_messages_days` / `retention_ai_usage_logs_days` | `30` / `365` / `365` / `365` | purge ages; `0` = keep forever. Audit logs and hiring records are never purged |

Production start-up validation (`app.core.hardening.production_config_findings`) refuses
placeholder secrets, short secrets, `JWT_SECRET == ADMIN_API_KEY`, a non-PostgreSQL URL, missing
SMTP, wildcard/malformed `FRONTEND_ORIGIN`, `AUTO_VERIFY_EMAIL_IN_TESTS=true` and
`EMAIL_MODE != smtp`; plain-http and localhost origins only warn.

Deployment: `FORWARDED_ALLOW_IPS` (uvicorn) must be your reverse proxy's address so client IPs â€”
and therefore rate-limit buckets and audit IPs â€” are correct. `CSP_ENFORCE` (frontend, **build**
time) switches the browser CSP from Report-Only to enforced.

