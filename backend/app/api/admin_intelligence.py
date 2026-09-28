"""V25.3 — admin platform intelligence and data quality (sections 12, 13).

Mounted under the existing ``/api/v1/admin`` prefix alongside the V9,
V17.3 and V25.2 admin routers. Paths were checked against all three
before being added; none collides.

AUTHORIZATION
-------------
Every route carries an explicit V25.2
``Depends(require_platform_permission(...))``. Platform intelligence
requires ``PLATFORM_ANALYTICS``; data quality requires
``SYSTEM_CONFIGURATION``, because it reports operational defects in
the deployment rather than product metrics. Recording a triage
decision is additionally audited to ``platform_audit_logs``.

An organization OWNER or ADMIN receives 403 here exactly as on every
other admin route — organization authority is not platform authority
(V25.2), and V25.3 adds no exception to that.

NOTHING HERE MODIFIES INSPECTED DATA
------------------------------------
The data-quality routes are read-only over jobs, candidates and
applications. The single write is an administrator's triage note,
which lands in its own table in the same transaction as its audit
record. There is no repair, merge, bulk-fix or delete endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.platform_admin import PlatformActor, PlatformPermission, require_platform_permission
from app.core.platform_audit import record_platform_action
from app.db.session import get_db
from app.intelligence import ai as intelligence_ai
from app.intelligence import corpus as corpus_mod
from app.intelligence import market as market_intel
from app.intelligence import platform_intel
from app.intelligence.quality import rules as quality_rules
from app.intelligence.quality import runner as quality_runner

from app.core.rate_limit import enforce_rate_limit

router = APIRouter()


# ===========================================================================
# 12. Platform intelligence
# ===========================================================================


@router.get("/intelligence")
def intelligence(
    days: int = Query(90, ge=1, le=corpus_mod.MAX_RANGE_DAYS),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.PLATFORM_ANALYTICS)),
):
    """Platform intelligence: V25.2's counts plus V25.3's dimensions."""
    return platform_intel.overview(db, days=days)


@router.get("/intelligence/skills")
def intelligence_skills(
    days: int = Query(90, ge=1, le=corpus_mod.MAX_RANGE_DAYS),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.PLATFORM_ANALYTICS)),
):
    return market_intel.skill_demand(db, corpus_mod.CorpusFilter(days=days), limit=limit)


@router.get("/intelligence/trends")
def intelligence_trends(
    days: int = Query(30, ge=1, le=corpus_mod.MAX_RANGE_DAYS),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.PLATFORM_ANALYTICS)),
):
    spec = corpus_mod.CorpusFilter(days=days)
    return {"skills": market_intel.skill_trends(db, spec), "volume": market_intel.volume_trends(db, spec)}


class MarketAIIn(BaseModel):
    days: int = Field(default=90, ge=1, le=corpus_mod.MAX_RANGE_DAYS)
    force: bool = False


@router.post("/intelligence/ai-summary")
def intelligence_ai_summary(
    payload: MarketAIIn,
    request: Request,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.PLATFORM_ANALYTICS)),
):
    """Grounded narrative over platform market activity.

    ``actor.user_id`` is None when the caller authenticated with the
    shared admin key rather than as a user. That is passed through as
    None, not coerced to 0 — ``AIUsageLog.user_id`` has a foreign key
    to ``users.id``, and there is no user with id 0. ``generate()``
    and the cache layer both accept a None user_id (an anonymous/
    system-attributed call), which is what the admin-key case
    genuinely is.
    """
    enforce_rate_limit(request, bucket="ai")
    analysis = market_intel.overview(db, corpus_mod.CorpusFilter(days=payload.days))
    content, cached = intelligence_ai.market_summary(
        db, user_id=actor.user_id, payload=analysis, force=payload.force
    )
    return {"analysis": analysis, "ai": content, "cached": cached}


# ===========================================================================
# 13. Data quality
# ===========================================================================


@router.get("/data-quality")
def data_quality(
    entity_type: str | None = Query(default=None, pattern="^(job|candidate|application|skill)$"),
    severity: str | None = Query(default=None, pattern="^(critical|high|medium|low)$"),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.SYSTEM_CONFIGURATION)),
):
    """Every data-quality rule with its current count and severity.

    Rules finding nothing are still listed with a count of zero — a
    clean rule vanishing from the report would make "we stopped
    checking" indistinguishable from "nothing is wrong".
    """
    return quality_runner.summary(db, entity_type=entity_type, severity=severity)


@router.get("/data-quality/rules")
def data_quality_rules(
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.SYSTEM_CONFIGURATION)),
):
    """The rule catalog itself, without running any of it."""
    return {
        "rules": [rule.as_dict() for rule in quality_rules.RULES],
        "severities": list(quality_rules.SEVERITIES),
        "triage_states": list(quality_runner.TRIAGE_STATES),
    }


@router.get("/data-quality/skill-mappings")
def data_quality_skill_mappings(
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.SYSTEM_CONFIGURATION)),
):
    """Skill names on jobs that resolve to no catalog entry."""
    return quality_runner.missing_skill_mappings(db, limit=limit)


@router.get("/data-quality/issues/{rule_id}")
def data_quality_issues(
    rule_id: str,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.SYSTEM_CONFIGURATION)),
):
    """One bounded page of the rows a single rule flags.

    Returns identifying labels only — a job id and title, or an
    account id and email. No rule returns resume text, application
    content, or a private note.
    """
    result = quality_runner.issues(db, rule_id, limit=limit, offset=offset)
    if not result:
        raise HTTPException(404, "Unknown data quality rule")
    return result


class TriageIn(BaseModel):
    state: str
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("state")
    @classmethod
    def _valid_state(cls, value: str) -> str:
        if value not in quality_runner.TRIAGE_STATES:
            raise ValueError(f"state must be one of: {', '.join(quality_runner.TRIAGE_STATES)}")
        return value


@router.put("/data-quality/issues/{rule_id}/{entity_id}/triage")
def set_triage(
    rule_id: str,
    entity_id: int,
    payload: TriageIn,
    db: Session = Depends(get_db),
    actor: PlatformActor = Depends(require_platform_permission(PlatformPermission.SYSTEM_CONFIGURATION)),
):
    """Record an administrator's decision about one detected issue.

    This is the entire "remediation" surface, and it deliberately does
    not touch the flagged record: marking an issue ``resolved`` records
    that a human dealt with it, it does not edit the job or the
    account. Section 13 forbids modifying production data without an
    explicit safe workflow, and V25.3's position is that automatic
    modification is never the safe workflow — the fix belongs in the
    moderation, job-edit or skill-catalog screens that already own
    those records and already audit their own changes.

    The triage row and its audit record commit together.
    """
    if rule_id not in quality_rules.RULES_BY_ID:
        raise HTTPException(404, "Unknown data quality rule")

    row = quality_runner.set_triage_state(
        db,
        rule_id=rule_id,
        entity_id=entity_id,
        state=payload.state,
        note=payload.note,
        actor_user_id=actor.user_id,
    )
    record_platform_action(
        db,
        actor,
        action="DATA_QUALITY_TRIAGED",
        target_type=quality_runner.entity_type_of(rule_id) or "data_quality",
        target_id=entity_id,
        note=payload.note,
        metadata={"rule_id": rule_id, "state": payload.state},
    )
    db.commit()
    return {
        "rule_id": row.rule_id,
        "entity_id": row.entity_id,
        "state": row.state,
        "note": row.note,
        "updated_at": row.updated_at,
    }
