"""V25.3 — organization hiring intelligence API (sections 10, 11, 22).

TENANT ISOLATION
----------------
Every route depends on ``require_organization_membership`` (V25.1),
which is the single place in the codebase that answers "is this user
in this organization". A non-member receives **404**, identical to a
nonexistent organization, and the attempt is recorded as a
``cross_tenant_access_attempt`` security event by that dependency —
so probing another tenant's intelligence is both fruitless and
visible. A platform-suspended organization also fails that check
(V25.2), because it flips the same ``is_active`` flag the dependency
already tests.

The ``organization_id`` in the path is therefore not trusted as
authorization; it is authorized, and only then used to derive member
ids inside the service layer. No route accepts an owner-id list or
any other identifier that could widen the scope.

No route here returns a candidate-level row. Applicant-pool analysis
is aggregate, floored by the privacy threshold, and never names or
identifies a person.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.organizations import require_organization_membership
from app.core.rate_limit import enforce_rate_limit
from app.core.security import current_user
from app.db.session import get_db
from app.intelligence import ai as intelligence_ai
from app.intelligence import corpus as corpus_mod
from app.intelligence import organization as organization_intel
from app.models.domain import Organization, OrganizationMember, User

router = APIRouter(tags=["V25.3 Data Intelligence"])


@router.get("/organizations/{organization_id}/intelligence")
def organization_intelligence(
    organization_id: int,
    days: int = Query(90, ge=1, le=corpus_mod.MAX_RANGE_DAYS),
    context: tuple[Organization, OrganizationMember] = Depends(require_organization_membership),
    db: Session = Depends(get_db),
):
    """Full hiring intelligence for one organization.

    Hiring metrics are V24.4's calculations, called with this
    organization's member ids; the skill demand, candidate-pool gap
    and difficult-to-fill blocks are V25.3's additions.
    """
    return organization_intel.full_intelligence(db, organization_id, days=days)


@router.get("/organizations/{organization_id}/intelligence/hiring")
def hiring(
    organization_id: int,
    days: int = Query(90, ge=1, le=corpus_mod.MAX_RANGE_DAYS),
    context: tuple[Organization, OrganizationMember] = Depends(require_organization_membership),
    db: Session = Depends(get_db),
):
    return organization_intel.hiring_overview(db, organization_id, days=days)


@router.get("/organizations/{organization_id}/intelligence/skill-demand")
def skill_demand(
    organization_id: int,
    days: int | None = Query(default=None, ge=1, le=corpus_mod.MAX_RANGE_DAYS),
    limit: int = Query(25, ge=1, le=100),
    context: tuple[Organization, OrganizationMember] = Depends(require_organization_membership),
    db: Session = Depends(get_db),
):
    return organization_intel.skill_demand(db, organization_id, days=days, limit=limit)


@router.get("/organizations/{organization_id}/intelligence/candidate-pool")
def candidate_pool(
    organization_id: int,
    context: tuple[Organization, OrganizationMember] = Depends(require_organization_membership),
    db: Session = Depends(get_db),
):
    """Aggregate skill coverage of this organization's own applicant pool.

    Suppressed entirely below the configured group-size floor, so a
    small pool cannot be used to work out an individual applicant's
    skills.
    """
    return organization_intel.candidate_pool_skill_gaps(db, organization_id)


@router.get("/organizations/{organization_id}/intelligence/difficult-to-fill")
def difficult_to_fill(
    organization_id: int,
    limit: int = Query(20, ge=1, le=100),
    context: tuple[Organization, OrganizationMember] = Depends(require_organization_membership),
    db: Session = Depends(get_db),
):
    return organization_intel.difficult_to_fill(db, organization_id, limit=limit)


@router.get("/organizations/{organization_id}/intelligence/job-performance")
def job_performance(
    organization_id: int,
    limit: int = Query(20, ge=1, le=100),
    context: tuple[Organization, OrganizationMember] = Depends(require_organization_membership),
    db: Session = Depends(get_db),
):
    return organization_intel.job_performance(db, organization_id, limit=limit)


class AIInsightsIn(BaseModel):
    force: bool = False


@router.post("/organizations/{organization_id}/ai-insights")
def ai_insights(
    organization_id: int,
    payload: AIInsightsIn,
    request: Request,
    context: tuple[Organization, OrganizationMember] = Depends(require_organization_membership),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """A grounded narrative over this organization's own analytics.

    The deterministic payload is computed first and returned under
    ``analysis`` in the same response. The model receives only counts,
    percentages, skill names and short job titles from that payload —
    never a job description, a recruiter note, a cover note, a resume,
    or any candidate detail. The AI cache is keyed on
    ``(org_intelligence, organization_id)`` plus a hash of
    those facts, so one organization's generated insight can never be
    served to another.
    """
    enforce_rate_limit(request, bucket="ai")
    analysis = organization_intel.full_intelligence(db, organization_id)
    content, cached = intelligence_ai.organization_insights(
        db, user_id=user.id, organization_id=organization_id, payload=analysis, force=payload.force
    )
    return {"analysis": analysis, "ai": content, "cached": cached}
