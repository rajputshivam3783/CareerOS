"""V25.3 — admin platform intelligence (spec section 12).

Extends V25.2's admin analytics rather than replacing it. V25.2's
``app.services.platform_analytics`` already answers "how many users,
organizations, jobs, applications, and how did those counts move" —
that function is called here, unmodified, and this module adds the
content dimensions it had no notion of: which categories, which
skills, which roles, which organizations, and what ingestion actually
produced.

PRIVACY
-------
Aggregates only, exactly as in V25.2. The organization-activity table
names organizations (they are not individuals, and a platform
administrator already has organization management rights in V25.2);
the candidate-activity block is counts, never a list of people. No
function here returns a candidate's identity, resume, application
content, or any profile field. As in V25.2, no breakdown is produced
by any protected characteristic, and none is inferred.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.intelligence import corpus as corpus_mod
from app.intelligence import market as market_mod
from app.intelligence import roles as roles_mod
from app.intelligence import skills as skills_mod
from app.intelligence import thresholds
from app.models.domain import (
    Applicant,
    IngestionRun,
    Job,
    Organization,
    OrganizationMember,
    SourceRegistry,
    User,
)
from app.services import platform_analytics as v25_2_analytics


def category_activity(db: Session, spec: corpus_mod.CorpusFilter) -> dict:
    """Jobs and applications by job category."""
    job_rows = corpus_mod.aggregate_counts(db, spec, Job.category, limit=25)
    application_rows = db.execute(
        select(Job.category, func.count(Applicant.id))
        .select_from(Applicant)
        .join(Job, Job.id == Applicant.job_id)
        .where(Job.category.isnot(None))
        .group_by(Job.category)
        .order_by(func.count(Applicant.id).desc())
        .limit(25)
    ).all()
    return {
        "jobs_by_category": job_rows,
        "applications_by_category": [
            {"key": category or "unspecified", "count": int(count)} for category, count in application_rows
        ],
    }


def organization_activity(db: Session, *, limit: int = 20) -> list[dict]:
    """Per-organization job and application volume, in one query.

    A single GROUP BY join across organizations, members, jobs and
    applicants rather than a query per organization — the same
    aggregate-in-SQL shape V25.2's leaderboards use (spec section 25).
    """
    rows = db.execute(
        select(
            Organization.id,
            Organization.name,
            Organization.is_active,
            func.count(func.distinct(Job.id)).label("jobs"),
            func.count(Applicant.id).label("applications"),
        )
        .select_from(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .join(Job, Job.owner_user_id == OrganizationMember.user_id)
        .outerjoin(Applicant, Applicant.job_id == Job.id)
        .where(OrganizationMember.status == "ACTIVE")
        .group_by(Organization.id, Organization.name, Organization.is_active)
        .order_by(func.count(func.distinct(Job.id)).desc())
        .limit(limit)
    ).all()
    return [
        {
            "organization_id": org_id,
            "name": name,
            "active": bool(is_active),
            "jobs": int(jobs),
            "applications": int(applications),
        }
        for org_id, name, is_active, jobs, applications in rows
    ]


def candidate_activity(db: Session) -> dict:
    """Candidate-side participation, as counts only."""
    from app.models.domain import Profile, Resume

    candidates = int(
        db.scalar(select(func.count()).select_from(User).where(User.role == "candidate", User.active.is_(True))) or 0
    )
    with_profile = int(db.scalar(select(func.count()).select_from(Profile)) or 0)
    with_resume = int(db.scalar(select(func.count()).select_from(Resume)) or 0)
    applied = int(db.scalar(select(func.count(func.distinct(Applicant.user_id)))) or 0)
    return {
        "active_candidates": candidates,
        "candidates_with_profile": with_profile,
        "candidates_with_resume": with_resume,
        "candidates_who_applied": applied,
        "note": "Counts only. No candidate is identified anywhere in this report.",
    }


def ingestion_activity(db: Session, *, days: int = 90) -> dict:
    """What automated ingestion actually produced.

    Sums ``IngestionRun`` columns, which are written only by real
    runs. No source's output is estimated, and a source that has
    never run reports zero rather than being omitted.
    """
    window_start = datetime.utcnow() - timedelta(days=corpus_mod.clamp_days(days))
    rows = db.execute(
        select(
            IngestionRun.source_name,
            func.count().label("runs"),
            func.coalesce(func.sum(IngestionRun.created), 0),
            func.coalesce(func.sum(IngestionRun.skipped), 0),
            func.coalesce(func.sum(IngestionRun.discovered), 0),
        )
        .where(IngestionRun.started_at >= window_start)
        .group_by(IngestionRun.source_name)
        .order_by(func.coalesce(func.sum(IngestionRun.created), 0).desc())
    ).all()
    registered = int(db.scalar(select(func.count()).select_from(SourceRegistry)) or 0)
    return {
        "window_days": days,
        "registered_sources": registered,
        "sources": [
            {
                "source_name": name,
                "runs": int(runs),
                "jobs_created": int(created),
                "records_skipped": int(skipped),
                "records_discovered": int(discovered),
            }
            for name, runs, created, skipped, discovered in rows
        ],
        "note": (
            "Figures are sums over recorded ingestion runs. Sources with no run in this window "
            "do not appear."
        ),
    }


def overview(db: Session, *, days: int = 90) -> dict:
    """The admin intelligence payload.

    ``platform_counts`` is V25.2's ``dashboard_metrics`` called
    unchanged — this module adds dimensions, it does not recount.
    """
    spec = corpus_mod.CorpusFilter(days=days)
    loaded = corpus_mod.load_jobs(db, spec)
    skill_block: dict
    blocked = skills_mod.guard_corpus(db, loaded.total)
    if blocked:
        skill_block = blocked
    else:
        skill_block = skills_mod.skill_summary(db, loaded.jobs, limit=25)

    return {
        "generated_at": datetime.utcnow(),
        "scope": market_mod.SCOPE,
        "scope_label": market_mod.SCOPE_LABEL,
        "scope_note": market_mod.SCOPE_NOTE,
        "filters": spec.describe(),
        "thresholds": thresholds.load(db).as_dict(),
        "platform_counts": v25_2_analytics.dashboard_metrics(db),
        "computed_by": "app.services.platform_analytics.dashboard_metrics (V25.2) plus V25.3 dimensions",
        "categories": category_activity(db, spec),
        "skills": skill_block,
        "roles": roles_mod.observed_roles(db, spec, limit=25),
        "organizations": organization_activity(db),
        "candidates": candidate_activity(db),
        "ingestion": ingestion_activity(db, days=days),
    }
