# AUTH_API.md â€” V17.1 Authentication Endpoints

Base path: `/api/v1/auth` (candidate/recruiter/admin registration &
login) and `/api/v1/admin` (admin account provisioning). Full
interactive docs remain auto-generated at `/docs` (Swagger UI) and
`/openapi.json` from these same route definitions â€” nothing here is a
separate spec to keep in sync by hand.

Legend: ðŸ”“ no auth required Â· ðŸ”’ requires `Authorization: Bearer <access_token>`

## Registration

### `POST /auth/candidate/register` ðŸ”“ (alias: `POST /auth/register`)
```json
{
  "email": "jane@example.com",
  "password": "at-least-12-characters",
  "password_confirm": "at-least-12-characters",
  "full_name": "Jane Doe",
  "phone": "+15550001234"   // optional; must be unique if given
}
```
â†’ `201`, sends a 6-digit email OTP:
```json
{"verification_required": true, "email": "jane@example.com", "message": "..."}
```
`409` on duplicate email or phone. `422` on password/confirmation
mismatch, password under 12 characters, or missing required fields.

### `POST /auth/recruiter/register` ðŸ”“
Same body as candidate registration, plus:
```json
{
  "company_name": "Acme Corp",
  "company_website": "https://acme.example",   // optional
  "company_email": "hr@acme.example"
}
```
â†’ `201`, same response shape. Account is created with
`recruiter_status="pending"` â€” cannot log in until an admin approves
it (`POST /admin/recruiters/{id}/approve`).

## Email verification

### `POST /auth/verify-email` ðŸ”“
```json
{"email": "jane@example.com", "code": "123456"}
```
â†’ `200 {"verified": true, "recruiter_status": null}`. `400` on
invalid/expired code.

### `POST /auth/resend-otp` ðŸ”“
```json
{"email": "jane@example.com"}
```
â†’ `200`, enumeration-safe generic message regardless of whether the
account exists.

## Login (role-scoped)

### `POST /auth/candidate/login` ðŸ”“ (alias: `POST /auth/login`)
### `POST /auth/recruiter/login` ðŸ”“
### `POST /auth/admin/login` ðŸ”“ (admin or super_admin)

Request:
```json
{
  "email": "jane@example.com",
  "password": "at-least-12-characters",
  "remember_me": false,
  "device_id": "optional-client-generated-id",
  "device_label": "Jane's laptop"
}
```

Response `200`:
```json
{
  "access_token": "<jwt, 15 min>",
  "token_type": "bearer",
  "role": "candidate",
  "refresh_token": "<opaque, 30â€“90 days>",
  "user": {
    "id": 1, "email": "jane@example.com", "full_name": "Jane Doe",
    "role": "candidate", "phone": null, "email_verified": true,
    "recruiter_status": null, "company_name": null,
    "company_website": null, "company_email": null
  },
  "session": {"id": 5, "device_id": "optional-client-generated-id"}
}
```

Errors: `401` invalid credentials Â· `403` unverified email, wrong-role
endpoint (message names the correct one), or recruiter pending
approval.

## Token lifecycle

### `POST /auth/refresh` ðŸ”“ (refresh token is the credential)
```json
{"refresh_token": "<the one from login or the previous refresh>"}
```
â†’ `200`, same shape as login minus `session`. The refresh token you
sent is now invalid â€” use the new one. `401` if invalid, expired,
already-used (rotated away), or belongs to a revoked session.

### `POST /auth/logout` ðŸ”’
```json
{"refresh_token": "<optional â€” revokes that session if given>"}
```
â†’ `200 {"logged_out": true}`

### `POST /auth/logout-all` ðŸ”’
â†’ `200 {"logged_out": true, "sessions_revoked": 3}`

### `GET /auth/sessions` ðŸ”’
â†’ `200`, array of active sessions:
```json
[{"id": 5, "device_id": "...", "device_label": "Jane's laptop",
  "ip_address": "203.0.113.4", "user_agent": "...",
  "remember_me": false, "created_at": "...", "last_seen_at": "..."}]
```

### `DELETE /auth/sessions/{id}` ðŸ”’
â†’ `200 {"revoked": true}` Â· `404` if the session doesn't belong to the
caller (or doesn't exist).

## Password

### `POST /auth/password-strength` ðŸ”“
```json
{"password": "candidate password to score"}
```
â†’ `200 {"score": 3, "label": "Strong", "feedback": ["Good password"]}`

### `POST /auth/forgot-password` ðŸ”“
```json
{"email": "jane@example.com"}
```
â†’ `200`, enumeration-safe generic message; sends a reset OTP only if
the account exists, is active, and is verified.

### `POST /auth/reset-password` ðŸ”“
```json
{
  "email": "jane@example.com", "code": "123456",
  "new_password": "at-least-12-characters",
  "new_password_confirm": "at-least-12-characters"
}
```
â†’ `200 {"reset": true}`. Also revokes every active session for the
account. `400` on invalid/expired code, confirmation mismatch, or
reuse of one of the account's last 5 passwords.

## Admin account provisioning

### `POST /admin/create-admin-user`
Header: `X-Admin-Key: <shared admin key>` **or**
`Authorization: Bearer <admin/super_admin access token>`.
```json
{
  "email": "ops@careeros.example",
  "password": "at-least-12-characters",
  "full_name": "Ops Admin",
  "role": "admin"   // or "super_admin"
}
```
â†’ `201 {"id": 42, "email": "ops@careeros.example", "role": "admin"}`.
`400` invalid role or weak password Â· `401` missing/bad credential Â·
`409` duplicate email.

This is the **only** endpoint that can create an admin or super_admin
account â€” there is no public registration path for either role.

## Profile

### `GET /auth/me` ðŸ”’
â†’ `200`, same `user` object shape shown under Login above.

## Backward-compatibility summary

Every V16 request/response shape still works unchanged except where
the V17.1 requirements explicitly demanded a stricter rule (12-char
minimum, required `password_confirm`). No V16 response field was
removed or renamed â€” every V17.1 addition (`refresh_token`, `user`,
`session`) is new, not a replacement.

