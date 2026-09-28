"""V25.2 — the platform administration API.

Mounted under the existing ``/api/v1/admin`` prefix alongside
``app.api.admin`` (V9) and ``app.api.admin_rbac`` (V17.3) rather than
under a new prefix, because these are the same administrative surface
— a fourth top-level namespace would fragment it. Route paths were
checked against both existing routers before being added; the only
deliberate overlaps are documented at their definitions.

AUTHORIZATION
-------------
Every route carries an explicit
``Depends(require_platform_permission(...))``. There is no route in
this file without one, and no route that infers authority from
anything other than ``User.role``. An organization OWNER or ADMIN, a
RECRUITER and a candidate all receive 403 here — being an
administrator *of a tenant* grants nothing *on the platform*. See
``app.core.platform_admin`` for why that separation is structural.

Frontend route guards are a convenience only; nothing in
``frontend/src/app/admin`` is trusted by this file.

PAGINATION
----------
Every list endpoint is paginated with a hard ``le=`` cap on ``limit``
and returns ``{total, limit, offset, results}``. No endpoint here can
be made to return an unbounded result set, which is what keeps
section 33 (performance) and section 11 ("do not load the entire
audit table into the browser") true by construction rather than by
convention.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.platform_admin import (
    ALL_PLATFORM_PERMISSIONS,
    PERMISSION_DESCRIPTIONS,
    PlatformActor,
    PlatformPermission,
    require_platform_permission,
    require_sensitive_platform_action,
)
from app.core.platform_audit import ALL_PLATFORM_ACTIONS, PlatformAction, record_platform_action
from app.core.platform_lifecycle import (
    SUSPENSION_REASONS,
    deactivate_user,
    derive_account_status,
    derive_organization_status,
    organization_member_ids,
    reactivate_organization,
    reactivate_user,
    suspend_organization,
    suspend_user,
)
from app.core.platform_settings import (
    SETTING_DEFINITIONS,
    describe_settings,
    get_setting,
    set_setting,
)
from app.core.security_events import SECURITY_INCIDENT_ACTIONS
from app.db.session import get_db
from app.models.domain import (
    Applicant,
    AuditLog,
    Job,
    Organization,
    OrganizationMember,
    PlatformAnnouncement,
    PlatformAuditLog,
    User,
)
from app.services import job_moderation, platform_analytics, platform_health

router = APIRouter()

MAX_PAGE = 100


def _page(total: int, limit: int, offset: int, results: list) -> dict:
    return {"total": total, "limit": limit, "offset": offset, "results": results}


# ===========================================================================
# Who am I / what can I do
# ===========================================================================


@router.get("/me/platform-permissions")
def my_platform_permissions(
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.AUDIT_ACCESS)),
):
    """Backs the permission-aware admin navigation (spec section 30).

    Gated on AUDIT_ACCESS rather than being open to any authenticated
    user on purpose: the set of permissions a platform holds is itself
    information an attacker would like. A non-administrator gets 403
    and learns nothing.
    """
    return {
        "actor_type": actor.actor_type,
        "role": actor.role,
        "permissions": sorted(actor.permissions),
        "can_perform_sensitive_actions": actor.can_perform_sensitive_action(),
        "catalog": [{"permission": p, "description": PERMISSION_DESCRIPTIONS[p]} for p in ALL_PLATFORM_PERMISSIONS],
    }


# ===========================================================================
# 3. Dashboard
# ===========================================================================


@router.get("/dashboard")
def dashboard(
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.PLATFORM_ANALYTICS)),
):
    return platform_analytics.dashboard_metrics(db)


# ===========================================================================
# 4/5. User management
# ===========================================================================


def _user_summary(user: User) -> dict:
    """The user fields safe to show in an administrative list.

    Explicitly absent, and never added: ``password_hash``, any OTP or
    verification code, any access/refresh token, resume or document
    content, and the candidate's private application notes. The fields
    below are account-administration facts only (spec section 4).
    """
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "account_status": derive_account_status(user),
        "active": user.active,
        "email_verified": user.email_verified,
        "recruiter_status": user.recruiter_status,
        "created_at": user.created_at,
        "suspended_at": user.suspended_at,
        "locked_until": user.locked_until,
    }


@router.get("/users")
def list_users(
    q: str | None = Query(default=None, max_length=200, description="Search email or full name"),
    role: str | None = Query(default=None, max_length=30),
    account_status: str | None = Query(default=None, pattern="^(ACTIVE|SUSPENDED|DEACTIVATED)$"),
    email_verified: bool | None = Query(default=None),
    organization_id: int | None = Query(default=None, ge=1),
    limit: int = Query(25, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.USER_MANAGEMENT)),
):
    """Search and filter platform user accounts.

    Replaces the V9 ``GET /admin/users``, which returned an unfiltered,
    unpaginated list of the 200 most recent users and no more. Every
    key that endpoint returned (``id``, ``email``, ``full_name``,
    ``role``, ``active``) is still present on each result, so a
    consumer reading those fields is unaffected; the response is now
    wrapped in the ``{total, limit, offset, results}`` envelope every
    other paginated endpoint in this codebase uses. This is an
    upgrade of the existing route, not a duplicate of it — spec
    section 29 forbids creating a second one.

    The search is a parameterized ``LIKE`` through SQLAlchemy — user
    input is never concatenated into SQL (section 31).
    """
    query = select(User)
    count_query = select(func.count()).select_from(User)

    clauses = []
    if q:
        needle = f"%{q.strip().lower()}%"
        clauses.append(or_(func.lower(User.email).like(needle), func.lower(User.full_name).like(needle)))
    if role:
        clauses.append(User.role == role)
    if email_verified is not None:
        clauses.append(User.email_verified.is_(email_verified))
    if account_status == "ACTIVE":
        clauses.append(User.active.is_(True))
    elif account_status == "SUSPENDED":
        clauses.append(User.active.is_(False))
        clauses.append(User.suspended_at.isnot(None))
    elif account_status == "DEACTIVATED":
        clauses.append(User.active.is_(False))
        clauses.append(User.suspended_at.is_(None))
    if organization_id:
        member_ids = select(OrganizationMember.user_id).where(
            OrganizationMember.organization_id == organization_id
        )
        clauses.append(User.id.in_(member_ids))

    for clause in clauses:
        query = query.where(clause)
        count_query = count_query.where(clause)

    total = int(db.scalar(count_query) or 0)
    rows = db.scalars(query.order_by(User.id.desc()).limit(limit).offset(offset)).all()
    return _page(total, limit, offset, [_user_summary(u) for u in rows])


@router.get("/users/{user_id}")
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.USER_MANAGEMENT)),
):
    """One account's administrative detail.

    Adds organization memberships and a small activity summary to the
    list fields. The activity summary is counts only — how many
    applications exist, not what is in them.
    """
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    memberships = db.execute(
        select(OrganizationMember, Organization)
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(OrganizationMember.user_id == user_id)
        .order_by(OrganizationMember.id.desc())
    ).all()

    detail = _user_summary(user)
    detail["organization_memberships"] = [
        {
            "organization_id": org.id,
            "organization_name": org.name,
            "organization_status": derive_organization_status(org),
            # Explicitly labelled so nobody reads an organization role
            # as a platform capability.
            "organization_role": member.role,
            "membership_status": member.status,
            "joined_at": member.joined_at,
        }
        for member, org in memberships
    ]
    detail["activity"] = {
        "applications": int(
            db.scalar(select(func.count()).select_from(Applicant).where(Applicant.user_id == user_id)) or 0
        ),
        "jobs_owned": int(db.scalar(select(func.count()).select_from(Job).where(Job.owner_user_id == user_id)) or 0),
    }
    detail["suspension_reason"] = user.suspension_reason
    return detail


class SuspendIn(BaseModel):
    reason: str = Field(description="Structured reason code")
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def _valid_reason(cls, value: str) -> str:
        if value not in SUSPENSION_REASONS:
            raise ValueError(f"reason must be one of: {', '.join(SUSPENSION_REASONS)}")
        return value


@router.post("/users/{user_id}/suspend")
def suspend_user_endpoint(
    user_id: int,
    payload: SuspendIn,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.USER_MANAGEMENT)),
):
    """Suspend a platform account.

    Refuses to suspend another platform administrator unless the
    caller holds a full platform-admin role: a ``support_admin`` with
    USER_MANAGEMENT must not be able to disable the accounts that
    could reverse the action. Self-suspension is refused outright —
    locking yourself out of the platform is never the intent, and
    section 20's "do not accidentally lock all administrators out"
    applies to this route just as much as to maintenance mode.
    """
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if actor.user_id is not None and user.id == actor.user_id:
        raise HTTPException(400, "You cannot suspend your own account")
    from app.core.platform_admin import is_platform_admin

    if is_platform_admin(user):
        require_sensitive_platform_action(actor)
    if not user.active:
        raise HTTPException(409, "Account is already inactive")

    suspend_user(db, user, reason=payload.reason, note=payload.note)
    record_platform_action(
        db,
        actor,
        action=PlatformAction.USER_SUSPENDED,
        target_type="user",
        target_id=user.id,
        reason=payload.reason,
        note=payload.note,
        metadata={"previous_role": user.role},
    )
    db.commit()
    return {"id": user.id, "account_status": derive_account_status(user)}


@router.post("/users/{user_id}/deactivate")
def deactivate_user_endpoint(
    user_id: int,
    payload: SuspendIn,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.USER_MANAGEMENT)),
):
    """Deactivate an account. Reversible; see
    ``app.core.platform_lifecycle`` for how this differs from
    suspension. Restricted to full platform administrators because it
    is the stronger of the two end-states (spec section 26)."""
    require_sensitive_platform_action(actor)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if actor.user_id is not None and user.id == actor.user_id:
        raise HTTPException(400, "You cannot deactivate your own account")

    deactivate_user(db, user, reason=payload.reason, note=payload.note)
    record_platform_action(
        db,
        actor,
        action=PlatformAction.USER_DEACTIVATED,
        target_type="user",
        target_id=user.id,
        reason=payload.reason,
        note=payload.note,
    )
    db.commit()
    return {"id": user.id, "account_status": derive_account_status(user)}


class ReactivateIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


@router.post("/users/{user_id}/reactivate")
def reactivate_user_endpoint(
    user_id: int,
    payload: ReactivateIn | None = None,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.USER_MANAGEMENT)),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    reactivate_user(db, user)
    record_platform_action(
        db,
        actor,
        action=PlatformAction.USER_REACTIVATED,
        target_type="user",
        target_id=user.id,
        note=payload.note if payload else None,
    )
    db.commit()
    return {"id": user.id, "account_status": derive_account_status(user)}


@router.get("/users/{user_id}/history")
def user_history(
    user_id: int,
    limit: int = Query(25, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.AUDIT_ACCESS)),
):
    """Administrative history for one account (spec section 12).

    A filtered read of the central platform audit trail — not a
    separate per-user history table, which section 12 explicitly asks
    us not to create.
    """
    return _audit_page(db, limit, offset, target_type="user", target_id=str(user_id))


# ===========================================================================
# 6/7. Organization management
# ===========================================================================


def _organization_summary(db: Session, org: Organization, *, counts: bool = True) -> dict:
    data = {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "status": derive_organization_status(org),
        "is_active": org.is_active,
        "verification_status": org.verification_status,
        "industry": org.industry,
        "location": org.location,
        "created_at": org.created_at,
        "suspended_at": org.suspended_at,
    }
    if counts:
        member_ids = organization_member_ids(db, org.id)
        data["member_count"] = len(member_ids)
        data["job_count"] = (
            int(db.scalar(select(func.count()).select_from(Job).where(Job.owner_user_id.in_(member_ids))) or 0)
            if member_ids
            else 0
        )
        data["application_count"] = (
            int(
                db.scalar(
                    select(func.count())
                    .select_from(Applicant)
                    .join(Job, Job.id == Applicant.job_id)
                    .where(Job.owner_user_id.in_(member_ids))
                )
                or 0
            )
            if member_ids
            else 0
        )
    return data


@router.get("/organizations")
def list_organizations(
    q: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None, pattern="^(ACTIVE|SUSPENDED|DEACTIVATED)$"),
    verification_status: str | None = Query(default=None, max_length=20),
    limit: int = Query(25, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.ORGANIZATION_MANAGEMENT)),
):
    query = select(Organization)
    count_query = select(func.count()).select_from(Organization)
    clauses = []
    if q:
        needle = f"%{q.strip().lower()}%"
        clauses.append(or_(func.lower(Organization.name).like(needle), func.lower(Organization.slug).like(needle)))
    if verification_status:
        clauses.append(Organization.verification_status == verification_status)
    if status == "ACTIVE":
        clauses.append(Organization.is_active.is_(True))
    elif status == "SUSPENDED":
        clauses.append(Organization.is_active.is_(False))
        clauses.append(Organization.suspended_at.isnot(None))
    elif status == "DEACTIVATED":
        clauses.append(Organization.is_active.is_(False))
        clauses.append(Organization.suspended_at.is_(None))
    for clause in clauses:
        query = query.where(clause)
        count_query = count_query.where(clause)

    total = int(db.scalar(count_query) or 0)
    rows = db.scalars(query.order_by(Organization.id.desc()).limit(limit).offset(offset)).all()
    # Counts are computed per row here. That is N+1-ish by shape, but
    # bounded hard by `limit <= 100` and each query is a single indexed
    # COUNT — measured against the alternative (a four-way GROUP BY
    # join across members/jobs/applicants for every org) it is the
    # simpler and more predictable of the two at this page size. The
    # aggregate leaderboards in platform_analytics, which are NOT
    # bounded to a page, do use the single-query GROUP BY form.
    return _page(total, limit, offset, [_organization_summary(db, org) for org in rows])


@router.get("/organizations/{organization_id}")
def get_organization(
    organization_id: int,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.ORGANIZATION_MANAGEMENT)),
):
    org = db.get(Organization, organization_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    detail = _organization_summary(db, org)
    detail["suspension_reason"] = org.suspension_reason

    members = db.execute(
        select(OrganizationMember, User)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == organization_id)
        .order_by(OrganizationMember.id)
        .limit(MAX_PAGE)
    ).all()
    detail["members"] = [
        {
            "user_id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "organization_role": member.role,
            "membership_status": member.status,
            "platform_account_status": derive_account_status(user),
            "joined_at": member.joined_at,
        }
        for member, user in members
    ]
    return detail


class OrganizationSuspendIn(SuspendIn):
    # Deactivation is the stronger end-state; suspension is the
    # default because it is the reversible one.
    deactivate: bool = False


@router.post("/organizations/{organization_id}/suspend")
def suspend_organization_endpoint(
    organization_id: int,
    payload: OrganizationSuspendIn,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.ORGANIZATION_MANAGEMENT)),
):
    """Suspend an organization.

    High impact — it unpublishes every live listing the organization
    owns — so it requires a full platform-admin role (spec section
    26). The exact behaviour, including what is deliberately left
    untouched, is documented in ``app.core.platform_lifecycle``.
    """
    require_sensitive_platform_action(actor)
    org = db.get(Organization, organization_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    if not org.is_active:
        raise HTTPException(409, "Organization is already inactive")

    summary = suspend_organization(
        db, org, reason=payload.reason, note=payload.note, deactivate=payload.deactivate
    )
    record_platform_action(
        db,
        actor,
        action=(
            PlatformAction.ORGANIZATION_DEACTIVATED if payload.deactivate else PlatformAction.ORGANIZATION_SUSPENDED
        ),
        target_type="organization",
        target_id=org.id,
        organization_id=org.id,
        reason=payload.reason,
        note=payload.note,
        metadata=summary,
    )
    db.commit()
    return {"id": org.id, "status": derive_organization_status(org), **summary}


@router.post("/organizations/{organization_id}/reactivate")
def reactivate_organization_endpoint(
    organization_id: int,
    payload: ReactivateIn | None = None,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.ORGANIZATION_MANAGEMENT)),
):
    require_sensitive_platform_action(actor)
    org = db.get(Organization, organization_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    summary = reactivate_organization(db, org)
    record_platform_action(
        db,
        actor,
        action=PlatformAction.ORGANIZATION_REACTIVATED,
        target_type="organization",
        target_id=org.id,
        organization_id=org.id,
        note=payload.note if payload else None,
        metadata=summary,
    )
    db.commit()
    return {"id": org.id, "status": derive_organization_status(org), **summary}


@router.get("/organizations/{organization_id}/history")
def organization_history(
    organization_id: int,
    limit: int = Query(25, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.AUDIT_ACCESS)),
):
    return _audit_page(db, limit, offset, target_type="organization", target_id=str(organization_id))


# ===========================================================================
# 8/9. Job moderation
# ===========================================================================


def _job_summary(job: Job, *, include_internal: bool) -> dict:
    data = {
        "id": job.id,
        "title": job.title,
        "organization": job.organization,
        "status": job.status,
        "job_type": job.job_type,
        "location": job.location,
        "owner_user_id": job.owner_user_id,
        "source_name": job.source_name,
        "created_at": job.created_at,
        "published_at": job.published_at,
        "deadline": job.deadline,
        "moderation_reason": job.moderation_reason,
        "moderated_at": job.moderated_at,
    }
    if include_internal:
        # Internal moderation note — platform-admin surface only.
        data["moderation_note"] = job.moderation_note
        data["moderated_by_user_id"] = job.moderated_by_user_id
        data["pre_moderation_status"] = job.pre_moderation_status
    return data


@router.get("/jobs")
def list_jobs(
    q: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None, max_length=20),
    organization_id: int | None = Query(default=None, ge=1),
    owner_user_id: int | None = Query(default=None, ge=1),
    moderation_reason: str | None = Query(default=None, max_length=40),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    published_from: datetime | None = Query(default=None),
    published_to: datetime | None = Query(default=None),
    limit: int = Query(25, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.JOB_MODERATION)),
):
    """Platform-wide job moderation queue with the filters section 8
    asks for: search, status, organization, recruiter, creation date,
    publication date and review state."""
    if status is not None and status not in job_moderation.JOB_STATUSES:
        raise HTTPException(422, f"status must be one of: {', '.join(job_moderation.JOB_STATUSES)}")

    query = select(Job)
    count_query = select(func.count()).select_from(Job)
    clauses = []
    if q:
        needle = f"%{q.strip().lower()}%"
        clauses.append(or_(func.lower(Job.title).like(needle), func.lower(Job.organization).like(needle)))
    if status:
        clauses.append(Job.status == status)
    if owner_user_id:
        clauses.append(Job.owner_user_id == owner_user_id)
    if organization_id:
        member_ids = organization_member_ids(db, organization_id)
        # An organization with no members owns no jobs; match nothing
        # rather than degrading to "match everything".
        clauses.append(Job.owner_user_id.in_(member_ids) if member_ids else Job.id < 0)
    if moderation_reason:
        clauses.append(Job.moderation_reason == moderation_reason)
    if created_from:
        clauses.append(Job.created_at >= created_from)
    if created_to:
        clauses.append(Job.created_at <= created_to)
    if published_from:
        clauses.append(Job.published_at >= published_from)
    if published_to:
        clauses.append(Job.published_at <= published_to)

    for clause in clauses:
        query = query.where(clause)
        count_query = count_query.where(clause)

    total = int(db.scalar(count_query) or 0)
    rows = db.scalars(query.order_by(Job.id.desc()).limit(limit).offset(offset)).all()
    return _page(total, limit, offset, [_job_summary(j, include_internal=True) for j in rows])


class ModerationIn(BaseModel):
    reason: str
    note: str | None = Field(default=None, max_length=4000)

    @field_validator("reason")
    @classmethod
    def _valid(cls, value: str) -> str:
        if value not in job_moderation.MODERATION_REASONS:
            raise ValueError(f"reason must be one of: {', '.join(job_moderation.MODERATION_REASONS)}")
        return value


@router.post("/jobs/{job_id}/approve")
def approve_job(
    job_id: int,
    payload: ReactivateIn | None = None,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.JOB_MODERATION)),
):
    """Approve a job out of the review queue.

    Same transition as the V9 ``POST /admin/jobs/{id}/publish``, which
    still exists and now shares this implementation
    (``app.services.job_moderation.approve_job``) — one publication
    system, two entry points, as section 8 requires.
    """
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    previous = job.status
    job_moderation.approve_job(db, job, actor_user_id=actor.user_id, note=payload.note if payload else None)
    record_platform_action(
        db,
        actor,
        action=PlatformAction.JOB_APPROVED,
        target_type="job",
        target_id=job.id,
        note=payload.note if payload else None,
        metadata={"from_status": previous, "to_status": job.status},
    )
    db.commit()
    return _job_summary(job, include_internal=True)


@router.post("/jobs/{job_id}/suspend")
def suspend_job(
    job_id: int,
    payload: ModerationIn,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.JOB_MODERATION)),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    previous = job.status
    job_moderation.suspend_job(db, job, reason=payload.reason, actor_user_id=actor.user_id, note=payload.note)
    record_platform_action(
        db,
        actor,
        action=PlatformAction.JOB_SUSPENDED,
        target_type="job",
        target_id=job.id,
        reason=payload.reason,
        note=payload.note,
        metadata={"from_status": previous, "to_status": job.status},
    )
    db.commit()
    return _job_summary(job, include_internal=True)


@router.post("/jobs/{job_id}/restore")
def restore_job(
    job_id: int,
    payload: ReactivateIn | None = None,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.JOB_MODERATION)),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    previous = job.status
    job_moderation.restore_job(db, job, actor_user_id=actor.user_id, note=payload.note if payload else None)
    record_platform_action(
        db,
        actor,
        action=PlatformAction.JOB_RESTORED,
        target_type="job",
        target_id=job.id,
        note=payload.note if payload else None,
        metadata={"from_status": previous, "to_status": job.status},
    )
    db.commit()
    return _job_summary(job, include_internal=True)


@router.get("/jobs/{job_id}/history")
def job_history(
    job_id: int,
    limit: int = Query(25, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.AUDIT_ACCESS)),
):
    return _audit_page(db, limit, offset, target_type="job", target_id=str(job_id))


@router.get("/moderation/reasons")
def moderation_reasons(
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.JOB_MODERATION)),
):
    """The structured reason vocabularies, so the admin UI's dropdowns
    are generated from the backend's validation list rather than a
    hardcoded copy that can drift out of sync with it."""
    return {
        "job_moderation_reasons": list(job_moderation.MODERATION_REASONS),
        "suspension_reasons": list(SUSPENSION_REASONS),
        "job_statuses": list(job_moderation.JOB_STATUSES),
    }


# ===========================================================================
# 10/11/32. Audit log
# ===========================================================================


def _audit_row(row: PlatformAuditLog) -> dict:
    return {
        "id": row.id,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "organization_id": row.organization_id,
        "actor_user_id": row.actor_user_id,
        "actor_type": row.actor_type,
        "actor_label": row.actor_label,
        "reason": row.reason,
        "note": row.note,
        "metadata": json.loads(row.metadata_json) if row.metadata_json else None,
        "result": row.result,
        "request_id": row.request_id,
        "ip_address": row.ip_address,
        "created_at": row.created_at,
    }


def _audit_page(
    db: Session,
    limit: int,
    offset: int,
    *,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    organization_id: int | None = None,
    actor_user_id: int | None = None,
    result: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    q: str | None = None,
) -> dict:
    query = select(PlatformAuditLog)
    count_query = select(func.count()).select_from(PlatformAuditLog)
    clauses = []
    if action:
        clauses.append(PlatformAuditLog.action == action)
    if target_type:
        clauses.append(PlatformAuditLog.target_type == target_type)
    if target_id:
        clauses.append(PlatformAuditLog.target_id == target_id)
    if organization_id:
        clauses.append(PlatformAuditLog.organization_id == organization_id)
    if actor_user_id:
        clauses.append(PlatformAuditLog.actor_user_id == actor_user_id)
    if result:
        clauses.append(PlatformAuditLog.result == result)
    if date_from:
        clauses.append(PlatformAuditLog.created_at >= date_from)
    if date_to:
        clauses.append(PlatformAuditLog.created_at <= date_to)
    if q:
        needle = f"%{q.strip().lower()}%"
        clauses.append(
            or_(
                func.lower(PlatformAuditLog.actor_label).like(needle),
                func.lower(PlatformAuditLog.action).like(needle),
                func.lower(cast(PlatformAuditLog.target_id, String)).like(needle),
            )
        )
    for clause in clauses:
        query = query.where(clause)
        count_query = count_query.where(clause)

    total = int(db.scalar(count_query) or 0)
    rows = db.scalars(query.order_by(PlatformAuditLog.id.desc()).limit(limit).offset(offset)).all()
    return _page(total, limit, offset, [_audit_row(r) for r in rows])


@router.get("/audit")
def audit_log(
    q: str | None = Query(default=None, max_length=200),
    action: str | None = Query(default=None, max_length=60),
    target_type: str | None = Query(default=None, max_length=40),
    target_id: str | None = Query(default=None, max_length=120),
    organization_id: int | None = Query(default=None, ge=1),
    actor_user_id: int | None = Query(default=None, ge=1),
    result: str | None = Query(default=None, pattern="^(success|failure|partial)$"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(25, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.AUDIT_ACCESS)),
):
    """Read the platform audit trail.

    Read-only by construction: this router defines no PUT, PATCH or
    DELETE against ``platform_audit_logs``, and
    ``app.core.platform_audit`` is the table's only writer. There is
    no code path through which an administrator can edit or remove a
    historical entry (spec section 32).
    """
    return _audit_page(
        db,
        limit,
        offset,
        q=q,
        action=action,
        target_type=target_type,
        target_id=target_id,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        result=result,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/audit/actions")
def audit_actions(
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.AUDIT_ACCESS)),
):
    return {"actions": sorted(ALL_PLATFORM_ACTIONS)}


# ===========================================================================
# 22/23. Security events and abuse visibility
# ===========================================================================


@router.get("/security/events")
def security_events(
    action: str | None = Query(default=None, max_length=60),
    entity_id: str | None = Query(default=None, max_length=120),
    date_from: datetime | None = Query(default=None),
    limit: int = Query(25, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.AUDIT_ACCESS)),
):
    """Security-relevant events, read from the existing `audit_logs`
    table filtered to the V17.2/V25.2 security taxonomy.

    No separate security-event store exists — see
    ``app.core.security_events``. The response carries no password,
    token, OTP or session identifier because nothing that records
    these events ever writes one.
    """
    if action and action not in SECURITY_INCIDENT_ACTIONS:
        raise HTTPException(422, "Unknown security event action")

    allowed = list(SECURITY_INCIDENT_ACTIONS)
    query = select(AuditLog).where(AuditLog.action.in_([action] if action else allowed))
    count_query = select(func.count()).select_from(AuditLog).where(
        AuditLog.action.in_([action] if action else allowed)
    )
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)
        count_query = count_query.where(AuditLog.entity_id == entity_id)
    if date_from:
        query = query.where(AuditLog.created_at >= date_from)
        count_query = count_query.where(AuditLog.created_at >= date_from)

    total = int(db.scalar(count_query) or 0)
    rows = db.scalars(query.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
    return _page(
        total,
        limit,
        offset,
        [
            {
                "id": r.id,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "detail": r.detail,
                "actor_type": r.actor_type,
                "actor_label": r.actor_label,
                "ip_address": r.ip_address,
                "request_id": r.request_id,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    )


@router.get("/security/abuse-signals")
def abuse_signals(
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(20, ge=1, le=MAX_PAGE),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.AUDIT_ACCESS)),
):
    """Aggregate abuse indicators over a window (spec section 22).

    Deliberately aggregate: counts of security events grouped by
    action and by source IP, not a per-user behavioural profile.
    Section 22 asks for meaningful abuse visibility and explicitly
    rules out invasive user surveillance — a ranked list of "which
    event types spiked and from which addresses" answers the
    investigative question without building a dossier on anyone.

    Rate-limiter internals are not exposed: ``app.core.rate_limit``
    keeps counters in memory (or Redis) keyed by bucket and client,
    with no durable history to report, so no rate-limit metric is
    invented here.
    """
    from datetime import timedelta

    since = datetime.utcnow() - timedelta(hours=hours)
    by_action = db.execute(
        select(AuditLog.action, func.count())
        .where(AuditLog.action.in_(list(SECURITY_INCIDENT_ACTIONS)), AuditLog.created_at >= since)
        .group_by(AuditLog.action)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    by_ip = db.execute(
        select(AuditLog.ip_address, func.count())
        .where(
            AuditLog.action.in_(list(SECURITY_INCIDENT_ACTIONS)),
            AuditLog.created_at >= since,
            AuditLog.ip_address.isnot(None),
        )
        .group_by(AuditLog.ip_address)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    locked = int(
        db.scalar(
            select(func.count()).select_from(User).where(User.locked_until.isnot(None), User.locked_until > datetime.utcnow())
        )
        or 0
    )
    return {
        "window_hours": hours,
        "events_by_action": [{"action": a, "count": int(c)} for a, c in by_action],
        "events_by_ip": [{"ip_address": ip, "count": int(c)} for ip, c in by_ip],
        "currently_locked_accounts": locked,
    }


# ===========================================================================
# 13. Platform search
# ===========================================================================


@router.get("/search")
def platform_search(
    q: str = Query(min_length=2, max_length=200),
    entities: str = Query(default="users,organizations,jobs", max_length=100),
    limit: int = Query(10, ge=1, le=25),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.AUDIT_ACCESS)),
):
    """Cross-entity administrative search.

    Implemented as separate, scoped, parameterized ORM queries per
    entity — never a unified raw-SQL endpoint (section 13 forbids
    one), and never a query built by string concatenation. Each
    entity block additionally re-checks the caller's permission for
    that domain, so a ``support_admin`` searching "acme" gets user
    hits and no organization hits rather than a blanket 403 or, worse,
    data they cannot otherwise reach.
    """
    requested = {e.strip() for e in entities.split(",") if e.strip()}
    needle = f"%{q.strip().lower()}%"
    out: dict[str, list] = {}

    if "users" in requested and actor.has(PlatformPermission.USER_MANAGEMENT):
        rows = db.scalars(
            select(User)
            .where(or_(func.lower(User.email).like(needle), func.lower(User.full_name).like(needle)))
            .order_by(User.id.desc())
            .limit(limit)
        ).all()
        out["users"] = [_user_summary(u) for u in rows]

    if "organizations" in requested and actor.has(PlatformPermission.ORGANIZATION_MANAGEMENT):
        rows = db.scalars(
            select(Organization)
            .where(func.lower(Organization.name).like(needle))
            .order_by(Organization.id.desc())
            .limit(limit)
        ).all()
        out["organizations"] = [_organization_summary(db, o, counts=False) for o in rows]

    if "jobs" in requested and actor.has(PlatformPermission.JOB_MODERATION):
        rows = db.scalars(
            select(Job)
            .where(or_(func.lower(Job.title).like(needle), func.lower(Job.organization).like(needle)))
            .order_by(Job.id.desc())
            .limit(limit)
        ).all()
        out["jobs"] = [_job_summary(j, include_internal=True) for j in rows]

    if "applications" in requested and actor.has(PlatformPermission.JOB_MODERATION):
        # Applications are searchable only by the JOB they belong to.
        # There is deliberately no way to search application content
        # or a candidate's submitted material from the admin surface
        # (spec sections 4 and 15).
        rows = db.execute(
            select(Applicant.id, Applicant.job_id, Applicant.status, Applicant.created_at, Job.title)
            .join(Job, Job.id == Applicant.job_id)
            .where(func.lower(Job.title).like(needle))
            .order_by(Applicant.id.desc())
            .limit(limit)
        ).all()
        out["applications"] = [
            {"id": aid, "job_id": jid, "job_title": title, "status": status, "created_at": created}
            for aid, jid, status, created, title in rows
        ]

    return {"query": q, "results": out}


# ===========================================================================
# 14. Analytics
# ===========================================================================


@router.get("/analytics")
def analytics(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.PLATFORM_ANALYTICS)),
):
    return platform_analytics.platform_analytics(db, days=days)


# ===========================================================================
# 16/17/18. System health
# ===========================================================================


@router.get("/system/health")
def system_health(
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.SYSTEM_CONFIGURATION)),
):
    return platform_health.system_health(db)


@router.get("/system/background-jobs")
def background_jobs(
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.SYSTEM_CONFIGURATION)),
):
    return platform_health.background_jobs(db)


class RetryEmailsIn(BaseModel):
    # Explicit ids only. There is intentionally no "retry everything"
    # switch and no way to name an arbitrary job to execute (section
    # 17): the only thing this endpoint can do is move specific,
    # already-FAILED email rows back to QUEUED.
    message_ids: list[int] = Field(min_length=1, max_length=100)


@router.post("/system/background-jobs/email/retry")
def retry_failed_emails(
    payload: RetryEmailsIn,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.SYSTEM_CONFIGURATION)),
):
    """Re-queue specific failed emails.

    Safe to retry because the V23.2 sender is idempotent per
    ``EmailMessage`` row: a row transitions QUEUED -> SENT once, and
    the row's ``dedupe_key`` already prevents a duplicate message ever
    being created for the same event. Rows not currently FAILED are
    skipped rather than reset, so this can never resurrect an email
    that was already delivered.
    """
    from app.models.domain import EmailMessage

    rows = db.scalars(select(EmailMessage).where(EmailMessage.id.in_(payload.message_ids))).all()
    requeued, skipped = [], []
    for row in rows:
        if row.status != "FAILED":
            skipped.append(row.id)
            continue
        row.status = "QUEUED"
        row.scheduled_at = datetime.utcnow()
        row.failed_at = None
        requeued.append(row.id)

    result = "success" if requeued and not skipped else ("partial" if requeued else "failure")
    record_platform_action(
        db,
        actor,
        action=PlatformAction.BULK_JOB_MODERATION,
        target_type="bulk",
        target_id="email_retry",
        metadata={"requeued": requeued, "skipped": skipped},
        result=result,
    )
    db.commit()
    return {"requeued": len(requeued), "skipped": len(skipped), "skipped_ids": skipped, "result": result}


@router.get("/system/ingestion")
def ingestion_status(
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.SYSTEM_CONFIGURATION)),
):
    return platform_health.ingestion_sources(db)


# ===========================================================================
# 19/20. Platform settings and maintenance mode
# ===========================================================================


@router.get("/settings")
def list_settings(
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.SYSTEM_CONFIGURATION)),
):
    return {"settings": describe_settings(db)}


class SettingIn(BaseModel):
    value: bool | int | str


@router.put("/settings/{key}")
def update_setting(
    key: str,
    payload: SettingIn,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.SYSTEM_CONFIGURATION)),
):
    """Change one typed platform setting.

    Unknown keys are rejected — the catalog in
    ``app.core.platform_settings`` is authoritative, so this endpoint
    cannot be used to write arbitrary configuration (which is exactly
    what section 19 rules out). Settings marked sensitive additionally
    require a full platform-admin role.

    The audit record is written in the SAME transaction as the change,
    so a setting cannot be altered without a corresponding entry.
    """
    definition = SETTING_DEFINITIONS.get(key)
    if definition is None:
        raise HTTPException(404, "Unknown platform setting")
    if definition.sensitive:
        require_sensitive_platform_action(actor)

    previous = get_setting(db, key)
    try:
        new_value = set_setting(db, key, payload.value, actor_user_id=actor.user_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    if key == "maintenance_mode":
        action = (
            PlatformAction.MAINTENANCE_MODE_ENABLED if new_value else PlatformAction.MAINTENANCE_MODE_DISABLED
        )
    else:
        action = PlatformAction.PLATFORM_SETTING_CHANGED

    record_platform_action(
        db,
        actor,
        action=action,
        target_type="platform_setting",
        target_id=key,
        metadata={"previous_value": previous, "new_value": new_value},
    )
    # Also raised as a security event so a settings change appears in
    # the security timeline alongside the authentication events an
    # investigator is correlating it against.
    from app.core.security_events import SecurityEvent, record_security_event

    record_security_event(
        db,
        SecurityEvent.PLATFORM_SETTING_CHANGED,
        entity_type="platform_setting",
        entity_id=key,
        detail=f"{previous!r} -> {new_value!r}",
    )
    db.commit()
    return {"key": key, "value": new_value, "previous_value": previous}


# ===========================================================================
# 21. Platform announcements
# ===========================================================================

AUDIENCES = ("ALL", "CANDIDATES", "RECRUITERS", "ORGANIZATION_ADMINS", "PLATFORM_ADMINS")


class AnnouncementIn(BaseModel):
    title: str = Field(min_length=3, max_length=220)
    message: str = Field(min_length=3, max_length=5000)
    audience: str = "ALL"
    channel: str = "IN_APP"
    scheduled_for: datetime | None = None

    @field_validator("audience")
    @classmethod
    def _audience(cls, value: str) -> str:
        if value not in AUDIENCES:
            raise ValueError(f"audience must be one of: {', '.join(AUDIENCES)}")
        return value

    @field_validator("channel")
    @classmethod
    def _channel(cls, value: str) -> str:
        if value not in ("IN_APP", "EMAIL", "BOTH"):
            raise ValueError("channel must be IN_APP, EMAIL or BOTH")
        return value


def _announcement_out(row: PlatformAnnouncement) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "message": row.message,
        "audience": row.audience,
        "channel": row.channel,
        "status": row.status,
        "created_by_user_id": row.created_by_user_id,
        "scheduled_for": row.scheduled_for,
        "sent_at": row.sent_at,
        "recipient_count": row.recipient_count,
        "created_at": row.created_at,
    }


@router.get("/announcements")
def list_announcements(
    limit: int = Query(25, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.CONTENT_MODERATION)),
):
    total = int(db.scalar(select(func.count()).select_from(PlatformAnnouncement)) or 0)
    rows = db.scalars(
        select(PlatformAnnouncement).order_by(PlatformAnnouncement.id.desc()).limit(limit).offset(offset)
    ).all()
    return _page(total, limit, offset, [_announcement_out(r) for r in rows])


@router.post("/announcements", status_code=201)
def create_announcement(
    payload: AnnouncementIn,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.CONTENT_MODERATION)),
):
    """Create an announcement in DRAFT. Sends nothing.

    Creation and sending are two separate, separately-audited requests
    precisely so no single call can mass-mail the platform by accident
    (spec section 21).
    """
    row = PlatformAnnouncement(
        title=payload.title.strip(),
        message=payload.message.strip(),
        audience=payload.audience,
        channel=payload.channel,
        scheduled_for=payload.scheduled_for,
        status="DRAFT",
        created_by_user_id=actor.user_id,
    )
    db.add(row)
    db.flush()
    record_platform_action(
        db,
        actor,
        action=PlatformAction.ANNOUNCEMENT_CREATED,
        target_type="announcement",
        target_id=row.id,
        metadata={"audience": payload.audience, "channel": payload.channel},
    )
    db.commit()
    db.refresh(row)
    return _announcement_out(row)


def _announcement_recipient_ids(db: Session, audience: str, cap: int) -> list[int]:
    query = select(User.id).where(User.active.is_(True))
    if audience == "CANDIDATES":
        query = query.where(User.role == "candidate")
    elif audience == "RECRUITERS":
        query = query.where(User.role == "recruiter")
    elif audience == "PLATFORM_ADMINS":
        query = query.where(User.role.in_(("admin", "super_admin", "system_admin", "support_admin")))
    elif audience == "ORGANIZATION_ADMINS":
        org_admins = select(OrganizationMember.user_id).where(
            OrganizationMember.status == "ACTIVE", OrganizationMember.role.in_(("OWNER", "ADMIN"))
        )
        query = query.where(User.id.in_(org_admins))
    return list(db.scalars(query.limit(cap)).all())


@router.post("/announcements/{announcement_id}/send")
def send_announcement(
    announcement_id: int,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.CONTENT_MODERATION)),
):
    """Deliver a DRAFT announcement.

    Guards against accidental mass sending, in order:
      1. Only a DRAFT can be sent — a re-POST of an already-SENT
         announcement is refused, so a double-click or a retried
         request cannot send twice.
      2. The recipient list is capped by the
         ``announcement_max_recipients`` platform setting.
      3. Email delivery additionally requires the
         ``announcement_email_enabled`` setting; with it off, an
         EMAIL/BOTH announcement delivers in-app only and says so in
         the response rather than silently doing nothing.
      4. Sending requires a full platform-admin role.

    Delivery reuses V23.1 in-app notifications and the V23.2 email
    queue — no new notification infrastructure (section 21). Each
    recipient's notification carries a per-announcement ``dedupe_key``,
    so a partially-completed send that is retried will not double-post
    to anyone who already received it.
    """
    require_sensitive_platform_action(actor)
    row = db.get(PlatformAnnouncement, announcement_id)
    if not row:
        raise HTTPException(404, "Announcement not found")
    if row.status != "DRAFT":
        raise HTTPException(409, f"Announcement is {row.status} and cannot be sent again")

    cap = int(get_setting(db, "announcement_max_recipients"))
    email_allowed = bool(get_setting(db, "announcement_email_enabled"))
    recipient_ids = _announcement_recipient_ids(db, row.audience, cap)

    row.status = "SENDING"
    db.flush()

    from app.notifications.service import create_notification

    delivered = 0
    for user_id in recipient_ids:
        try:
            created = create_notification(
                db,
                user_id,
                notification_type="platform_announcement",
                category="SYSTEM",
                priority="NORMAL",
                title=row.title,
                message=row.message,
                dedupe_key=f"platform_announcement:{row.id}",
            )
            if created is not None:
                delivered += 1
        except Exception:
            # One bad recipient must not abort the whole send; the
            # partial result is reported honestly below.
            continue

    emails_queued = 0
    if row.channel in ("EMAIL", "BOTH") and email_allowed:
        emails_queued = _queue_announcement_emails(db, row, recipient_ids)

    row.status = "SENT"
    row.sent_at = datetime.utcnow()
    row.recipient_count = delivered
    result = "success" if delivered == len(recipient_ids) else "partial"
    record_platform_action(
        db,
        actor,
        action=PlatformAction.ANNOUNCEMENT_SENT,
        target_type="announcement",
        target_id=row.id,
        metadata={
            "audience": row.audience,
            "channel": row.channel,
            "targeted": len(recipient_ids),
            "delivered": delivered,
            "emails_queued": emails_queued,
            "email_channel_allowed": email_allowed,
        },
        result=result,
    )
    db.commit()
    return {
        **_announcement_out(row),
        "targeted": len(recipient_ids),
        "delivered": delivered,
        "emails_queued": emails_queued,
        "email_channel_allowed": email_allowed,
        "result": result,
        "note": (
            None
            if email_allowed or row.channel == "IN_APP"
            else "Email delivery is disabled by the announcement_email_enabled platform setting; "
            "this announcement was delivered in-app only."
        ),
    }


def _queue_announcement_emails(db: Session, row: PlatformAnnouncement, recipient_ids: list[int]) -> int:
    """Queue announcement emails through the existing V23.2 service.

    Uses the pre-existing SYSTEM_NOTIFICATION template rather than
    introducing a new one, and passes a per-(announcement, user)
    ``dedupe_key`` so the queue itself refuses a duplicate. If the
    template is unavailable in a given deployment, ``queue_email``
    returns None per its own contract and this reports zero queued
    rather than raising.
    """
    from app.email.service import queue_email

    queued = 0
    users = db.scalars(select(User).where(User.id.in_(recipient_ids))).all()
    for user in users:
        try:
            message = queue_email(
                db,
                user_id=user.id,
                recipient=user.email,
                template_key="SYSTEM_NOTIFICATION",
                variables={"full_name": user.full_name, "title": row.title, "message": row.message},
                category="SYSTEM",
                dedupe_key=f"platform_announcement:{row.id}:{user.id}",
            )
            if message is not None:
                queued += 1
        except Exception:
            continue
    return queued


# ===========================================================================
# 27. Bulk actions
# ===========================================================================


class BulkJobModerationIn(BaseModel):
    job_ids: list[int] = Field(min_length=1, max_length=50)
    action: str
    reason: str | None = None
    note: str | None = Field(default=None, max_length=4000)

    @field_validator("action")
    @classmethod
    def _action(cls, value: str) -> str:
        if value not in ("approve", "reject", "suspend", "restore"):
            raise ValueError("action must be approve, reject, suspend or restore")
        return value


@router.post("/bulk/jobs/moderate")
def bulk_moderate_jobs(
    payload: BulkJobModerationIn,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.JOB_MODERATION)),
):
    """Apply one moderation action to up to 50 jobs.

    Design decisions, all of them section 27's requirements:

    - **Bounded** (50 per request) — there is no "moderate everything
      matching this filter" form, which would make a mis-clicked
      filter catastrophic.
    - **No bulk deletion exists.** The only actions are the four
      reversible status transitions.
    - **Per-item auditing**: every successful item gets its own audit
      record, in addition to one summary record for the batch, so the
      trail for an individual job is complete whether it was moderated
      alone or in a batch.
    - **Partial failure is reported, not hidden**: one invalid item
      (already suspended, not found) does not abort the batch, and the
      response names exactly which items failed and why.
    - **Transaction safety**: one commit at the end, so the batch and
      all of its audit records land together or not at all.
    """
    if payload.action in ("reject", "suspend"):
        if not payload.reason:
            raise HTTPException(422, f"reason is required for bulk {payload.action}")
        job_moderation.validate_reason(payload.reason)

    succeeded: list[int] = []
    failed: list[dict] = []

    for job_id in payload.job_ids:
        job = db.get(Job, job_id)
        if job is None:
            failed.append({"job_id": job_id, "error": "not found"})
            continue
        previous = job.status
        try:
            if payload.action == "approve":
                job_moderation.approve_job(db, job, actor_user_id=actor.user_id, note=payload.note)
                item_action = PlatformAction.JOB_APPROVED
            elif payload.action == "reject":
                job_moderation.reject_job(
                    db, job, reason=payload.reason, actor_user_id=actor.user_id, note=payload.note
                )
                item_action = PlatformAction.JOB_REJECTED
            elif payload.action == "suspend":
                job_moderation.suspend_job(
                    db, job, reason=payload.reason, actor_user_id=actor.user_id, note=payload.note
                )
                item_action = PlatformAction.JOB_SUSPENDED
            else:
                job_moderation.restore_job(db, job, actor_user_id=actor.user_id, note=payload.note)
                item_action = PlatformAction.JOB_RESTORED
        except HTTPException as exc:
            failed.append({"job_id": job_id, "error": exc.detail})
            continue

        record_platform_action(
            db,
            actor,
            action=item_action,
            target_type="job",
            target_id=job.id,
            reason=payload.reason,
            note=payload.note,
            metadata={"from_status": previous, "to_status": job.status, "bulk": True},
        )
        succeeded.append(job_id)

    result = "success" if not failed else ("partial" if succeeded else "failure")
    record_platform_action(
        db,
        actor,
        action=PlatformAction.BULK_JOB_MODERATION,
        target_type="bulk",
        target_id=payload.action,
        reason=payload.reason,
        note=payload.note,
        metadata={"requested": len(payload.job_ids), "succeeded": succeeded, "failed_count": len(failed)},
        result=result,
    )
    db.commit()
    return {
        "action": payload.action,
        "requested": len(payload.job_ids),
        "succeeded": succeeded,
        "failed": failed,
        "result": result,
    }
