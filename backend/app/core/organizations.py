"""V25.1 — Multi-Tenant Architecture & Organization Management.

Centralized authorization for every organization-scoped resource,
matching this codebase's existing pattern of one module owning one
concern (``app.core.rbac`` for platform permissions, ``app.core.team_access``
for the pre-existing job-sharing resolution — this module for the new
formal Organization/OrganizationMember RBAC).

THE SECURITY RULE THIS MODULE EXISTS TO ENFORCE (spec sections 8/21):

    The authenticated user's organization MEMBERSHIP determines
    access — never an ``organization_id`` supplied by the client,
    whether in the URL path, a request body, or a header.

Every dependency below re-derives membership from the database on
every request using the path's ``organization_id`` only as a lookup
key, then checks it against the current user — it never trusts the
caller's claim about what role/org they're in. A request for
``/organizations/{organization_id}/...`` where the authenticated user
has no ACTIVE membership in that exact organization_id fails closed
(404, not 403, for the top-level "does this org exist for you" check,
matching this codebase's existing convention elsewhere of not
confirming a resource's existence to an unauthorized caller — see
e.g. ``app.api.company._owned_company_or_404``).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import current_user
from app.db.session import get_db
from app.models.domain import Organization, OrganizationMember, User

# Every valid role, weakest to strongest — used only for documentation
# and the one explicit hierarchy check in `require_organization_role`
# (OWNER implicitly satisfies an ADMIN/RECRUITER requirement and so
# on). Actual permission *grants* below are still explicit sets, not a
# numeric comparison, matching app.core.rbac's ROLE_HIERARCHY docstring
# rationale: a role's specific permissions should never be widenable by
# a hierarchy bug.
ROLES: tuple[str, ...] = ("OWNER", "ADMIN", "RECRUITER")
_ROLE_RANK: dict[str, int] = {role: i for i, role in enumerate(reversed(ROLES))}  # RECRUITER=0, ADMIN=1, OWNER=2

STATUSES: tuple[str, ...] = ("PENDING", "ACTIVE", "SUSPENDED", "REMOVED")


def get_active_membership(db: Session, organization_id: int, user_id: int) -> OrganizationMember | None:
    """The user's membership row for this org, if ACTIVE. Deliberately
    returns None (not the row) for PENDING/SUSPENDED/REMOVED — every
    caller in this module treats "not an active member" as a single
    outcome, matching spec section 30's requirement that a suspended
    or removed member's access fails exactly like a non-member's."""
    return db.scalars(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == "ACTIVE",
        )
    ).first()


def user_organization_ids(db: Session, user_id: int) -> list[int]:
    """Every organization_id this user is an ACTIVE member of — backs
    the organization switcher (spec section 7) and `GET /organizations`."""
    rows = db.scalars(
        select(OrganizationMember.organization_id).where(
            OrganizationMember.user_id == user_id, OrganizationMember.status == "ACTIVE"
        )
    ).all()
    return list(rows)


def organization_member_user_ids(db: Session, organization_id: int) -> list[int]:
    """Every user_id with ACTIVE membership in this organization.
    This is the org-aware resource-scoping primitive: consumed by
    `app.core.team_access.team_owner_ids` so every existing
    job/candidate/pipeline/analytics/AI query that already filters by
    that function's output becomes organization-isolated for free once
    an organization has a backfilled/created OrganizationMember set."""
    rows = db.scalars(
        select(OrganizationMember.user_id).where(
            OrganizationMember.organization_id == organization_id, OrganizationMember.status == "ACTIVE"
        )
    ).all()
    return list(rows)


def _get_db_dep():
    yield from get_db()


def require_organization_membership(
    organization_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(_get_db_dep),
) -> tuple[Organization, OrganizationMember]:
    """Base dependency: any ACTIVE role in the path's organization_id.
    Returns (organization, membership) so route handlers that need
    either don't have to look them up again. Every stronger dependency
    below (`require_organization_role`, `_admin`, `_owner`) builds on
    this — there is exactly one place that resolves "is this user in
    this org at all", per spec section 12's "centralize, don't repeat
    authorization logic in every route"."""
    org = db.get(Organization, organization_id)
    if org is None or not org.is_active:
        # V25.2 — `is_active` is False for a platform-suspended
        # organization too (see app.core.platform_lifecycle), so a
        # suspension takes effect through this one pre-existing check
        # rather than needing a second one added to every route. The
        # member is told only that the organization is unavailable;
        # the moderation reason is internal (spec section 7: a
        # suspension must not leak information through notifications
        # or errors).
        raise HTTPException(404, "Organization not found")
    membership = get_active_membership(db, organization_id, user.id)
    if membership is None:
        # 404, not 403 — do not confirm to a non-member that this
        # organization_id exists and has resources (spec section 8:
        # cross-tenant IDOR probing must fail exactly like a
        # nonexistent ID, not leak existence via a different status).
        #
        # V25.2 — the attempt is recorded as a security event so
        # cross-tenant probing is investigable (spec section 23). The
        # response is unchanged; only the audit trail is richer.
        _record_cross_tenant_attempt(db, user, organization_id)
        raise HTTPException(404, "Organization not found")
    return org, membership


