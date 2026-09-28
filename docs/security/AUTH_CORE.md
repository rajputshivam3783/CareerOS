# AUTH_CORE.md â€” V17.1 Enterprise Authentication Core

Architecture reference for the authentication system. For the
endpoint list and request/response shapes, see `AUTH_API.md`. For
what changed vs. V16, see `CHANGELOG_V17_1.md`.

## Modules

| Module | Responsibility |
|---|---|
| `app/api/auth.py` | Route handlers, request/response schemas, role-scoped registration/login |
| `app/api/admin.py` | `POST /admin/create-admin-user` (the only admin/super_admin provisioning path) |
| `app/core/security.py` | Password hashing (Argon2id), short-lived access-token issuance/verification, `current_user`/`require_admin`/`require_super_admin`/`require_recruiter` dependencies |
| `app/core/sessions.py` | Session + refresh-token lifecycle: issue, rotate, revoke, list |
| `app/core/password_policy.py` | Strength scoring, password-history reuse checks |
| `app/core/rbac.py` | `role â†’ permissions` map (unchanged shape from V16; `super_admin` added) |
| `app/models/domain.py` | `User` (extended), `UserSession`, `RefreshToken`, `PasswordHistory` |

This split mirrors what was already there in V16 (`security.py` doing
password + token work) rather than inventing a new layering â€” the new
pieces are `sessions.py` (session/refresh-token state, which didn't
exist before) and `password_policy.py` (strength/history, likewise
new), kept separate from `security.py` so that file stays focused on
what it already did.

## Roles

`candidate`, `recruiter`, `admin`, `super_admin` â€” `app.core.security.
KNOWN_ROLES`. `ADMIN_ROLES = {"admin", "super_admin"}` is the set used
everywhere an endpoint should accept either.

Role is stored on `users.role` (unchanged column, now with a fourth
value) and is read fresh from the database on every request â€” a JWT's
`role` claim reflects the role *at the time the token was issued*, but
every permission check re-fetches the current user row rather than
trusting the claim, so a role change (or an account being deactivated)
takes effect on the very next request, not on next login. This was
already true of `require_admin`/`require_recruiter`/the `/admin/*`
guard in V16; V17.1 keeps it.

## Registration

`POST /auth/candidate/register` and `POST /auth/recruiter/register`
(plus `/auth/register` as a backward-compatible alias for the
candidate path) create the user row directly with `role="candidate"`
or `role="recruiter"`. There is no `role` field in either request body
â€” it isn't accepted from the client, so a request can't self-elevate
by passing `"role": "admin"`.

Recruiter accounts get `recruiter_status="pending"` and can't log in
via `/auth/recruiter/login` until an admin approves them
(`POST /admin/recruiters/{id}/approve`) â€” unchanged from V16.

Admin and super_admin accounts are never created by any endpoint under
`/auth/*`. The only path is `POST /admin/create-admin-user`, gated by
`app.api.admin.guard` (the same dependency every other admin route
uses): either the shared `X-Admin-Key` header, or a Bearer JWT for an
already-existing admin/super_admin user. This is what satisfies "Admin
registration must not be public" â€” it's a closed loop bootstrapped by
whoever holds the admin key at deploy time.

## Passwords

- Hashing: Argon2id via `pwdlib.PasswordHash.recommended()` â€”
  unchanged from V16, already met the "use Argon2id" requirement.
- Minimum length: 12 characters (`settings.password_min_length`),
  enforced by the pydantic schema (`Register`, `RecruiterRegister`,
  `ResetPassword`), not by the strength meter.
- Confirmation: `password_confirm` / `new_password_confirm`, checked
  with a pydantic `model_validator(mode="after")`.
- Strength meter: `POST /auth/password-strength` returns a 0â€“4 score
  and feedback strings (`app/core/password_policy.score_password`).
  Purely advisory â€” a low score doesn't block anything; the hard
  requirements above do.
- History: every password (at registration, and on every successful
  reset) is recorded in `password_history`
  (`app/core/password_policy.record_password_history`), pruned to the
  most recent `settings.password_history_limit` (default 5) per user.
  `POST /auth/reset-password` rejects a new password that matches any
  of them.

## Sessions and refresh tokens

