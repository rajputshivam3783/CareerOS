"""V18.1 Company module — a recruiter's company profile (logo, banner,
description, size, branches, verification status) plus a public
directory/detail view candidates can browse.

Deliberately separate from app.api.recruiter (which stays focused on
jobs/applicants/interviews/offers) rather than folding this in, since
it's a distinct resource with its own ownership model: one company
profile per recruiter (``organizations.owner_user_id``), not scoped to
any single job. Mounted twice from app.api.routes — once under
``/recruiter/company`` (owner-only management) and once under
``/companies`` (public read-only).
"""

import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.validators import http_url_validator
from app.core.audit import log_audit
from app.core.constants import COMPANY_SIZES
from app.core.organizations import sync_legacy_membership
from app.core.security import require_recruiter
from app.db.session import get_db
from app.models.domain import CompanyBranch, CompanyTeamMember, Organization, User
from app.search.hooks import sync_company

router = APIRouter()
public_router = APIRouter()


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:140].rstrip("-")
    return f"{slug}-{uuid4().hex[:8]}"


def _owned_company_or_404(db: Session, recruiter: User) -> Organization:
    org = db.scalars(select(Organization).where(Organization.owner_user_id == recruiter.id)).first()
    if not org:
        raise HTTPException(404, "You haven't created a company profile yet")
    return org


def _ensure_owner_membership(db: Session, org: Organization) -> None:
    """Guarantees an ``owner`` row exists in company_team_members for
    this company's owner. Called defensively (not just at creation
    time) so companies created before V18.4 — or on SQLite, where
    migrations aren't run (see PROJECT_STATUS.md) — still show a
    roster instead of an empty team list."""
    if org.owner_user_id is None:
        return
    exists = db.scalars(
        select(CompanyTeamMember).where(
            CompanyTeamMember.company_id == org.id, CompanyTeamMember.user_id == org.owner_user_id
        )
    ).first()
    if not exists:
        db.add(CompanyTeamMember(company_id=org.id, user_id=org.owner_user_id, role="owner"))
        # V25.1 — mirror into the formal OrganizationMember table too
        # (see app.core.organizations.sync_legacy_membership) so a
        # company created/used only through this legacy endpoint still
        # gets correct org-scoped access under the new RBAC.
        sync_legacy_membership(db, organization_id=org.id, user_id=org.owner_user_id, role="OWNER")
        db.commit()


def _membership_or_403(db: Session, org: Organization, user: User) -> CompanyTeamMember:
    _ensure_owner_membership(db, org)
    member = db.scalars(
        select(CompanyTeamMember).where(CompanyTeamMember.company_id == org.id, CompanyTeamMember.user_id == user.id)
    ).first()
    if not member:
        raise HTTPException(403, "You aren't a member of this company's team")
    return member


class CompanyIn(BaseModel):
    name: str = Field(min_length=2, max_length=220)
    website: str | None = None
    logo_url: str | None = None
    banner_url: str | None = None
    description: str | None = None
    industry: str | None = None
    company_size: str | None = None
    founded_year: int | None = Field(default=None, ge=1800, le=2100)
    location: str | None = None
    linkedin_url: str | None = None
    twitter_url: str | None = None
    facebook_url: str | None = None
    instagram_url: str | None = None
    _validate_urls = http_url_validator(
        "website", "logo_url", "banner_url", "linkedin_url", "twitter_url", "facebook_url", "instagram_url", assume_https=True
    )

    @field_validator("company_size")
    @classmethod
    def company_size_must_be_known(cls, value: str | None) -> str | None:
        if value is not None and value not in COMPANY_SIZES:
            raise ValueError(f"company_size must be one of {COMPANY_SIZES}")
        return value


class BranchIn(BaseModel):
    branch_name: str = Field(min_length=1, max_length=220)
    location: str | None = None
    address: str | None = None
    is_headquarters: bool = False


# ---------------------------------------------------------------------------
# Recruiter-facing management (owner-only)
# ---------------------------------------------------------------------------


