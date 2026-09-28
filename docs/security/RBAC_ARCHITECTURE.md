# RBAC Architecture â€” V17.3

## What this pass added, and what it deliberately reused

V17.1/V17.2 already built real authentication (candidate/recruiter/admin
split login, OTP email verification, refresh-token sessions, account
lockout, audit logging with actor/request-id correlation) and a first-cut
permission module (`app/core/rbac.py`, colon-namespaced permissions like
`jobs:manage_own`) that was never wired into a live route.

V17.3 does not rewrite any of that. It:

1. Extends `app/core/rbac.py` with a second, **dot-namespaced** permission
   catalog (`jobs.create`, `users.read`, etc. â€” the exact strings this
   pass's brief specified) and four new roles that sit in the hierarchy
   between the existing `recruiter` and `admin` roles.
2. Adds **database-backed permission overrides** so a permission can be
   granted to or revoked from a role at runtime (an admin action), not
   only via a code change.
3. Adds a new, isolated router (`app/api/admin_rbac.py`) for the actual
   admin-panel endpoints (roles, permissions, sessions, suspend/reset/force-logout,
   audit export) â€” mounted under the existing `/admin` prefix, but in its own
   file so this pass's diff never touches an existing route.
4. Reuses, rather than duplicates, several already-built mechanisms â€” see
   "What was reused, not rebuilt" below.

## Role hierarchy

```
candidate â†’ recruiter â†’ recruiter_manager â†’ recruiter_admin â†’ support_admin â†’ system_admin â†’ super_admin
```

`User.role` is a plain `VARCHAR(30)` column with no database-level enum
constraint â€” this is consistent with every prior role/status value this
project has ever added (see the V16/V14 precedent noted in
`app/core/rbac.py`'s docstring), so introducing four new role *values*
needed no migration. `ROLE_HIERARCHY` in `app/core/rbac.py` is used only
for admin-UI display ordering â€” it is never used for permission checks,
which are always plain set-membership. This is a deliberate choice: a
numeric "role N can do everything role N-1 can" comparison is a common
source of RBAC bugs when a specific lower-privilege permission needs to
be *excluded* from a higher role. Every role's permission set is
independently listed.

| Role | Where its permissions live |
|---|---|
| `candidate`, `recruiter` | Original V16 colon-namespaced `ROLE_PERMISSIONS` â€” unchanged |
| `recruiter_manager`, `recruiter_admin`, `support_admin`, `system_admin` | New V17.3 dot-namespaced `DOT_ROLE_PERMISSIONS` |
| `admin`, `super_admin` | Both catalogs â€” every colon-namespaced permission (unchanged, V16) *and* every dot-namespaced permission (V17.3, so a route migrated to the new style doesn't lose an existing admin/super_admin caller's access) |

## Why two permission-string conventions coexist

The colon-namespaced permissions (`jobs:manage_own`) were confirmed, before
this pass started, to not be consumed by any live route â€” renaming them
would have been free from a compatibility standpoint. But the brief for
this pass specified an exact set of dot-namespaced permission strings
(`jobs.create`, `users.read`, ...) and was equally explicit about not
rewriting existing code. Keeping both makes this pass's diff purely
additive: nothing that already depends on the colon-namespaced catalog
(see `tests/test_v16_hardening.py`) had to change.

## Permission resolution

```
effective_permissions_for_role(role, db) =
    static_default_permissions(role)
    âˆª {p | RolePermissionOverride(role, p, granted=True)}
    âˆ’ {p | RolePermissionOverride(role, p, granted=False)}
```

`db=None` (the original V16 call signature) skips the override lookup
entirely and returns just the static set â€” this keeps `has_permission`'s
original behavior unchanged for any caller that doesn't pass a session.

## RBAC middleware

Two permission-checking dependencies exist side by side:

- `require_permission(permission)` â€” V16, colon-namespaced, JWT-only,
  static-only (no DB overrides). Unchanged.
- `require_dot_permission(permission)` â€” V17.3, dot-namespaced,
  JWT-only, DB-override-aware.
- `require_permission_dual(permission)` â€” V17.3, the dependency actually
  used by every new `/admin/rbac/...` route. Dual-mode, mirroring
  `app.api.admin.guard`'s existing pattern exactly: the shared
  `X-Admin-Key` is a full bypass (the same "break-glass" treatment it
  already gets for the rest of `/admin/...`), or a logged-in user's JWT
  is checked against the *specific* permission via
  `has_dot_permission` (DB-override-aware).

Every new route validates, in order: authentication (is there a valid
key or token) â†’ for JWT auth, is the account active â†’ the specific
permission (not just "is this any kind of admin"). Resource-ownership
checks (e.g. "can this recruiter only edit their own job postings") were
already enforced by the existing recruiter/admin routes before this pass
and are untouched â€” Government Hub, Recruiter ATS, and every other
"do not touch" area's ownership logic is exactly as it was.

## What was reused, not rebuilt

The brief's checklist under "User Management" and "Session Management"
maps mostly onto mechanisms that already existed:

| Brief asks for | Implementation |
|---|---|
| Activate / Deactivate account | Existing `POST /admin/users/{id}/lock` (`permanent: true`) / `unlock` |
| Suspend / Unsuspend account | **New** â€” `POST /admin/rbac/users/{id}/suspend` / `unsuspend` (see `SESSION_MANAGEMENT.md` for why this is distinct from lock) |
| Approve / Reject recruiter | Existing `POST /admin/recruiters/{id}/approve` / `reject` â€” untouched |
| Reset password | **New** endpoint, but it calls the *existing* `_issue(db, user, purpose="reset_password")` OTP-issuance helper from `app/api/auth.py` â€” the same one `POST /auth/forgot-password` already uses. No second password-reset mechanism was built. |
| Force logout | **New** endpoint, but it calls the *existing* `revoke_all_sessions()` function in `app/core/sessions.py` â€” the same one the self-service `POST /auth/logout-all` already uses |
| Single-session revoke | Existing `POST /admin/sessions/{id}/revoke` â€” untouched, not duplicated |
| List a user's sessions | Existing `GET /admin/users/{id}/sessions` â€” untouched. New: `GET /admin/rbac/sessions` for a *system-wide* view across all users |
| Audit log viewer (pagination) | Existing `GET /admin/audit-logs` â€” untouched. New: `GET /admin/rbac/audit-logs/export` adds search/date-range/CSV/JSON on top, as an additional endpoint rather than a rewrite |

## Known scope boundaries

- No route outside the new `/admin/rbac/...` group was changed to require
  a specific dot-namespaced permission â€” Government Hub, Recruiter ATS,
  AI/Search/Notifications/Analytics routes are explicitly out of scope
  for this pass and were not touched.
- IP-based geolocation ("Country" in a session listing) is not
  implemented â€” no geo-IP service is configured or reachable from this
  codebase. The field is always returned as `null` rather than faked.
  See `SESSION_MANAGEMENT.md`.

