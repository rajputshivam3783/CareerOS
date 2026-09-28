"""V25.3 — platform job-market intelligence API (sections 6-9, 22).

AUTHORIZATION AND SCOPE
-----------------------
These endpoints report aggregate, published-job activity — the same
listings any authenticated user can already browse and search. They
require authentication (``current_user``) but no special role, since
a candidate deciding what to learn is the primary audience.

What they never expose, regardless of caller:

- any organization-private figure. The corpus is published jobs
  platform-wide; there is no ``organization_id`` parameter on any
  route here, so one organization's hiring data cannot be isolated
  through this router. Organization-scoped intelligence lives behind
  V25.1 membership authorization in ``organization_intelligence.py``.
- any candidate's data, aggregate or otherwise. Nothing in this
  router reads a profile, resume, application or candidate location.

Every response carries ``scope: "careeros_platform"`` — see
``app.intelligence.market`` for why that label is load-bearing rather
than decorative.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import current_user
from app.db.session import get_db
from app.intelligence import corpus as corpus_mod
from app.intelligence import market as market_intel
from app.models.domain import User

router = APIRouter(prefix="/market-intelligence", tags=["V25.3 Data Intelligence"])


def _spec(
    days: int | None,
    role: str | None,
    location: str | None,
    category: str | None,
    job_type: str | None,
    work_mode: str | None,
    employment_type: str | None,
) -> corpus_mod.CorpusFilter:
    """Build the shared corpus filter.

    ``owner_user_ids`` is never set from a request parameter here.
    That field is what scopes a corpus to one organization, and it is
    reachable only through the organization router, which authorizes
    membership first.
    """
    return corpus_mod.CorpusFilter(
        days=days,
        role_query=role,
        location=location,
        category=category,
        job_type=job_type,
        work_mode=work_mode,
        employment_type=employment_type,
    )


def _filters(
    days: int | None = Query(default=None, ge=1, le=corpus_mod.MAX_RANGE_DAYS),
    role: str | None = Query(default=None, max_length=160),
    location: str | None = Query(default=None, max_length=160),
    category: str | None = Query(default=None, max_length=100),
    job_type: str | None = Query(default=None, max_length=40),
    work_mode: str | None = Query(default=None, max_length=20),
    employment_type: str | None = Query(default=None, max_length=40),
) -> corpus_mod.CorpusFilter:
    return _spec(days, role, location, category, job_type, work_mode, employment_type)


@router.get("/overview")
def overview(
    spec: corpus_mod.CorpusFilter = Depends(_filters),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return market_intel.overview(db, spec)


@router.get("/skills")
def skills(
    limit: int = Query(25, ge=1, le=100),
    spec: corpus_mod.CorpusFilter = Depends(_filters),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return market_intel.skill_demand(db, spec, limit=limit)


@router.get("/roles")
def roles(
    limit: int = Query(25, ge=1, le=100),
    spec: corpus_mod.CorpusFilter = Depends(_filters),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return market_intel.role_demand(db, spec, limit=limit)


@router.get("/trends")
def trends(
    limit: int = Query(20, ge=1, le=100),
    spec: corpus_mod.CorpusFilter = Depends(_filters),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Skill and volume trends across two equal adjacent periods."""
    return {
        "skills": market_intel.skill_trends(db, spec, limit=limit),
        "volume": market_intel.volume_trends(db, spec),
    }


@router.get("/locations")
def locations(
    limit: int = Query(20, ge=1, le=50),
    spec: corpus_mod.CorpusFilter = Depends(_filters),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return market_intel.location_intelligence(db, spec, limit=limit)


@router.get("/salary")
def salary(
    spec: corpus_mod.CorpusFilter = Depends(_filters),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Salary DISCLOSURE coverage — not salary analytics.

    CareerOS stores pay as unvalidated free text, so no distribution,
    median or salary-by-role breakdown exists to return. The response
    says so explicitly and reports what is genuinely measurable: how
    many listings disclose pay at all.
    """
    return {
        "scope": market_intel.SCOPE,
        "scope_label": market_intel.SCOPE_LABEL,
        "filters": spec.describe(),
        **market_intel.salary_disclosure(db, spec),
    }