def _record_cross_tenant_attempt(db: Session, user: User, organization_id: int) -> None:
    """Best-effort security-event logging for a cross-tenant access
    attempt. Never allowed to change the outcome of the request: the
    404 is raised by the caller whether or not this succeeds."""
    try:
        from app.core.security_events import SecurityEvent, record_security_event

        record_security_event(
            db,
            SecurityEvent.CROSS_TENANT_ACCESS_ATTEMPT,
            entity_type="organization",
            entity_id=str(organization_id),
            detail=f"user_id={user.id} has no active membership",
        )
        db.commit()
    except Exception:  # pragma: no cover - defensive
        db.rollback()


def require_organization_role(*roles: str):
    """Dependency factory requiring one of `roles` (or anything that
    ranks higher — OWNER always satisfies an ADMIN/RECRUITER
    requirement). Use this directly for anything narrower than the
    three convenience dependencies below."""
    minimum_rank = min(_ROLE_RANK[r] for r in roles)

    def _dependency(
        resolved: tuple[Organization, OrganizationMember] = Depends(require_organization_membership),
    ) -> tuple[Organization, OrganizationMember]:
        org, membership = resolved
        if _ROLE_RANK.get(membership.role, -1) < minimum_rank:
            raise HTTPException(403, f"Requires one of: {', '.join(roles)}")
        return org, membership

    return _dependency


def require_organization_admin(
    resolved: tuple[Organization, OrganizationMember] = Depends(require_organization_role("OWNER", "ADMIN")),
) -> tuple[Organization, OrganizationMember]:
    return resolved


def require_organization_owner(
    resolved: tuple[Organization, OrganizationMember] = Depends(require_organization_role("OWNER")),
) -> tuple[Organization, OrganizationMember]:
    return resolved


def can_manage_role(actor_role: str, target_role: str) -> bool:
    """Section 25's privilege-escalation tests, as a single reusable
    rule rather than ad-hoc checks per endpoint:

    - Only OWNER may grant or revoke the OWNER role, or change the
      role of an existing OWNER (prevents ADMIN -> OWNER escalation
      and prevents an ADMIN from demoting an OWNER out of spite/bug).
    - ADMIN may manage RECRUITER <-> ADMIN, but never OWNER.
    - RECRUITER may not manage anyone (callers never reach here for a
      RECRUITER actor — `require_organization_admin` already blocks
      it — this function is the second, defense-in-depth layer).
    """
    if actor_role == "OWNER":
        return True
    if actor_role == "ADMIN":
        return target_role != "OWNER"
    return False


def ensure_not_last_owner(db: Session, organization_id: int, member: OrganizationMember) -> None:
    """Spec section 4/25: the final OWNER can't remove themselves (or
    be demoted/removed by anyone) without first transferring
    ownership. Ownership transfer isn't implemented in this phase
    (spec explicitly scopes that as optional/deferred), so today this
    simply blocks the action outright rather than silently leaving an
    organization ownerless."""
    if member.role != "OWNER":
        return
    other_owners = db.scalars(
        select(OrganizationMember.id).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.role == "OWNER",
            OrganizationMember.status == "ACTIVE",
            OrganizationMember.id != member.id,
        )
    ).first()
    if other_owners is None:
        raise HTTPException(
            409,
            "This is the organization's only owner. Promote another member to OWNER before removing "
            "or changing this membership.",
        )


def sync_legacy_membership(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    role: str,
    invited_by: int | None = None,
    remove: bool = False,
) -> None:
    """Keeps the new `OrganizationMember` table in sync with writes
    made through the pre-existing, unmodified V18.4
    `CompanyTeamMember` endpoints (`app.api.company`'s
    `invite_team_member` / `remove_team_member` / `_ensure_owner_membership`),
    so a recruiter who only ever uses the legacy team roster still
    gets correct, isolated org-scoped access under V25.1 without
    redoing anything. Does not commit — callers control the
    transaction boundary, matching every other helper in this
    codebase (see app.core.audit.log_audit's docstring)."""
    existing = db.scalars(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id, OrganizationMember.user_id == user_id
        )
    ).first()

    if remove:
        if existing is not None and existing.status != "REMOVED":
            existing.status = "REMOVED"
            existing.updated_at = datetime.utcnow()
        return

    if existing is None:
        db.add(
            OrganizationMember(
                organization_id=organization_id,
                user_id=user_id,
                role=role,
                status="ACTIVE",
                invited_by=invited_by,
                joined_at=datetime.utcnow(),
            )
        )
    elif existing.status != "ACTIVE" or existing.role != role:
        existing.status = "ACTIVE"
        existing.role = role
        existing.joined_at = existing.joined_at or datetime.utcnow()
        existing.updated_at = datetime.utcnow()