@router.get("/company")
def get_my_company(recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    return _owned_company_or_404(db, recruiter)


@router.put("/company")
def upsert_my_company(
    payload: CompanyIn, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)
):
    """Create the recruiter's company profile if none exists yet, or
    update it in place otherwise — one PUT covers both so the frontend
    doesn't need to know which state it's in."""
    org = db.scalars(select(Organization).where(Organization.owner_user_id == recruiter.id)).first()

    # Catches both another recruiter's company AND a legacy/unclaimed
    # `organizations` row with the same name (owner_user_id NULL) —
    # `name` carries a unique constraint from V1, so either case would
    # otherwise surface as an unhandled IntegrityError on commit rather
    # than this clean 409.
    name_clash_stmt = select(Organization).where(Organization.name == payload.name)
    if org is not None:
        name_clash_stmt = name_clash_stmt.where(Organization.id != org.id)
    if db.scalars(name_clash_stmt).first():
        raise HTTPException(409, "A company with this name already exists")

    creating = org is None
    if creating:
        org = Organization(name=payload.name, owner_user_id=recruiter.id, slug=_slugify(payload.name))
        db.add(org)

    material_fields = {"name", "industry", "description", "company_size", "location"}
    incoming = payload.model_dump()
    material_change = any(getattr(org, key, None) != incoming.get(key) for key in material_fields)
    for key, value in incoming.items():
        setattr(org, key, value)

    # Re-verification, same rule V9 already applies to job listings: a
    # material profile edit on an already-verified company sends it
    # back to "pending" rather than silently keeping the old badge.
    if not creating and material_change and org.verification_status == "verified":
        org.verification_status = "pending"
        org.verified = False

    db.commit()
    db.refresh(org)
    log_audit(db, "company.created" if creating else "company.updated", "organization", str(org.id))
    db.commit()
    sync_company(db, org.id)  # V21.1 Phase 3
    db.refresh(org)  # sync_company's own commit expires org — refresh before returning it
    _ensure_owner_membership(db, org)
    db.refresh(org)  # _ensure_owner_membership may also commit internally (creating the owner's team-member row on first save), which expires org same as sync_company above; refresh again before returning it
    return org


@router.get("/company/branches")
def list_my_branches(recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    org = _owned_company_or_404(db, recruiter)
    return db.scalars(
        select(CompanyBranch).where(CompanyBranch.organization_id == org.id).order_by(CompanyBranch.id)
    ).all()


@router.post("/company/branches", status_code=201)
def add_branch(
    payload: BranchIn, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)
):
    org = _owned_company_or_404(db, recruiter)
    branch = CompanyBranch(organization_id=org.id, **payload.model_dump())
    db.add(branch)
    db.commit()
    db.refresh(branch)
    log_audit(db, "company.branch_added", "company_branch", str(branch.id))
    db.commit()
    db.refresh(branch)  # this commit expires branch again (log_audit itself doesn't commit) — refresh before returning it, same fix as upsert_my_company above
    return branch


@router.delete("/company/branches/{branch_id}", status_code=204)
def delete_branch(branch_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    org = _owned_company_or_404(db, recruiter)
    branch = db.get(CompanyBranch, branch_id)
    if not branch or branch.organization_id != org.id:
        raise HTTPException(404, "Branch not found")
    db.delete(branch)
    log_audit(db, "company.branch_removed", "company_branch", str(branch_id))
    db.commit()


# ---------------------------------------------------------------------------
# V18.4 — Team management. A company's own recruiter account is always
# its "owner" member; the owner can additionally list other *existing*
# recruiter accounts as "member"s. This is a roster/visibility feature
# only — see CompanyTeamMember's docstring for why job/applicant access
# itself isn't (yet) widened to team members.
# ---------------------------------------------------------------------------


class TeamInviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)


def _company_for_member_or_404(db: Session, recruiter: User) -> Organization:
    """A company this recruiter either owns or is a member of — used
    by the read-only team endpoints so any teammate (not just the
    owner) can see the roster."""
    org = db.scalars(select(Organization).where(Organization.owner_user_id == recruiter.id)).first()
    if org:
        return org
    membership = db.scalars(select(CompanyTeamMember).where(CompanyTeamMember.user_id == recruiter.id)).first()
    if membership:
        org = db.get(Organization, membership.company_id)
        if org:
            return org
    raise HTTPException(404, "You aren't part of a company team yet")


