"""V25.1 — Multi-Tenant Architecture & Organization Management.

New, additive API surface for the formal Organization/OrganizationMember
RBAC introduced this version (see app.models.domain and
app.core.organizations). Deliberately does NOT replace or modify
app.api.company's pre-existing V18.1/V18.4 endpoints
(GET/PUT /recruiter/company, GET/POST/DELETE /recruiter/company/team/...)
— those keep working exactly as before (see
app.core.organizations.sync_legacy_membership for how the two stay
consistent).

Every route that touches a specific organization takes
``organization_id`` from the URL path and resolves the caller's role in
THAT organization from the database via
``app.core.organizations.require_organization_*`` — never from a
client-supplied claim (spec section 8/21). Every mutation that matters
is recorded on the existing platform-wide ``audit_logs`` table via
``app.core.audit.log_audit`` (entity_type="organization", entity_id=the
organization id, detail=a JSON blob with the specific action's
target/metadata) rather than a new dedicated audit table — this reuses
the same, already-correct actor/request-id/IP attribution every other
subsystem gets for free, instead of duplicating that machinery (see
spec section 19's "do not store unnecessary sensitive payloads": the
existing table already has exactly the right shape).
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.validators import http_url_validator
from app.core.audit import log_audit
from app.core.config import settings
from app.core.organizations import (
    ROLES,
    can_manage_role,
    ensure_not_last_owner,
    require_organization_admin,
    require_organization_membership,
    user_organization_ids,
)
from app.core.security import current_user, require_recruiter
from app.db.session import get_db
from app.email.service import queue_email
from app.models.domain import AuditLog, Organization, OrganizationInvitation, OrganizationMember, User

router = APIRouter()

INVITATION_EXPIRY_DAYS = 7


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class OrganizationIn(BaseModel):
    name: str = Field(min_length=2, max_length=220)
    description: str | None = Field(default=None, max_length=4000)
    website: str | None = Field(default=None, max_length=1000)
    industry: str | None = Field(default=None, max_length=120)
    company_size: str | None = Field(default=None, max_length=40)
    location: str | None = Field(default=None, max_length=220)
    logo_url: str | None = Field(default=None, max_length=1000)
    _validate_urls = http_url_validator("website", "logo_url", assume_https=True)


class OrganizationUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=220)
    description: str | None = Field(default=None, max_length=4000)
    website: str | None = Field(default=None, max_length=1000)
    industry: str | None = Field(default=None, max_length=120)
    company_size: str | None = Field(default=None, max_length=40)
    location: str | None = Field(default=None, max_length=220)
    logo_url: str | None = Field(default=None, max_length=1000)
    _validate_urls = http_url_validator("website", "logo_url", assume_https=True)


class InviteMemberIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = Field(default="RECRUITER")

    @field_validator("role")
    @classmethod
    def role_must_be_known(cls, value: str) -> str:
        value = value.upper()
        if value not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        return value


class RoleChangeIn(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def role_must_be_known(cls, value: str) -> str:
        value = value.upper()
        if value not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        return value


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:140].rstrip("-")
    return f"{slug}-{secrets.token_hex(4)}"


def _org_out(org: Organization, membership: OrganizationMember | None = None) -> dict:
    out = {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "description": org.description,
        "website": org.website,
        "industry": org.industry,
        "company_size": org.company_size,
        "location": org.location,
        "logo_url": org.logo_url,
        "is_active": org.is_active,
        "created_at": org.created_at,
        "updated_at": org.updated_at,
    }
    if membership is not None:
        out["my_role"] = membership.role
    return out


def _member_out(member: OrganizationMember, user: User | None) -> dict:
    return {
        "id": member.id,
        "user_id": member.user_id,
        "name": user.full_name if user else None,
        "email": user.email if user else None,
        "role": member.role,
        "status": member.status,
        "invited_by": member.invited_by,
        "joined_at": member.joined_at,
        "created_at": member.created_at,
    }


def _audit(db: Session, organization_id: int, action: str, target_type: str | None = None,
           target_id: str | None = None, **metadata) -> None:
    detail = json.dumps({"target_type": target_type, "target_id": target_id, **metadata}, default=str)
    log_audit(db, f"organization.{action}", "organization", str(organization_id), detail=detail)


# ---------------------------------------------------------------------------
# Organization CRUD (spec sections 5, 17, 20)
# ---------------------------------------------------------------------------


@router.post("/organizations", status_code=201)
def create_organization(
    payload: OrganizationIn, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)
):
    """Creates an organization AND its OWNER membership atomically
    (spec section 5): if anything below fails, the whole transaction
    rolls back rather than leaving a partial/ownerless organization —
    the `db.commit()` at the end is the only commit point; every
    failure path before it re-raises without committing."""
    if db.scalars(select(Organization).where(Organization.name == payload.name)).first():
        raise HTTPException(409, "An organization with this name already exists")

    org = Organization(
        name=payload.name,
        slug=_slugify(payload.name),
        description=payload.description,
        website=payload.website,
        industry=payload.industry,
        company_size=payload.company_size,
        location=payload.location,
        logo_url=payload.logo_url,
        owner_user_id=recruiter.id,
        created_by=recruiter.id,
        is_active=True,
    )
    db.add(org)
    db.flush()  # obtain org.id inside the same transaction, before commit

    membership = OrganizationMember(
        organization_id=org.id,
        user_id=recruiter.id,
        role="OWNER",
        status="ACTIVE",
        joined_at=datetime.utcnow(),
    )
    db.add(membership)
    _audit(db, org.id, "created", target_type="organization", target_id=str(org.id), name=org.name)
    db.commit()
    db.refresh(org)
    return _org_out(org, membership)


@router.get("/organizations")
def list_my_organizations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Every organization the caller is an ACTIVE member of — backs
    the organization switcher (spec section 7)."""
    org_ids = user_organization_ids(db, user.id)
    if not org_ids:
        return []
    memberships = {
        m.organization_id: m
        for m in db.scalars(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id, OrganizationMember.organization_id.in_(org_ids)
            )
        ).all()
    }
    orgs = db.scalars(select(Organization).where(Organization.id.in_(org_ids))).all()
    return [_org_out(o, memberships.get(o.id)) for o in orgs]


