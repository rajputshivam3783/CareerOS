"""V25.3 — candidate career intelligence API (spec sections 2, 4, 5, 22).

AUTHORIZATION
-------------
Every endpoint derives the candidate from ``Depends(current_user)``
and passes ``user.id`` to the service layer. **No endpoint here
accepts a user id, candidate id, or any other identity parameter**,
so there is no id for a caller to manipulate — a candidate cannot
request another candidate's intelligence because the API provides no
way to name one.

That is the structural version of the section 26 requirement, and it
is why the corresponding security test asserts the absence of such a
parameter rather than merely that a forged one is rejected.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.rate_limit import enforce_rate_limit
from app.core.security import current_user
from app.db.session import get_db
from app.intelligence import ai as intelligence_ai
from app.intelligence import candidate as candidate_intel
from app.intelligence import corpus as corpus_mod
from app.intelligence import roles as roles_mod
from app.models.domain import User

router = APIRouter(prefix="/career-intelligence", tags=["V25.3 Data Intelligence"])

MAX_ROLE_LENGTH = 160


def _spec(days: int | None, location: str | None, category: str | None) -> corpus_mod.CorpusFilter:
    return corpus_mod.CorpusFilter(days=days, location=location, category=category)


@router.get("/overview")
def overview(
    role: str | None = Query(default=None, max_length=MAX_ROLE_LENGTH),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Career overview: profile completeness, skills, activity, target role."""
    return candidate_intel.overview(db, user.id, explicit_role=role)


@router.get("/skills")
def skills(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """The candidate's own normalized skill set and its sources."""
    return candidate_intel.skill_profile(db, user.id)


@router.get("/relevant-skills")
def relevant_skills(
    role: str | None = Query(default=None, max_length=MAX_ROLE_LENGTH),
    limit: int = Query(20, ge=1, le=50),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Skills appearing most often in CareerOS jobs relevant to this candidate."""
    return candidate_intel.relevant_market_skills(db, user.id, explicit_role=role, limit=limit)


@router.get("/skill-gaps")
def skill_gaps(
    role: str | None = Query(default=None, max_length=MAX_ROLE_LENGTH),
    days: int | None = Query(default=None, ge=1, le=corpus_mod.MAX_RANGE_DAYS),
    location: str | None = Query(default=None, max_length=160),
    category: str | None = Query(default=None, max_length=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Deterministic gap analysis against the target role's real listings."""
    return candidate_intel.skill_gaps(
        db, user.id, explicit_role=role, spec=_spec(days, location, category)
    )


@router.get("/roles/{role}")
def role_analysis(
    role: str,
    days: int | None = Query(default=None, ge=1, le=corpus_mod.MAX_RANGE_DAYS),
    location: str | None = Query(default=None, max_length=160),
    category: str | None = Query(default=None, max_length=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Analysis for one explicitly named role."""
    return candidate_intel.target_role_analysis(
        db, user.id, explicit_role=role[:MAX_ROLE_LENGTH], spec=_spec(days, location, category)
    )


@router.get("/roles")
def available_roles(
    days: int | None = Query(default=None, ge=1, le=corpus_mod.MAX_RANGE_DAYS),
    limit: int = Query(25, ge=1, le=50),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Roles actually present on CareerOS, so a candidate can pick one.

    Offered rather than chosen: section 4 permits a target role only
    from explicit selection or the candidate's own saved data, so this
    endpoint presents options and never assigns one.
    """
    return {
        "scope": "careeros_platform",
        "roles": roles_mod.observed_roles(db, corpus_mod.CorpusFilter(days=days), limit=limit),
        "note": "Job titles as listed on CareerOS. Pick one, or set a target role in your career preferences.",
    }


class AISummaryIn(BaseModel):
    role: str | None = Field(default=None, max_length=MAX_ROLE_LENGTH)
    force: bool = False


@router.post("/ai-summary")
def ai_summary(
    payload: AISummaryIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """A grounded natural-language summary of the candidate's own analytics.

    The deterministic analysis is computed first and returned in the
    same response under ``analysis``. The model receives only that
    analysis, already reduced to skill names and counts, and its
    output is never substituted for a figure — so a reader can always
    check the narrative against the numbers it was given.

    Rate-limited because it is the one endpoint in this router that
    can reach an external provider.
    """
    enforce_rate_limit(request, bucket="ai")
    analysis = candidate_intel.skill_gaps(db, user.id, explicit_role=payload.role)
    if analysis.get("status") != "ok":
        # Nothing solid to ground a summary in — say so rather than
        # asking a model to talk around missing data.
        return {
            "analysis": analysis,
            "ai": intelligence_ai.unavailable(
                "there is not yet enough CareerOS data for your target role to summarize"
            ),
            "cached": False,
        }
    content, cached = intelligence_ai.career_summary(
        db, user_id=user.id, analysis=analysis, force=payload.force
    )
    return {"analysis": analysis, "ai": content, "cached": cached}
