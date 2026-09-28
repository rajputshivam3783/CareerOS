"""V25.2 — Platform-administrator authorization.

THE ONE RULE THIS MODULE EXISTS TO ENFORCE
------------------------------------------

    Platform administration and organization administration are two
    separate authority systems. Holding OWNER or ADMIN inside an
    organization grants *nothing* at the platform level, and no
    organization-scoped role can ever be escalated into one.

That separation is structural, not a check that could be forgotten:
platform authority is derived exclusively from ``User.role`` (the
platform account role — "admin"/"super_admin"/"support_admin"/
"system_admin"), while organization authority is derived exclusively
from an ``OrganizationMember`` row (OWNER/ADMIN/RECRUITER). The two
are read from different tables by different modules
(``app.core.organizations`` owns the other one) and this module never
consults membership at all. There is therefore no code path in which
promoting someone to OWNER of an organization changes what
``require_platform_permission`` returns.

WHY NOT JUST REUSE app.core.rbac?
---------------------------------

``app.core.rbac`` already has a dot-namespaced permission catalog and
``require_permission_dual``, and this module deliberately *builds on*
it rather than replacing it — ``PLATFORM_ROLE_PERMISSIONS`` below is
derived from the same ``User.role`` values that module already knows
about, and nothing in rbac.py is modified. What rbac.py does not have
is a coarse, auditable notion of "platform capability area" (the seven
domains spec section 2 asks for: user management, organization
management, job moderation, content moderation, audit access,
analytics, system configuration). Its catalog is per-endpoint-action
("sessions.revoke", "jobs.publish"); this is per-domain. Expressing
the governance surface in terms of 30-odd endpoint-level permission
strings would have made "can this account administer the platform at
all?" — the single question every route in app.api.admin_platform has
to answer — into a set union computed at every call site.

The two layers coexist cleanly because they answer different
questions, and both ultimately key off the same ``User.role``:
adding a new platform role means adding one entry to
``PLATFORM_ROLE_PERMISSIONS`` here, and (if it also needs
endpoint-level grants) one to ``DOT_ROLE_PERMISSIONS`` there. Neither
file has to know about the other's contents.

EXTENSIBILITY
-------------

Spec section 2 asks for a model that supports PLATFORM_ADMIN at
minimum, structures permissions internally for future roles, and does
not over-engineer a full enterprise RBAC system. That is exactly the
shape below: one dict mapping a platform role to its permission set,
with three roles pre-wired (the two that already existed, plus the two
V17.3 half-admin roles mapped to the subsets they already
semantically had). A new role is one line. A new permission is one
constant plus its grants.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.hardening import safe_equals
from app.core.rate_limit import enforce_rate_limit
from app.core.request_context import Actor, set_actor
from app.core.security import access_token_session_is_active, decode_access_token
from app.db.session import get_db
from app.models.domain import User


class PlatformPermission:
    """The platform capability domains (spec section 2).

    A plain class of string constants rather than an Enum so the
    values serialize as-is into API responses, audit rows and the
    frontend's permission-aware navigation without an intermediate
    ``.value`` everywhere — matching how ``app.core.rbac``'s catalogs
    are already plain strings.
    """

    USER_MANAGEMENT = "USER_MANAGEMENT"
    ORGANIZATION_MANAGEMENT = "ORGANIZATION_MANAGEMENT"
    JOB_MODERATION = "JOB_MODERATION"
    CONTENT_MODERATION = "CONTENT_MODERATION"
    AUDIT_ACCESS = "AUDIT_ACCESS"
    PLATFORM_ANALYTICS = "PLATFORM_ANALYTICS"
    SYSTEM_CONFIGURATION = "SYSTEM_CONFIGURATION"


ALL_PLATFORM_PERMISSIONS: tuple[str, ...] = (
    PlatformPermission.USER_MANAGEMENT,
    PlatformPermission.ORGANIZATION_MANAGEMENT,
    PlatformPermission.JOB_MODERATION,
    PlatformPermission.CONTENT_MODERATION,
    PlatformPermission.AUDIT_ACCESS,
    PlatformPermission.PLATFORM_ANALYTICS,
    PlatformPermission.SYSTEM_CONFIGURATION,
)

PERMISSION_DESCRIPTIONS: dict[str, str] = {
    PlatformPermission.USER_MANAGEMENT: "View, search, suspend and reactivate platform user accounts",
    PlatformPermission.ORGANIZATION_MANAGEMENT: "View, search, suspend and reactivate organizations",
    PlatformPermission.JOB_MODERATION: "Review, approve, reject, suspend and restore job postings",
    PlatformPermission.CONTENT_MODERATION: "Publish platform announcements and moderate platform content",
    PlatformPermission.AUDIT_ACCESS: "Read the platform audit log and security events",
    PlatformPermission.PLATFORM_ANALYTICS: "View aggregate platform analytics",
    PlatformPermission.SYSTEM_CONFIGURATION: "View system health and change platform settings",
}

# Platform roles are values of ``User.role`` — the same column
# app.core.security and app.core.rbac already read. An organization
# role (OWNER/ADMIN/RECRUITER, stored in organization_members) is
# never a key here and can never become one: nothing writes
# OrganizationMember.role into User.role, and the only endpoint that
# can change User.role at all is the admin-guarded
# POST /admin/users/{id}/role.
PLATFORM_ROLE_PERMISSIONS: dict[str, set[str]] = {
    # The two pre-existing full platform-admin roles (V9 / V17.1).
    "admin": set(ALL_PLATFORM_PERMISSIONS),
    "super_admin": set(ALL_PLATFORM_PERMISSIONS),
    # V17.3 introduced these two as intermediate elevated roles with
    # narrower endpoint-level grants (see app.core.rbac's
    # DOT_ROLE_PERMISSIONS). Mapped here to the platform domains that
    # match the grants they already had, so this version gives them
    # no capability they did not already possess.
    "system_admin": {
        PlatformPermission.USER_MANAGEMENT,
        PlatformPermission.ORGANIZATION_MANAGEMENT,
        PlatformPermission.JOB_MODERATION,
        PlatformPermission.CONTENT_MODERATION,
        PlatformPermission.AUDIT_ACCESS,
        PlatformPermission.PLATFORM_ANALYTICS,
    },
    "support_admin": {
        PlatformPermission.USER_MANAGEMENT,
        PlatformPermission.AUDIT_ACCESS,
    },
}

# Changing platform settings, toggling maintenance mode and changing a
# user's platform role are the actions with the widest blast radius on
# the platform, so they are restricted further than SYSTEM_CONFIGURATION
# alone (spec section 26).
SENSITIVE_ACTION_ROLES: frozenset[str] = frozenset({"admin", "super_admin"})


@dataclass(frozen=True)
class PlatformActor:
    """Who is performing a platform-admin action.

    ``user`` is None only for the shared ``X-Admin-Key`` break-glass
    credential, which has no user row. Every route handler receives
    this rather than a bare ``User`` so it can record the actor in the
    platform audit trail without re-deriving it from request context,
    and so the break-glass path is explicit in the type rather than a
    surprising None.
    """

    actor_type: str  # "user" | "admin_key"
    label: str
    user: User | None = None
    permissions: frozenset[str] = frozenset()

    @property
    def user_id(self) -> int | None:
        return self.user.id if self.user is not None else None

    @property
    def role(self) -> str | None:
        return self.user.role if self.user is not None else None

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def can_perform_sensitive_action(self) -> bool:
        if self.actor_type == "admin_key":
            return True
        return self.role in SENSITIVE_ACTION_ROLES


def platform_permissions_for_role(role: str | None) -> set[str]:
    """The platform permissions a ``User.role`` value grants.

    An unknown role — including every organization role name, every
    candidate/recruiter role, and any string someone manages to get
    into the column — returns the empty set. This function fails
    closed by construction: there is no wildcard branch.
    """
    if not role:
        return set()
    return set(PLATFORM_ROLE_PERMISSIONS.get(role, set()))


def is_platform_admin(user: User | None) -> bool:
    """True iff this account holds *any* platform permission.

    Note what is deliberately absent: no ``db`` parameter, and no
    lookup of organization membership. A caller cannot accidentally
    pass an organization context that would widen the answer.
    """
    if user is None or not user.active:
        return False
    return bool(platform_permissions_for_role(user.role))


def _get_db_dep():
    yield from get_db()


def _actor_from_bearer(authorization: str, db: Session) -> PlatformActor | None:
    """Resolve a Bearer token to a platform actor, or None if the
    token is absent/invalid/not a platform administrator.

    Returns None rather than raising so the caller decides the status
    code and can record the refusal as a security event with the right
    context.
    """
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_access_token(token)
        user = db.get(User, int(claims["sub"]))
        # V25.6: revoked session -> token rejected.
        if user is not None and not access_token_session_is_active(db, claims):
            return None
    except Exception:
        return None
    if user is None or not user.active:
        return None
    permissions = platform_permissions_for_role(user.role)
    if not permissions:
        # A perfectly valid session — for a candidate, a recruiter, or
        # an organization OWNER/ADMIN. Valid, and not a platform
        # administrator. This is the single point at which the
        # platform/organization separation is enforced for JWT auth.
        return PlatformActor(actor_type="user", label=user.email, user=user, permissions=frozenset())
    return PlatformActor(
        actor_type="user", label=user.email, user=user, permissions=frozenset(permissions)
    )


def require_platform_permission(permission: str):
    """Dependency factory: the platform-admin gate for every route in
    ``app.api.admin_platform``.

    Dual-mode, matching the credential model the rest of the admin
    surface has used since V16 (``app.api.admin.guard``): either the
    shared ``X-Admin-Key`` break-glass credential (rate-limited, and a
    full bypass — it is treated as "can do anything" everywhere else
    in this codebase, so treating it differently here would only make
    the security model inconsistent, not stronger) or a normal
    ``Authorization: Bearer`` JWT, which must belong to an account
    whose ``User.role`` grants `permission`.

    Reuses the existing authentication system rather than adding a
    second one (spec section 25): the token is the same token
    /auth/login issues, verified with the same secret, and a
    deactivated/suspended account fails here exactly as it does on
    every other authenticated endpoint because ``User.active`` is
    checked identically.

    A denied JWT request is recorded as a security event
    (PRIVILEGE_ESCALATION_ATTEMPT) before the 403 is raised, so a
    recruiter or organization owner probing /admin leaves an
    investigable trail — which is the entire point of spec section 23.
    """

    async def _dependency(
        request: Request,
        x_admin_key: str = Header(default=""),
        authorization: str = Header(default=""),
        db: Session = Depends(_get_db_dep),
    ) -> PlatformActor:
        # Must stay `async def`, not a plain `def`. FastAPI dispatches a
        # sync dependency via run_in_threadpool, which executes it inside
        # an independent contextvars.copy_context() — a set_actor() call
        # made there would never be visible to the endpoint body. An
        # async dependency runs in the request's own task, so the actor
        # it sets is present for app.core.audit.log_audit later in the
        # same request. This is the same constraint documented on
        # app.core.security.current_user, and the same shape
        # app.core.rbac.require_permission_dual already uses.
        if authorization.lower().startswith("bearer "):
            actor = _actor_from_bearer(authorization, db)
            if actor is None:
                raise HTTPException(401, "Invalid or expired token")
            if not actor.has(permission):
                # Attribute the event to the account that attempted it
                # before recording, so the audit row names them rather
                # than showing an anonymous actor. This is the only
                # place set_actor is called for a request that is about
                # to be refused.
                set_actor(Actor(actor_type="user", actor_id=str(actor.user_id), label=actor.label))
                _record_denied_platform_access(db, actor, permission, request)
                raise HTTPException(403, "Platform administrator access required")
            set_actor(Actor(actor_type="user", actor_id=str(actor.user_id), label=actor.label))
            return actor

        # Break-glass shared key. Rate-limited so a wrong key can't be
        # brute-forced (same bucket app.api.admin.guard already uses).
        enforce_rate_limit(request, bucket="admin-key")
        if not settings.admin_key_auth_enabled or not x_admin_key or not safe_equals(x_admin_key, settings.admin_api_key):
            raise HTTPException(401, "Platform administrator authentication required")
        set_actor(Actor(actor_type="admin_key", actor_id=None, label="shared admin key"))
        return PlatformActor(
            actor_type="admin_key",
            label="shared admin key",
            user=None,
            permissions=frozenset(ALL_PLATFORM_PERMISSIONS),
        )

    return _dependency


def _record_denied_platform_access(db: Session, actor: PlatformActor, permission: str, request: Request) -> None:
    """Log an authenticated non-administrator's attempt to reach a
    platform-admin endpoint.

    Best-effort by design: a failure to write the security event must
    never turn a clean 403 into a 500, and must never be the reason a
    refusal doesn't happen. The refusal is raised by the caller
    regardless of what happens in here.
    """
    try:
        from app.core.security_events import SecurityEvent, record_security_event

        record_security_event(
            db,
            SecurityEvent.PRIVILEGE_ESCALATION_ATTEMPT,
            entity_type="user",
            entity_id=str(actor.user_id) if actor.user_id else None,
            # Role and requested permission only — no token, no
            # headers, nothing that could carry a credential.
            detail=f"role={actor.role} requested={permission} path={request.url.path}",
        )
        db.commit()
    except Exception:  # pragma: no cover - defensive, see docstring
        db.rollback()


def require_sensitive_platform_action(actor: PlatformActor) -> None:
    """Second gate for the highest-impact actions (spec section 26).

    Called from inside a handler rather than as a dependency because
    for some endpoints only *certain* payloads are sensitive (changing
    a setting flagged sensitive vs. one that isn't), so the check
    needs the parsed body.
    """
    if not actor.can_perform_sensitive_action():
        raise HTTPException(403, "This action requires a full platform administrator role")