@router.get("/organizations/{organization_id}")
def get_organization(resolved: tuple = Depends(require_organization_membership)):
    org, membership = resolved
    return _org_out(org, membership)


@router.patch("/organizations/{organization_id}")
def update_organization(
    payload: OrganizationUpdateIn,
    resolved: tuple = Depends(require_organization_admin),
    db: Session = Depends(get_db),
):
    """OWNER/ADMIN only (spec section 17). Never accepts owner,
    organization id, or any internal audit field — this schema simply
    has no such fields, so there is nothing to reject at runtime."""
    org, membership = resolved
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(org, field, value)
    org.updated_at = datetime.utcnow()
    if changes:
        _audit(db, org.id, "settings_changed", target_type="organization", target_id=str(org.id), changed=list(changes))
    db.commit()
    db.refresh(org)
    return _org_out(org, membership)


# ---------------------------------------------------------------------------
# Membership (spec sections 3, 12, 13, 14, 20)
# ---------------------------------------------------------------------------


@router.get("/organizations/{organization_id}/members")
def list_members(resolved: tuple = Depends(require_organization_membership), db: Session = Depends(get_db)):
    org, _membership = resolved
    members = db.scalars(
        select(OrganizationMember)
        .where(OrganizationMember.organization_id == org.id, OrganizationMember.status != "REMOVED")
        .order_by(OrganizationMember.id)
    ).all()
    users_by_id = {u.id: u for u in db.scalars(select(User).where(User.id.in_([m.user_id for m in members]))).all()}
    return [_member_out(m, users_by_id.get(m.user_id)) for m in members]