One `user_sessions` row is created per login â€” one per device,
identified by a client-supplied or server-generated `device_id`. Each
session owns a chain of `refresh_tokens` rows:

```
login  â”€â”€â–¶  UserSession â”€â”€â–¶ RefreshToken #1 (active)
POST /auth/refresh (token #1) â”€â”€â–¶ RefreshToken #1 revoked, replaced_by â†’ #2 (active)
POST /auth/refresh (token #2) â”€â”€â–¶ #2 revoked, replaced_by â†’ #3 (active)
```

- **Never store plaintext.** `refresh_tokens.token_hash` is sha256 of
  the token actually handed to the client â€” same treatment
  `email_verifications.code_hash` already gives OTP codes.
- **Rotation.** `POST /auth/refresh` always issues a new refresh token
  and revokes the one it was given. A client should always use the
  refresh token from the most recent response, never an older one.
- **Reuse/theft detection.** If an already-rotated (or already-
  revoked) refresh token is presented again, the entire session is
  revoked â€” every refresh token in that session's chain, not just the
  one that was reused. This is the standard mitigation for a stolen
  refresh token being replayed after the legitimate client already
  rotated past it.
- **Access tokens carry `sid`.** The session id is embedded in the JWT
  so a future pass could reject access tokens from a revoked session
  before they naturally expire (15 minutes); today expiry alone bounds
  the blast radius of a leaked access token.
- **Remember me.** `remember_me=true` at login extends the refresh
  token's lifetime from 30 to 90 days (`settings.refresh_token_days` /
  `refresh_token_remember_me_days`). Nothing else about the flow
  changes â€” the difference is purely how long the refresh token lives
  before it needs a fresh login.

Logout endpoints:

- `POST /auth/logout` â€” revokes the session tied to the refresh token
  in the request body (i.e. logs out the current device).
- `POST /auth/logout-all` â€” revokes every active session for the
  caller.
- `DELETE /auth/sessions/{id}` â€” revokes one specific session by id
  (e.g. "log out my old phone" from a list rendered by
  `GET /auth/sessions`), after confirming it belongs to the caller.
- Password reset (`POST /auth/reset-password`) implicitly calls the
  same "revoke all sessions" path â€” a reset is often a response to a
  suspected compromise, so any session that compromise already opened
  should not survive it.

## JWT claims

```json
{
  "sub": "<user id>",
  "role": "candidate|recruiter|admin|super_admin",
  "sid": "<session id, or null for tokens minted without a session>",
  "iat": 1234567890,
  "exp": 1234568790
}
```

Signed HS256 with `settings.jwt_secret` â€” unchanged signing mechanism
from V16. `exp` is now 15 minutes out instead of 7 days; long-lived
sessions live in the refresh-token/session tables instead of in the
token itself.

## Middleware / dependencies

- `current_user` â€” decodes the access token, loads the user, sets the
  request's audit actor. Unchanged behavior from V16 beyond reading
  `sid` (currently unused for revocation checks â€” see note above).
- `require_admin` â€” `role in {"admin", "super_admin"}`.
- `require_super_admin` â€” `role == "super_admin"` only (used nowhere
  yet in V17.1's own endpoints, but exported for future admin-only
  actions like managing other admins).
- `require_recruiter` â€” `role == "recruiter"` and approved, or any
  admin role (admins can do anything a recruiter can â€” unchanged from
  V16).

## Database schema (new/changed)

See `backend/migrations/v17_1_auth_core.sql` for the exact DDL. In
brief:

- `users` â€” new nullable columns `phone`, `company_name`,
  `company_website`, `company_email`. No existing column changed
  type, nullability, or default; every pre row remains valid.
- `user_sessions` â€” `id, user_id, device_id, device_label, ip_address,
  user_agent, remember_me, created_at, last_seen_at, revoked_at`.
- `refresh_tokens` â€” `id, user_id, session_id, token_hash (unique),
  expires_at, revoked_at, replaced_by_id, created_at`.
- `password_history` â€” `id, user_id, password_hash, created_at`.

SQLite (dev/test) picks up the same shape automatically via
`Base.metadata.create_all` at app startup, unchanged mechanism from
every prior version.

