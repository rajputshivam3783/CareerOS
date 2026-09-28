"""V18.6 — shared-team-access resolution.

Widens `app.api.company.CompanyTeamMember` from a pure roster (V18.4,
visibility only) into real shared access: any two recruiters on the same
company team can see and manage each other's jobs, applicants, interviews,
and offers. Kept as its own tiny module — rather than folding into
`app.api.company` or `app.api.recruiter` — since both of those import it,
and importing `app.api.recruiter` from `app.api.company` (or vice versa)
would create a circular import.

Does not touch Authentication or Security: this only changes which
`Job.owner_user_id` rows a request is allowed to read/write, computed
fresh per-request from the existing `Organization`/`CompanyTeamMember`
tables — no new role, no new token, no persisted "acting as" state.

V25.1 UPDATE — Multi-Tenant Architecture: this now prefers the formal
`OrganizationMember` table (see app.core.organizations) when the
resolved organization has any ACTIVE membership rows there, falling
back to the original V18.4 `CompanyTeamMember`-only resolution
otherwise. This is the single chokepoint every recruiter-facing
job/candidate-discovery/pipeline/analytics/AI query already filters
through (see this module's own docstring above), so this one change
is what makes all of those org-isolated per spec section 8/27 without
touching each of those call sites individually. A SUSPENDED or REMOVED
OrganizationMember is correctly excluded (unlike the legacy
CompanyTeamMember table, which has no such states) — this is a
strictly narrower, more correct result for any org that has been
backfilled (see scripts/migrate_v25_1_backfill_organizations.py), never
a wider one, so no existing recruiter loses access they had before.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import CompanyTeamMember, Organization, OrganizationMember, User


def _formally_excluded(db: Session, organization_id: int, user_id: int) -> bool:
    """V25.6 — True if this user has a formal ``OrganizationMember`` row for the
    organization whose status is anything other than ACTIVE (SUSPENDED / REMOVED /
    PENDING).

    Why this exists: ``suspend_member`` / ``remove_member`` (app.api.organizations) only
    change the ``OrganizationMember`` row. A user who is *also* the organization's legacy
    ``owner_user_id`` or still has a legacy ``CompanyTeamMember`` row used to be resolved
    to the organization anyway, and then received every active member's jobs, candidates,
    pipeline and analytics. An explicit non-ACTIVE membership must win over the legacy
    signals. A user with NO formal row at all (never backfilled) is unaffected, which
    preserves pre-V25.1 behaviour."""
    row = db.scalars(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id, OrganizationMember.user_id == user_id
        )
    ).first()
    return row is not None and row.status != "ACTIVE"


def _resolve_organization(db: Session, user: User) -> Organization | None:
    """Pick the organization whose team ``user`` belongs to, skipping any organization in
    which the user has been suspended/removed. Candidates, in priority order (unchanged
    from V25.1): the legacy organization they own, their legacy team membership, then
    their first ACTIVE formal membership."""
    candidates: list[Organization] = []

    owned = db.scalars(select(Organization).where(Organization.owner_user_id == user.id)).first()
    if owned is not None:
        candidates.append(owned)

    legacy_membership = db.scalars(select(CompanyTeamMember).where(CompanyTeamMember.user_id == user.id)).first()
    if legacy_membership is not None:
        legacy_org = db.get(Organization, legacy_membership.company_id)
        if legacy_org is not None:
            candidates.append(legacy_org)

    for member_row in db.scalars(
        select(OrganizationMember).where(OrganizationMember.user_id == user.id, OrganizationMember.status == "ACTIVE")
    ).all():
        formal_org = db.get(Organization, member_row.organization_id)
        if formal_org is not None:
            candidates.append(formal_org)

    for org in candidates:
        if not _formally_excluded(db, org.id, user.id):
            return org
    return None


def team_owner_ids(db: Session, user: User) -> list[int]:
    """Every user_id whose ATS resources `user` may access: always their
    own id, plus — if they own or belong to a company — every other
    member of that company's team.

    A recruiter who has no company profile and isn't on anyone's team
    just gets back their own id, matching pre-V18.6 behavior exactly —
    this is additive, not a narrowing of what solo recruiters could
    already do.

    V25.6: an organization in which the user is SUSPENDED or REMOVED is never used (see
    ``_formally_excluded``). Note the deliberate residual behaviour: a user's *own* id is
    always included, so jobs they personally created remain reachable by them; see
    docs/V25_FINAL_SECURITY_AND_COMPLIANCE_AUDIT.md (remaining risks).
    """
    ids = {user.id}

    org = _resolve_organization(db, user)
    if org is None:
        return list(ids)

    org_members = db.scalars(
        select(OrganizationMember.user_id).where(
            OrganizationMember.organization_id == org.id, OrganizationMember.status == "ACTIVE"
        )
    ).all()
    if org_members:
        # Formal membership exists for this org — it is the source of
        # truth (correctly excludes SUSPENDED/REMOVED users the legacy
        # table below has no concept of).
        ids.update(org_members)
        return list(ids)

    # Legacy fallback: this org has never been touched by V25.1 (no
    # OrganizationMember rows at all yet) — resolve exactly as before.
    if org.owner_user_id is not None:
        ids.add(org.owner_user_id)
    legacy_members = db.scalars(select(CompanyTeamMember).where(CompanyTeamMember.company_id == org.id)).all()
    ids.update(m.user_id for m in legacy_members)

    return list(ids)