@router.post("/organizations/{organization_id}/members/invite", status_code=201)
def invite_member(
    payload: InviteMemberIn,
    resolved: tuple = Depends(require_organization_admin),
    db: Session = Depends(get_db),
):
    """Only OWNER/ADMIN may invite (spec section 14: RECRUITER must
    not manage organization membership — enforced here by
    `require_organization_admin`, not just hidden in the UI, per
    spec section 26)."""
    org, membership = resolved
    if not can_manage_role(membership.role, payload.role):
        raise HTTPException(403, "You aren't allowed to invite a member at that role")

    email = payload.email.strip().lower()

    existing_user = db.scalars(select(User).where(User.email == email)).first()
    if existing_user is not None:
        existing_membership = db.scalars(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org.id,
                OrganizationMember.user_id == existing_user.id,
                OrganizationMember.status == "ACTIVE",
            )
        ).first()
        if existing_membership is not None:
            raise HTTPException(409, "That person is already a member of this organization")

    # Revoke any still-pending invitation to the same email for this
    # org first, so acceptance is always unambiguous about which
    # invite/role applies (spec section 15: single-use tokens).
    for prior in db.scalars(
        select(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == org.id,
            OrganizationInvitation.email == email,
            OrganizationInvitation.status == "PENDING",
        )
    ).all():
        prior.status = "REVOKED"

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = datetime.utcnow() + timedelta(days=INVITATION_EXPIRY_DAYS)

    invitation = OrganizationInvitation(
        organization_id=org.id,
        email=email,
        role=payload.role,
        invited_by=membership.user_id,
        token_hash=token_hash,
        status="PENDING",
        expires_at=expires_at,
    )
    db.add(invitation)
    _audit(db, org.id, "member_invited", target_type="invitation_email", target_id=email, role=payload.role)
    db.commit()
    db.refresh(invitation)

    # Only queue an actual email when the invitee already has a
    # CareerOS account — app.email.service.queue_email requires a
    # real user_id (see EmailMessage.user_id, NOT NULL). Inviting an
    # email address with no account yet still creates the invitation
    # row above (so it exists and can be accepted once they register
    # and log in with a matching email), but no email is sent for it
    # in this pass — see docs/V25_1_MULTI_TENANT_ORGANIZATIONS.md,
    # "NOT VERIFIED" / known limitations.
    if existing_user is not None:
        accept_url = f"{settings.frontend_origin}/organizations/invitations/{raw_token}"
        queue_email(
            db,
            user_id=existing_user.id,
            recipient=existing_user.email,
            template_key="ORGANIZATION_INVITATION",
            variables={
                "user_name": existing_user.full_name,
                "inviter_name": db.get(User, membership.user_id).full_name if db.get(User, membership.user_id) else "A teammate",
                "organization_name": org.name,
                "role": payload.role.title(),
                "action_url": accept_url,
                "expires_in": f"{INVITATION_EXPIRY_DAYS} days",
            },
            dedupe_key=f"org-invite-{invitation.id}",
        )
        db.commit()

    return {
        "id": invitation.id,
        "email": invitation.email,
        "role": invitation.role,
        "status": invitation.status,
        "expires_at": invitation.expires_at,
        # Returned once, to the inviter only, so the frontend can show/
        # copy a shareable link without a second round trip. Never
        # logged (see log line above, which only records the email/role)
        # and never retrievable again after this response.
        "token": raw_token,
    }


@router.post("/organization-invitations/{token}/accept")
def accept_invitation(token: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Explicit acceptance only (spec section 16) — a matching email
    is necessary but never sufficient by itself: the logged-in user
    must also present the actual secret token, AND that token's email
    must match the logged-in account, so a forwarded/leaked link can't
    be used to join under someone else's account."""
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    invitation = db.scalars(
        select(OrganizationInvitation).where(OrganizationInvitation.token_hash == token_hash)
    ).first()
    if invitation is None or invitation.status != "PENDING":
        raise HTTPException(400, "Invalid or already-used invitation")
    if invitation.expires_at < datetime.utcnow():
        invitation.status = "EXPIRED"
        db.commit()
        raise HTTPException(400, "This invitation has expired")
    if invitation.email != user.email.strip().lower():
        raise HTTPException(403, "This invitation was sent to a different email address")

    org = db.get(Organization, invitation.organization_id)
    if org is None or not org.is_active:
        raise HTTPException(404, "Organization not found")

    existing = db.scalars(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org.id, OrganizationMember.user_id == user.id
        )
    ).first()
    if existing is not None:
        existing.role = invitation.role
        existing.status = "ACTIVE"
        existing.joined_at = existing.joined_at or datetime.utcnow()
        existing.updated_at = datetime.utcnow()
    else:
        db.add(
            OrganizationMember(
                organization_id=org.id,
                user_id=user.id,
                role=invitation.role,
                status="ACTIVE",
                invited_by=invitation.invited_by,
                joined_at=datetime.utcnow(),
            )
        )

    invitation.status = "ACCEPTED"
    invitation.accepted_at = datetime.utcnow()
    invitation.accepted_by_user_id = user.id
    _audit(db, org.id, "invitation_accepted", target_type="user", target_id=str(user.id), role=invitation.role)
    db.commit()
    return {"organization_id": org.id, "role": invitation.role}


