"""V16 — permission-based RBAC. Extended in V17.3 (see below).

CareerOS has always had *roles* (``User.role`` is one of "candidate",
"recruiter", "admin" — see ``app.models.domain.User`` and the
``require_admin``/``require_recruiter`` dependencies in
``app.core.security``). What it didn't have is a *permission* layer:
routes could only ask "is this role admin?", not "can this actor
moderate jobs?" — those happen to be the same question today only
because there's a single admin role. As soon as a second kind of
elevated account is needed (e.g. a read-only support/ops role that
can view audit logs but not delete data), a route-per-role check
can't express that without duplicating logic everywhere.

This module adds that layer without removing or changing
``require_admin``/``require_recruiter`` — both are kept as-is so
every existing route dependency keeps working unchanged. New routes
(and any route being touched anyway) should prefer
``require_permission(...)``.

Permissions are namespaced ``resource:action`` strings. The mapping
below is the single source of truth for what each role can do; adding
a permission to a role is a one-line change here, not a hunt through
route files.

--------------------------------------------------------------------
V17.3 additions (Enterprise RBAC / session management / admin panel)
--------------------------------------------------------------------

Everything above this point is unchanged from V16/V17.1 — the original
``ROLE_PERMISSIONS`` dict (colon-namespaced, e.g. "jobs:manage_own")
still exists exactly as it did, and ``permissions_for_role`` /
``has_permission`` / ``require_permission`` still work exactly as
before for anything already using them (see tests/test_v16_hardening.py).

New in V17.3:

- Four new roles (``recruiter_manager``, ``recruiter_admin``,
  ``support_admin``, ``system_admin``), sitting in the hierarchy
  between the existing ``recruiter``/``admin`` roles, each with its
  own permission set below. ``User.role`` is a plain string column
  (no DB-level enum) — see the V16/V14 precedent of adding new role
  and update_type *values* without a migration — so no schema change
  was needed to introduce these values.
- A **dot-namespaced** permission catalog (``PERMISSION_CATALOG``,
  e.g. "jobs.publish") alongside the pre-existing colon-namespaced one.
  Two conventions coexisting in one file is not an accident: the
  colon-namespaced permissions were never wired into a live route
  (confirmed before starting this pass — see PROJECT_STATUS.md), so
  changing their separator would have been free, but the brief for
  this pass was explicit about the exact dot-namespaced permission
  strings to implement (jobs.create, users.read, etc.) and equally
  explicit about not rewriting existing code. Renaming the old set to
  match would touch nothing that currently depends on it either way,
  but keeping both makes the diff for this pass purely additive rather
  than "also happened to rename an unrelated constant."
- **Database-backed permission overrides** (``RolePermissionOverride``)
  so an admin can grant a role a permission it doesn't have by default,
  or revoke one it does, without a code change — the "configurable
  permissions" and "add future permissions without changing business
  logic" requirements. The static catalogs above remain the *defaults*;
  ``effective_permissions_for_role`` merges them with any DB overrides.
- ``require_permission_dual`` — the same dual-mode auth pattern
  ``app.api.admin.guard`` already uses (shared admin key OR a logged-in
  user's JWT), extended to also check a specific dot-namespaced
  permission when authenticating via JWT. The shared key remains a
  full bypass (break-glass credential), matching how ``guard`` already
  treats it for the existing admin router.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.security import current_user
from app.models.domain import User

# Role -> permissions granted to that role. "admin" is deliberately
# listed explicitly (not "grant everything") so a permission that's
# added here without thinking about admin doesn't silently apply to
# every role by accident.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "candidate": {
        "applications:manage_own",
        "saved_jobs:manage_own",
        "resume:manage_own",
    },
    "recruiter": {
        "jobs:manage_own",
        "applicants:view_own_jobs",
        "applicants:update_status_own_jobs",
    },
    "admin": {
        "jobs:moderate",
        "jobs:publish",
        "jobs:reject",
        "jobs:delete",
        "users:manage_roles",
        "recruiters:approve",
        "partners:manage",
        "exam_prep:manage",
        "ingestion:trigger",
        "audit_logs:read",
        "recruitment_updates:manage",
    },
}
# V17.1 — super_admin is a distinct role/JWT claim from admin (separate
# login endpoint, separate audit trail), but has at least every
# permission admin has. Kept as an explicit copy (not "grant
# everything") for the same reason admin is listed explicitly above.
ROLE_PERMISSIONS["super_admin"] = set(ROLE_PERMISSIONS["admin"])


def permissions_for_role(role: str) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set())


def has_permission(user: User, permission: str) -> bool:
    return permission in permissions_for_role(user.role)


def require_permission(permission: str):
    """Dependency factory: ``Depends(require_permission("jobs:publish"))``.

    Unlike ``require_admin``, this checks a specific permission rather
    than a hardcoded role, so it stays correct if a role's
    capabilities change or a new role is introduced later.
    """

    def _dependency(user: User = Depends(current_user)) -> User:
        if not has_permission(user, permission):
            raise HTTPException(403, f"Missing required permission: {permission}")
        return user

    return _dependency


# ============================= V17.3 ================================

# Role hierarchy, weakest to strongest, for admin-UI display only (not
# used for permission checks — those are always set-membership, not
# a numeric comparison, so a role's *specific* permissions can't
# accidentally be widened by a hierarchy bug).
ROLE_HIERARCHY: list[str] = [
    "candidate",
    "recruiter",
    "recruiter_manager",
    "recruiter_admin",
    "support_admin",
    "system_admin",
    "super_admin",
]

# The dot-namespaced permission catalog this pass's brief specified,
# plus the additional resource.action strings the new admin-panel
# endpoints in app.api.admin_rbac need (sessions.*, roles.*,
# permissions.*, users.* beyond read/update/delete). Every permission
# actually enforced anywhere is listed here — this is the "system must
# support adding future permissions without changing business logic"
# registry: add a string here and to a role's set below, no route code
# changes needed unless the *route* is new too.
PERMISSION_CATALOG: dict[str, str] = {
    "jobs.create": "Create a job posting",
    "jobs.update": "Edit a job posting",
    "jobs.delete": "Delete a job posting",
    "jobs.publish": "Publish a job posting from the review queue",
    "jobs.review": "View/moderate the job review queue",
    "users.read": "View user accounts",
    "users.update": "Edit a user account",
    "users.delete": "Delete a user account",
    "recruiters.approve": "Approve or reject a pending recruiter registration",
    "applications.review": "View/update applicant status for a job",
    "applications.export": "Export applicant/application data",
    "admin.audit.read": "Read the audit log",
    "government.publish": "Publish a government job posting",
    "government.review": "Review government-sourced ingestion records",
    "analytics.read": "View analytics/metrics",
    "notifications.send": "Trigger outbound notifications",
    # Admin-panel permissions this pass adds routes for.
    "roles.manage": "Grant/revoke permissions for a role",
    "permissions.read": "View the permission catalog",
    "sessions.read": "View any user's active sessions",
    "sessions.revoke": "Revoke any user's session(s)",
    "users.suspend": "Suspend/unsuspend a user account",
    "users.reset_password": "Trigger a password reset for a user",
}

# Default role -> dot-namespaced permission grants. A role not listed
# here (e.g. "candidate", "recruiter") has no dot-namespaced
# permissions by default — they're governed by the colon-namespaced
# ``ROLE_PERMISSIONS`` above instead, unchanged from V16.
DOT_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "recruiter_manager": {
        "jobs.create",
        "jobs.update",
        "applications.review",
    },
    "recruiter_admin": {
        "jobs.create",
        "jobs.update",
        "jobs.delete",
        "applications.review",
        "applications.export",
    },
    "support_admin": {
        "users.read",
        "sessions.read",
        "admin.audit.read",
        "recruiters.approve",
        "users.reset_password",
    },
    "system_admin": {
        "jobs.create", "jobs.update", "jobs.delete", "jobs.publish", "jobs.review",
        "users.read", "users.update", "users.suspend",
        "recruiters.approve",
        "applications.review", "applications.export",
        "admin.audit.read",
        "government.publish", "government.review",
        "analytics.read",
        "notifications.send",
        "roles.manage", "permissions.read",
        "sessions.read", "sessions.revoke",
    },
}
# admin/super_admin already exist as roles (V9/V17.1) — extend them
# with every dot-namespaced permission too, so a request authenticated
# as one of those roles doesn't lose capability just because a given
# route was migrated to the new permission style.
DOT_ROLE_PERMISSIONS["admin"] = set(PERMISSION_CATALOG.keys())
DOT_ROLE_PERMISSIONS["super_admin"] = set(PERMISSION_CATALOG.keys())


def _static_dot_permissions_for_role(role: str) -> set[str]:
    return set(DOT_ROLE_PERMISSIONS.get(role, set()))


def effective_permissions_for_role(role: str, db: Session | None = None) -> set[str]:
    """Static default permissions for `role`, merged with any DB
    overrides. Passing no `db` (the V16 call sites' original contract)
    returns just the static set — this keeps `has_permission`'s
    original signature/behavior intact for anything that doesn't know
    about overrides yet.
    """
    perms = _static_dot_permissions_for_role(role)
    if db is None:
        return perms

    from app.models.domain import RolePermissionOverride  # local import avoids a module-load cycle

    for override in db.query(RolePermissionOverride).filter(RolePermissionOverride.role == role).all():
        if override.granted:
            perms.add(override.permission)
        else:
            perms.discard(override.permission)
    return perms


def has_dot_permission(user: User, permission: str, db: Session | None = None) -> bool:
    return permission in effective_permissions_for_role(user.role, db)


def require_dot_permission(permission: str):
    """Like ``require_permission`` but for the V17.3 dot-namespaced
    catalog, and DB-override-aware (so a grant made via
    ``POST /admin/rbac/roles/{role}/grant`` takes effect immediately,
    no restart/redeploy needed)."""

    def _dependency(user: User = Depends(current_user), db: Session = Depends(_get_db)) -> User:
        if not has_dot_permission(user, permission, db):
            raise HTTPException(403, f"Missing required permission: {permission}")
        return user

    return _dependency


def _get_db():
    # Local import to avoid a module-load-order cycle with app.db.session
    # (which does not itself import this module, so this is precautionary
    # rather than a known cycle, but keeps this file's only hard
    # dependencies at import time to app.core.security/app.models.domain,
    # matching how the rest of this file was already structured).
    from app.db.session import get_db

    yield from get_db()


def require_permission_dual(permission: str):
    """Dual-mode dependency for the new admin-panel routes: accepts
    *either* the shared ``X-Admin-Key`` (full bypass, same as
    ``app.api.admin.guard`` — the master key is treated as "can do
    anything" everywhere else in this codebase, so it is here too) or
    a logged-in user's JWT, in which case the specific `permission` is
    checked via ``has_dot_permission`` (DB-override-aware).
    """

    async def _dependency(
        x_admin_key: str = Header(default=""),
        authorization: str = Header(default=""),
        db: Session = Depends(_get_db),
    ) -> None:
        from app.core.config import settings
        from app.core.hardening import safe_equals
        from app.core.request_context import Actor, set_actor
        from app.core.security import access_token_session_is_active, decode_access_token

        if authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
            try:
                claims = decode_access_token(token)
                user = db.get(User, int(claims["sub"]))
                # V25.6: revoked session -> token rejected.
                if user is not None and not access_token_session_is_active(db, claims):
                    user = None
            except Exception:
                user = None
            if not user or not user.active:
                raise HTTPException(401, "Invalid or expired token")
            if not has_dot_permission(user, permission, db):
                raise HTTPException(403, f"Missing required permission: {permission}")
            set_actor(Actor(actor_type="user", actor_id=str(user.id), label=user.email))
            return

        if not settings.admin_key_auth_enabled or not x_admin_key or not safe_equals(x_admin_key, settings.admin_api_key):
            raise HTTPException(401, "Admin authentication required")
        set_actor(Actor(actor_type="admin_key", actor_id=None, label="shared admin key"))

    return _dependency
