"""V25.2 — platform account and organization lifecycle transitions.

One module owns every transition between ACTIVE / SUSPENDED /
DEACTIVATED, for both users and organizations, so the invariants below
hold everywhere instead of being re-derived per endpoint.

THE INVARIANTS
--------------

1. **Nothing is destroyed to disable access.** Every transition here
   is a flag change. No row is deleted, no application is removed, no
   audit record is touched, no organization membership is severed. A
   suspension is reversible by construction — which is why the spec
   (section 26) asks for reversible state changes and why "restore"
   is a real operation rather than a re-creation.

2. **The new lifecycle column never becomes a second gate.**
   ``User.active`` remains the single flag every authentication path
   checks (``app.core.security.current_user``), and
   ``Organization.is_active`` remains the single flag every V25.1
   tenancy check reads (``app.core.organizations``). The
   ``account_status`` / ``status`` columns are kept in lockstep with
   them here. That ordering matters: if the two ever disagreed, the
   one that governs access is still the old, well-tested one, so the
   failure mode is a wrong label in the admin UI rather than a
   security hole.

3. **Platform status and organization membership status are
   independent.** Suspending a user at the platform level does not
   remove or alter their ``OrganizationMember`` rows, and suspending
   an organization does not change any member's platform account
   status. Spec section 5 asks for these to be clearly distinguished;
   keeping both writes in one file is how that stays true.

EXACT SUSPENSION BEHAVIOUR (spec sections 5 and 7)
--------------------------------------------------

**Suspended user**
  - Cannot authenticate: ``active=False`` is checked by
    ``current_user``/``optional_user``, so existing access tokens stop
    working on their next request and refresh fails.
  - Active sessions are revoked, so a live session is not left usable
    for the remainder of its access-token lifetime.
  - Applications, application history, notifications, uploaded
    documents and audit records are all preserved untouched.
  - Organization memberships are preserved untouched. Removing
    someone from an organization is a separate, organization-level
    workflow (V25.1) with its own authorization.

**Reactivated user**
  - ``active=True``, status ACTIVE, suspension fields cleared,
    ``failed_login_count`` reset (so they are not immediately
    re-locked by failures accumulated while suspended).
  - ``lock_count`` is deliberately NOT reset — it is the escalation
    counter for automatic lockout durations (see
    app.core.account_lockout), and clearing it would reward an
    attacker for having got an account suspended.

**Suspended organization**
  - ``is_active=False``, so every V25.1 organization-scoped
    dependency fails closed exactly as it does for a nonexistent
    organization: members cannot read or write organization
    resources through /organizations/{id}/... endpoints.
  - **Jobs**: every currently ``published`` job belonging to the
    organization is moved to ``suspended`` with reason
    ``organization_suspended`` and its prior status recorded, so
    reactivation restores precisely the set that was live — no
    candidate-facing listing outlives the suspension, and nothing is
    deleted. Jobs already in review/rejected/closed are left alone.
  - **Applications**: untouched and still readable by the candidates
    who made them. A candidate's own history must not disappear
    because a company was suspended.
  - **Members' platform accounts**: untouched. Being in a suspended
    organization is not misconduct by the individual.
  - **Notifications**: none are sent to candidates, and none of the
    organization's members are told the reason. The reason is an
    internal moderation record (spec sections 7 and 9).

**Reactivated organization**
  - ``is_active=True``, status ACTIVE, suspension fields cleared, and
    every job suspended *by that suspension* is restored to the exact
    status it held beforehand.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import Job, Organization, OrganizationMember, User

log = logging.getLogger("careeros.platform_lifecycle")

ACCOUNT_STATUSES: tuple[str, ...] = ("ACTIVE", "SUSPENDED", "DEACTIVATED")
ORGANIZATION_STATUSES: tuple[str, ...] = ("ACTIVE", "SUSPENDED", "DEACTIVATED")

# Reason codes shared by user and organization suspension. Kept in one
# place so the admin UI dropdown, the API validation and the audit
# trail can never drift apart.
SUSPENSION_REASONS: tuple[str, ...] = (
    "policy_violation",
    "suspicious_activity",
    "fraudulent_activity",
    "spam",
    "abuse_report",
    "security_concern",
    "payment_issue",
    "requested_by_user",
    "other",
)

# The marker written to Job.moderation_reason when a job was suspended
# as a side effect of its organization's suspension, so reactivation
# can restore exactly that set and nothing else.
ORGANIZATION_SUSPENSION_JOB_REASON = "organization_suspended"


def derive_account_status(user: User) -> str:
    """The lifecycle state of a user row, tolerating rows written
    before this column existed.

    Old rows have ``account_status`` defaulted to ACTIVE by the
    migration, which is right for the overwhelming majority — but a
    user deactivated pre-V25.2 (``active=False``) would then be
    mislabelled. Rather than a backfill that has to guess at intent,
    the label is derived: an inactive account with a recorded
    suspension is SUSPENDED, an inactive account without one is
    DEACTIVATED, and an active account is ACTIVE regardless of what
    the column says.
    """
    if user.active:
        return "ACTIVE"
    if user.suspended_at is not None:
        return "SUSPENDED"
    return "DEACTIVATED"


def suspend_user(db: Session, user: User, *, reason: str, note: str | None = None) -> None:
    """Suspend a platform account. See the module docstring for the
    exact, complete list of what this does and does not touch.

    Does not commit — the caller commits this together with its audit
    record so the two are atomic.
    """
    user.active = False
    user.account_status = "SUSPENDED"
    user.suspended_at = datetime.utcnow()
    # Stored for the admin UI. Never surfaced to the suspended user
    # themselves through any endpoint, and never included in a
    # notification.
    user.suspension_reason = (f"{reason}: {note}" if note else reason)[:500]
    _revoke_sessions(db, user)


def deactivate_user(db: Session, user: User, *, reason: str, note: str | None = None) -> None:
    """Administratively deactivate an account.

    Distinct from suspension only in intent and label: deactivation is
    the end-state for an account that should not come back (a closure
    request, a duplicate), suspension is a hold. Both are reversible
    by ``reactivate_user`` — spec section 26 asks that destructive
    actions not be irreversible unless required, and nothing here
    requires it.
    """
    user.active = False
    user.account_status = "DEACTIVATED"
    user.suspended_at = datetime.utcnow()
    user.suspension_reason = (f"{reason}: {note}" if note else reason)[:500]
    _revoke_sessions(db, user)


def reactivate_user(db: Session, user: User) -> None:
    user.active = True
    user.account_status = "ACTIVE"
    user.suspended_at = None
    user.suspension_reason = None
    user.locked_until = None
    user.failed_login_count = 0
    # lock_count intentionally preserved — see module docstring.


def _revoke_sessions(db: Session, user: User) -> None:
    """Best-effort revocation of a suspended user's live sessions.

    Best-effort because ``active=False`` is already sufficient to stop
    every subsequent authenticated request; this only closes the
    window in which an already-issued, still-unexpired access token
    would otherwise keep working. A failure here must not prevent the
    suspension itself from being applied.
    """
    try:
        from app.core.sessions import revoke_all_sessions

        revoke_all_sessions(db, user)
    except Exception:  # pragma: no cover - defensive
        log.warning("Could not revoke sessions for user %s during suspension", user.id, exc_info=True)


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------


def derive_organization_status(org: Organization) -> str:
    """Same rationale as ``derive_account_status``: label an
    organization from the flag that actually governs access, so a
    pre-V25.2 row deactivated through the V25.1 API is reported
    honestly rather than as ACTIVE."""
    if org.is_active:
        return "ACTIVE"
    if org.suspended_at is not None:
        return "SUSPENDED"
    return "DEACTIVATED"


def _organization_job_query(organization_id: int, member_user_ids: list[int]):
    """Jobs belonging to an organization.

    A Job has no direct organization FK (``Job.organization_id`` points
    at ``government_organizations``, a different table — see that
    model). Ownership of a recruiter-posted job runs through
    ``Job.owner_user_id`` and the organization's member list, which is
    the same relationship ``app.core.team_access`` already uses to
    scope every recruiter-facing query. Reusing it here keeps one
    definition of "this organization's jobs" instead of inventing a
    second.
    """
    if not member_user_ids:
        return None
    return select(Job).where(Job.owner_user_id.in_(member_user_ids))


def organization_member_ids(db: Session, organization_id: int, *, active_only: bool = True) -> list[int]:
    query = select(OrganizationMember.user_id).where(OrganizationMember.organization_id == organization_id)
    if active_only:
        query = query.where(OrganizationMember.status == "ACTIVE")
    return list(db.scalars(query).all())


def suspend_organization(
    db: Session, org: Organization, *, reason: str, note: str | None = None, deactivate: bool = False
) -> dict:
    """Suspend (or deactivate) an organization and unpublish its live
    jobs. Returns a small summary for the audit record.

    Does not commit; see ``suspend_user``.
    """
    org.is_active = False
    org.status = "DEACTIVATED" if deactivate else "SUSPENDED"
    org.suspended_at = datetime.utcnow()
    org.suspension_reason = (f"{reason}: {note}" if note else reason)[:500]

    member_ids = organization_member_ids(db, org.id)
    suspended_jobs = 0
    query = _organization_job_query(org.id, member_ids)
    if query is not None:
        for job in db.scalars(query.where(Job.status == "published")).all():
            job.pre_moderation_status = job.status
            job.status = "suspended"
            job.moderation_reason = ORGANIZATION_SUSPENSION_JOB_REASON
            job.moderated_at = datetime.utcnow()
            suspended_jobs += 1
            _sync_search(db, job.id)

    return {"member_count": len(member_ids), "jobs_suspended": suspended_jobs}


def reactivate_organization(db: Session, org: Organization) -> dict:
    """Reverse a suspension, restoring exactly the jobs it unpublished.

    Only jobs carrying the ``organization_suspended`` marker are
    restored: a job an administrator suspended individually, for its
    own policy violation, stays suspended. Reactivating the company
    must not silently undo an unrelated moderation decision.
    """
    org.is_active = True
    org.status = "ACTIVE"
    org.suspended_at = None
    org.suspension_reason = None

    member_ids = organization_member_ids(db, org.id)
    restored = 0
    query = _organization_job_query(org.id, member_ids)
    if query is not None:
        rows = db.scalars(
            query.where(
                Job.status == "suspended",
                Job.moderation_reason == ORGANIZATION_SUSPENSION_JOB_REASON,
            )
        ).all()
        for job in rows:
            job.status = job.pre_moderation_status or "published"
            job.pre_moderation_status = None
            job.moderation_reason = None
            job.moderated_at = datetime.utcnow()
            restored += 1
            _sync_search(db, job.id)

    return {"member_count": len(member_ids), "jobs_restored": restored}


def _sync_search(db: Session, job_id: int) -> None:
    """Keep the V21.1 search index consistent with a status change.

    Wrapped because search indexing is a derived cache: if it fails,
    the moderation decision itself must still stand. The index is
    rebuilt periodically anyway (see settings.search_reindex_interval_minutes).
    """
    try:
        from app.search.hooks import sync_job

        sync_job(db, job_id)
    except Exception:  # pragma: no cover - defensive
        log.warning("Search sync failed for job %s", job_id, exc_info=True)