@router.get("/company/team")
def list_team(recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    org = _company_for_member_or_404(db, recruiter)
    _membership_or_403(db, org, recruiter)
    members = db.scalars(
        select(CompanyTeamMember).where(CompanyTeamMember.company_id == org.id).order_by(CompanyTeamMember.id)
    ).all()
    result = []
    for m in members:
        user = db.get(User, m.user_id)
        result.append(
            {
                "id": m.id,
                "user_id": m.user_id,
                "name": user.full_name if user else None,
                "email": user.email if user else None,
                "role": m.role,
                "created_at": m.created_at,
            }
        )
    return result


@router.post("/company/team/invite", status_code=201)
def invite_team_member(
    payload: TeamInviteIn, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)
):
    """Adds an *existing* recruiter account to the team. Deliberately
    does not create a new account or send a signup link — CareerOS
    Authentication stays untouched here; the person being added must
    already have registered and been granted the recruiter role
    (through the normal, unmodified registration/admin-approval path)
    before an owner can add them by email."""
    org = _owned_company_or_404(db, recruiter)  # only the owner can invite
    _ensure_owner_membership(db, org)

    candidate = db.scalars(select(User).where(User.email == payload.email.strip().lower())).first()
    if not candidate:
        raise HTTPException(
            404, "No account found with that email. They need to register as a recruiter first."
        )
    if candidate.role != "recruiter":
        raise HTTPException(409, "That account isn't a recruiter account, so it can't be added to the team.")

    existing = db.scalars(
        select(CompanyTeamMember).where(
            CompanyTeamMember.company_id == org.id, CompanyTeamMember.user_id == candidate.id
        )
    ).first()
    if existing:
        raise HTTPException(409, "That recruiter is already on the team.")

    member = CompanyTeamMember(company_id=org.id, user_id=candidate.id, role="member", added_by_user_id=recruiter.id)
    db.add(member)
    # V25.1 — mirror into OrganizationMember; see _ensure_owner_membership above.
    sync_legacy_membership(db, organization_id=org.id, user_id=candidate.id, role="RECRUITER", invited_by=recruiter.id)
    log_audit(db, "company.team_member_added", "organization", str(org.id), detail=candidate.email)
    db.commit()
    db.refresh(member)
    return {"id": member.id, "user_id": candidate.id, "name": candidate.full_name, "email": candidate.email, "role": member.role}


@router.delete("/company/team/{member_id}", status_code=204)
def remove_team_member(member_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    org = _owned_company_or_404(db, recruiter)  # only the owner can remove
    member = db.get(CompanyTeamMember, member_id)
    if not member or member.company_id != org.id:
        raise HTTPException(404, "Team member not found")
    if member.role == "owner":
        raise HTTPException(409, "The company owner can't be removed from the team")
    # V25.1 — mirror into OrganizationMember (marks REMOVED rather
    # than deleting, so the audit trail/history is preserved there).
    sync_legacy_membership(db, organization_id=org.id, user_id=member.user_id, role="RECRUITER", remove=True)
    db.delete(member)
    log_audit(db, "company.team_member_removed", "organization", str(org.id), detail=str(member.user_id))
    db.commit()


# ---------------------------------------------------------------------------
# Public directory / profile (read-only, no auth)
# ---------------------------------------------------------------------------


@public_router.get("/companies")
def list_companies(
    q: str | None = Query(default=None, description="Search by company name"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Organization).where(Organization.slug.is_not(None))
    if q:
        stmt = stmt.where(Organization.name.ilike(f"%{q}%"))
    return db.scalars(stmt.order_by(Organization.name).limit(limit).offset(offset)).all()


@public_router.get("/companies/{slug}")
def get_company(slug: str, db: Session = Depends(get_db)):
    org = db.scalars(select(Organization).where(Organization.slug == slug)).first()
    if not org:
        raise HTTPException(404, "Company not found")
    branches = db.scalars(
        select(CompanyBranch).where(CompanyBranch.organization_id == org.id).order_by(CompanyBranch.id)
    ).all()
    return {"company": org, "branches": branches}
