# SECURITY_ARCHITECTURE.md â€” V17.2

Describes the authentication/security system as it exists after V17.2.
Read [AUTH_CORE.md](./AUTH_CORE.md) first for the V17.1 foundation
this builds on (JWT access tokens, refresh-token rotation with reuse
detection, multi-device sessions, hashed OTPs, password history) â€”
this document only covers what V17.2 added on top of it, per the
"reuse all existing authentication code, do not redesign" instruction
this pass was scoped under.

## Layers

```
Request
  â”‚
  â”œâ”€ app.core.rate_limit        per-IP request budget (in-memory or Redis)
  â”‚
  â”œâ”€ app.core.account_lockout   per-ACCOUNT failure tracking (login only)
  â”‚
  â”œâ”€ app.core.otp_security      per-OTP-code attempt/resend limits
  â”‚
  â”œâ”€ app.core.sessions          session lifecycle: create, rotate, revoke,
  â”‚                             idle/absolute timeout (V17.2 additions)
  â”‚
  â””â”€ app.core.security_events   every security-relevant action lands here,
                                 which writes it to the audit log
                                 (app.core.audit) and notifies any
                                 registered handler
```

## Why rate limiting and account lockout are two separate systems

They answer different questions and are keyed differently:

- **Rate limiting** (`app.core.rate_limit`, V16 + V17.2): "has this
  *IP address* made too many requests to this endpoint?" Stops a
  single source hammering many accounts, or one account, fast.
- **Account lockout** (`app.core.account_lockout`, V17.2, new): "has
  this *account* failed to log in too many times?" Stops an attacker
  who rotates IPs against one known email â€” the rate limiter alone
  doesn't catch that, since each IP individually stays under budget.

A login request passes through both. Locking out an account never
throttles the rate limiter's budget for that IP (a stolen-password
attempt against a locked account still "counts" as a normal request
for rate-limiting purposes) â€” they're independent, not layered
versions of the same control.

## Account lockout design

Two tiers, both scoped to `_login` in `app.api.auth`:

1. **Progressive delay** â€” once `failed_login_count` passes
   `account_progressive_delay_after_attempts` (default 3), each
   subsequent attempt must wait `min(base * 2^(count - threshold),
   max_seconds)` since the last failure, enforced by *rejecting* an
   early attempt with 429 â€” never by sleeping the request thread,
   which would tie up a worker and is itself a denial-of-service risk
   under load.
2. **Temporary lock** â€” at `account_lockout_threshold` (default 5)
   failures, the account is locked for `lock_duration_minutes(user.
   lock_count)` (escalates: doubles per prior lock, capped at
   `account_lockout_max_minutes`). Lifts automatically once
   `locked_until` passes â€” checked at login time, no separate cleanup
   job needed.

**Permanent lock deliberately reuses `User.active`** rather than a
new column â€” every auth code path (`_login`, `current_user`,
`rotate_refresh_token`) already treats an inactive user as fully
unable to authenticate, including with existing valid sessions, which
the temporary lock above does not attempt to do (scoped to login time
only, to avoid touching those other call sites â€” see
`account_lockout.py`'s module docstring for the full reasoning).

**Known nuance, not swept under the rug**: an admin-issued permanent
lock (`active=False`) does not short-circuit the lock-check block at
the top of `_login` (which only inspects `locked_until`) â€” a login
attempt against a permanently-locked account instead falls through to
the generic "invalid credentials" branch, which also calls
`record_failed_login`. In practice this means a permanently-locked
account can also accumulate temporary-lock state on top of being
deactivated. Harmless (the account can't log in either way) but worth
knowing if you're reading the lockout counters for an account and see
both `active=false` and a `locked_until` in the past.

## OTP hardening

Hashing, expiration, and single-use were already in place before
V17.2 (see AUTH_CORE.md). New in V17.2:

- **Max attempts** (`otp_max_attempts`, default 5) â€” a code is
  invalidated after this many wrong guesses, independent of the
  per-IP `verify-email`/`reset-password` rate-limit buckets (which an
  attacker distributing guesses across IPs wouldn't trip).
- **Resend cooldown** (`otp_resend_cooldown_seconds`, default 60) â€”
  minimum gap between resend requests for the same purpose.

## Session timeouts

`app.core.sessions.rotate_refresh_token` â€” called on every `POST
/auth/refresh` â€” now also enforces:

- **Idle timeout** (`session_idle_timeout_minutes`) â€” resets on every
  refresh call (`UserSession.last_seen_at`).
- **Absolute timeout** (`session_absolute_timeout_days`) â€” a hard cap
  from session creation, does not reset on activity.

This is the natural enforcement point rather than, say, only checking
at next login: access tokens are short-lived (15 min default), so a
legitimate client calls `/refresh` often, making this an effective
checkpoint rather than a theoretical one.

## Security events

`app.core.security_events` is a thin taxonomy (`SecurityEvent` enum)
over the existing audit log (`app.core.audit.log_audit`) â€” every
event is still an audit row, `GET /admin/audit-logs` is unaffected.
What's new is `register_handler()`, a real, working extension point
for future SIEM/webhook/notification forwarding. **No handler is
registered anywhere in this codebase by default** â€” this makes wiring
one possible without touching every call site, it does not claim any
external integration already exists. A handler that raises is caught
and logged, never allowed to fail the request that triggered it.

## Admin security surface (new in V17.2)

- `POST /admin/users/{id}/lock` â€” permanent (`active=false`) or
  temporary (`locked_until`).
- `POST /admin/users/{id}/unlock` â€” reverses either kind.
- `GET /admin/security/locked-accounts` â€” currently-locked accounts,
  split by permanent/temporary.
- `GET /admin/security/failed-logins` â€” recent failed-login and
  locked-account-login-attempt events.
- `GET /admin/users/{id}/sessions` â€” a user's active sessions.
- `POST /admin/sessions/{id}/revoke` â€” admin-initiated revoke, no
  ownership check (the caller is already admin-authorized).

## What V17.2 explicitly did not touch

Per this pass's own scope: Government Hub, Recruiter ATS, AI, Search,
Notifications, Analytics, Deployment, Docker, RBAC/permissions
beyond what already existed, and any database schema unrelated to
security. See CHANGELOG_V17_2.md for the file-level diff and
TEST_REPORT_V17_2.md for what could and couldn't be verified in the
environment this was built in.