@router.post("/organization-invitations/{token}/reject")
def reject_invitation(token: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    invitation = db.scalars(
        select(OrganizationInvitation).where(OrganizationInvitation.token_hash == token_hash)
    ).first()
    if invitation is None or invitation.status != "PENDING":
        raise HTTPException(400, "Invalid or already-used invitation")
    if invitation.email != user.email.strip().lower():
        raise HTTPException(403, "This invitation was sent to a different email address")
    invitation.status = "REVOKED"
    _audit(db, invitation.organization_id, "invitation_rejected", target_type="user", target_id=str(user.id))
    db.commit()
    return {"status": "REVOKED"}


@router.post("/organizations/{organization_id}/members/{member_id}/suspend")
def suspend_member(
    member_id: int, resolved: tuple = Depends(require_organization_admin), db: Session = Depends(get_db)
):
    org, membership = resolved
    member = db.get(OrganizationMember, member_id)
    if member is None or member.organization_id != org.id or member.status == "REMOVED":
        raise HTTPException(404, "Member not found")
    if not can_manage_role(membership.role, member.role):
        raise HTTPException(403, "You aren't allowed to manage a member at that role")
    ensure_not_last_owner(db, org.id, member)
    member.status = "SUSPENDED"
    member.updated_at = datetime.utcnow()
    _audit(db, org.id, "member_suspended", target_type="user", target_id=str(member.user_id))
    db.commit()
    return _member_out(member, db.get(User, member.user_id))


@router.delete("/organizations/{organization_id}/members/{member_id}", status_code=204)
def remove_member(
    member_id: int, resolved: tuple = Depends(require_organization_admin), db: Session = Depends(get_db)
):
    org, membership = resolved
    member = db.get(OrganizationMember, member_id)
    if member is None or member.organization_id != org.id or member.status == "REMOVED":
        raise HTTPException(404, "Member not found")
    if not can_manage_role(membership.role, member.role):
        raise HTTPException(403, "You aren't allowed to manage a member at that role")
    ensure_not_last_owner(db, org.id, member)
    member.status = "REMOVED"
    member.updated_at = datetime.utcnow()
    _audit(db, org.id, "member_removed", target_type="user", target_id=str(member.user_id))
    db.commit()


@router.patch("/organizations/{organization_id}/members/{member_id}/role")
def change_member_role(
    member_id: int,
    payload: RoleChangeIn,
    resolved: tuple = Depends(require_organization_admin),
    db: Session = Depends(get_db),
):
    """Spec section 25's central privilege-escalation test: an ADMIN
    can never grant OWNER (nor edit an existing OWNER's role) — only
    an OWNER can. See `app.core.organizations.can_manage_role`."""
    org, membership = resolved
    member = db.get(OrganizationMember, member_id)
    if member is None or member.organization_id != org.id or member.status not in ("ACTIVE", "PENDING"):
        raise HTTPException(404, "Member not found")
    if not can_manage_role(membership.role, member.role) or not can_manage_role(membership.role, payload.role):
        raise HTTPException(403, "You aren't allowed to set that role")
    if member.role == "OWNER" and payload.role != "OWNER":
        ensure_not_last_owner(db, org.id, member)
    member.role = payload.role
    member.updated_at = datetime.utcnow()
    _audit(db, org.id, "member_role_changed", target_type="user", target_id=str(member.user_id), new_role=payload.role)
    db.commit()
    return _member_out(member, db.get(User, member.user_id))


# ---------------------------------------------------------------------------
# Audit log (spec sections 19, 20) — reuses the platform-wide AuditLog
# table (see this module's docstring) rather than a dedicated one.
# ---------------------------------------------------------------------------


@router.get("/organizations/{organization_id}/audit-log")
def get_audit_log(resolved: tuple = Depends(require_organization_admin), db: Session = Depends(get_db)):
    """OWNER/ADMIN only — not RECRUITER (spec section 13 scopes
    RECRUITER's visibility to their own authorized jobs/candidates,
    never organization-management data)."""
    org, _membership = resolved
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "organization", AuditLog.entity_id == str(org.id))
        .order_by(AuditLog.id.desc())
        .limit(200)
    ).all()
    out = []
    for row in rows:
        detail = json.loads(row.detail) if row.detail else {}
        out.append(
            {
                "id": row.id,
                "action": row.action,
                "target_type": detail.pop("target_type", None),
                "target_id": detail.pop("target_id", None),
                "metadata": detail,
                "actor_id": row.actor_id,
                "actor_label": row.actor_label,
                "created_at": row.created_at,
            }
        )
    return out
