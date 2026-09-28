"""V25.3 — organization hiring intelligence (sections 10 and 11).

REUSE, NOT REIMPLEMENTATION
---------------------------
Section 10 is explicit: reuse V24.4, do not create duplicate analytics
calculations. Every hiring metric this module reports — funnel,
conversion, time-to-review, time-in-stage, time-to-interview, offer
conversion, stale candidates, per-job performance — is produced by
calling ``app.recruiter_analytics.service`` with the organization's
member ids. Not one of those formulas is re-implemented here.

That works because V24.4's service was already written against an
``owner_ids`` list rather than a single recruiter, and because a
CareerOS organization owns jobs through its members
(``Job.owner_user_id ∈ member_ids``) — the same ownership
relationship ``app.core.team_access`` and V25.2 already use. So an
organization's analytics are literally its members' analytics,
aggregated by the existing engine.

What V25.3 genuinely adds is the two things V24.4 had no notion of:
organization-wide **skill demand** (section 11) and a deterministic
**difficult-to-fill** definition.

TENANT ISOLATION
----------------
Every function takes ``organization_id`` and derives member ids from
the database. No function accepts a caller-supplied owner id list.
The API layer authorizes membership through the V25.1
``require_organization_membership`` dependency before any of this
runs, and a suspended organization fails that check (V25.2). There is
no code path by which one organization's figures can be computed from
another organization's rows.

DIFFICULT TO FILL (section 11)
------------------------------
Explicitly deterministic, with no AI judgement. A role is flagged
when a published job meets BOTH:

  * it has been open at least ``MIN_OPEN_DAYS`` days, and
  * either it has received fewer than ``LOW_APPLICATION_COUNT``
    applications, or a high share of its applicants stalled before
    reaching review.

Each flagged row returns the exact numbers that triggered it, so the
label is auditable rather than asserted.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.organizations import organization_member_user_ids
from app.intelligence import corpus as corpus_mod
from app.intelligence import roles as roles_mod
from app.intelligence import skills as skills_mod
from app.intelligence import thresholds
from app.models.domain import Applicant, Job
from app.recruiter_analytics import service as v24_service

# Difficult-to-fill parameters. Named constants rather than inline
# numbers so the definition is readable and reviewable in one place,
# and reported alongside every result.
MIN_OPEN_DAYS = 30
LOW_APPLICATION_COUNT = 5
STALLED_STAGE_SHARE = 0.7
EARLY_STAGES = ("new",)


def _member_ids(db: Session, organization_id: int) -> list[int]:
    return organization_member_user_ids(db, organization_id)


def _org_spec(
    member_ids: list[int], *, days: int | None = None, statuses: tuple[str, ...] | None = corpus_mod.PUBLIC_STATUSES
) -> corpus_mod.CorpusFilter:
    return corpus_mod.CorpusFilter(days=days, owner_user_ids=member_ids, statuses=statuses)


def hiring_overview(db: Session, organization_id: int, *, days: int = 90) -> dict:
    """Organization hiring metrics — entirely V24.4's calculations.

    ``overview``, ``funnel``, ``time_and_bottleneck_analytics`` and
    ``applications_over_time`` are called as-is. This function adds
    scoping and labelling, nothing arithmetic.
    """
    member_ids = _member_ids(db, organization_id)
    if not member_ids:
        return {
            "organization_id": organization_id,
            "status": "no_members",
            "message": "This organization has no active members, so it owns no jobs or applications.",
        }

    days = corpus_mod.clamp_days(days)
    return {
        "organization_id": organization_id,
        "scope": "organization",
        "scope_note": (
            "These figures cover only jobs owned by this organization's members and the "
            "applications made to them."
        ),
        "member_count": len(member_ids),
        "generated_at": datetime.utcnow(),
        "computed_by": "app.recruiter_analytics.service (V24.4)",
        # --- V24.4, unmodified ---
        "overview": v24_service.overview(db, member_ids),
        "funnel": v24_service.funnel(db, member_ids),
        **v24_service.time_and_bottleneck_analytics(db, member_ids),
        "applications_over_time": v24_service.applications_over_time(db, member_ids, days=days),
        "stale_candidates_count": len(v24_service.stale_candidates_all(db, member_ids)),
    }


def skill_demand(db: Session, organization_id: int, *, days: int | None = None, limit: int = 25) -> dict:
    """What this organization asks for across its own listings."""
    member_ids = _member_ids(db, organization_id)
    spec = _org_spec(member_ids, days=days)
    loaded = corpus_mod.load_jobs(db, spec)
    blocked = skills_mod.guard_corpus(db, loaded.total)
    if blocked:
        return {"organization_id": organization_id, "jobs": loaded.total, **blocked}

    return {
        "organization_id": organization_id,
        "scope": "organization",
        "jobs": loaded.total,
        "filters": spec.describe(),
        "role_distribution": roles_mod.observed_roles(db, spec, limit=limit),
        **skills_mod.skill_summary(db, loaded.jobs, limit=limit),
    }


def candidate_pool_skill_gaps(db: Session, organization_id: int, *, limit: int = 20) -> dict:
    """Where this organization's own applicant pool falls short of
    what its own listings ask for.

    Scoped to people who **applied to this organization's jobs** —
    never the platform's candidate population, which would be other
    organizations' applicant data. Each gap row is a count of
    applicants, and rows below the privacy group floor are suppressed
    so a single applicant's skill set cannot be inferred from a
    breakdown.

    No candidate is named, and no candidate-level row is ever
    returned.
    """
    member_ids = _member_ids(db, organization_id)
    if not member_ids:
        return {"organization_id": organization_id, "status": "no_members"}

    limits = thresholds.load(db)
    spec = _org_spec(member_ids)
    loaded = corpus_mod.load_jobs(db, spec)
    blocked = skills_mod.guard_corpus(db, loaded.total)
    if blocked:
        return {"organization_id": organization_id, "jobs": loaded.total, **blocked}

    skill_corpus = skills_mod.build(db, loaded.jobs)
    required = skills_mod.reference_skills_from_corpus(skill_corpus, top_n=20, min_job_count=2)
    if not required:
        return {
            "organization_id": organization_id,
            "jobs": loaded.total,
            **thresholds.insufficient(0, 1, subject="jobs listing skills"),
        }

    applicant_ids = list(
        db.scalars(
            select(Applicant.user_id)
            .join(Job, Job.id == Applicant.job_id)
            .where(Job.owner_user_id.in_(member_ids))
            .distinct()
        ).all()
    )
    if len(applicant_ids) < limits.min_group:
        return {
            "organization_id": organization_id,
            "applicant_pool_size": len(applicant_ids),
            **thresholds.insufficient(
                len(applicant_ids), limits.min_group, subject="applicants in your pool"
            ),
            "privacy_note": (
                "Applicant-pool skill breakdowns are withheld below this size so an individual "
                "applicant's skills cannot be identified from an aggregate."
            ),
        }

    have: Counter = Counter()
    for user_id in applicant_ids:
        candidate = set(skills_mod.candidate_skills(db, user_id).canonical)
        for skill in required:
            if skill in candidate:
                have[skill] += 1

    pool = len(applicant_ids)
    rows = [
        {
            "skill": skill,
            "display_name": skill_corpus.display_names.get(skill, skill),
            "applicants_with_skill": have.get(skill, 0),
            "applicants_without_skill": pool - have.get(skill, 0),
            "coverage_pct": round(have.get(skill, 0) / pool * 100, 1),
        }
        for skill in required
    ]
    rows.sort(key=lambda r: r["coverage_pct"])

    return {
        "organization_id": organization_id,
        "scope": "organization",
        "applicant_pool_size": pool,
        "required_skills_considered": len(required),
        "definition": (
            f"Skills listed on at least 2 of this organization's {skill_corpus.jobs_with_skill_data} "
            f"skill-bearing jobs, matched against the normalized skills of the {pool} distinct "
            "candidates who applied to those jobs."
        ),
        "gaps": rows,
        "privacy_note": (
            "Aggregate counts only. No candidate is identified, and no candidate-level row is returned."
        ),
    }


def difficult_to_fill(db: Session, organization_id: int, *, limit: int = 20) -> dict:
    """Roles that are hard to fill, by an explicit deterministic rule."""
    member_ids = _member_ids(db, organization_id)
    if not member_ids:
        return {"organization_id": organization_id, "status": "no_members", "jobs": []}

    now = datetime.utcnow()
    jobs = list(
        db.scalars(
            select(Job)
            .where(
                Job.owner_user_id.in_(member_ids),
                Job.status == "published",
                Job.published_at.isnot(None),
            )
            .order_by(Job.published_at)
            .limit(500)
        ).all()
    )
    job_ids = [job.id for job in jobs]

    # One grouped query for application counts and one for early-stage
    # counts — not a query per job (spec section 25).
    totals = dict(
        db.execute(
            select(Applicant.job_id, func.count()).where(Applicant.job_id.in_(job_ids)).group_by(Applicant.job_id)
        ).all()
    ) if job_ids else {}
    early = dict(
        db.execute(
            select(Applicant.job_id, func.count())
            .where(Applicant.job_id.in_(job_ids), Applicant.pipeline_stage.in_(list(EARLY_STAGES)))
            .group_by(Applicant.job_id)
        ).all()
    ) if job_ids else {}

    flagged = []
    for job in jobs:
        open_days = (now - job.published_at).days
        if open_days < MIN_OPEN_DAYS:
            continue
        applications = int(totals.get(job.id, 0))
        stalled = int(early.get(job.id, 0))
        stalled_share = round(stalled / applications, 2) if applications else 0.0

        reasons = []
        if applications < LOW_APPLICATION_COUNT:
            reasons.append(
                f"open {open_days} days with {applications} application(s), below the "
                f"{LOW_APPLICATION_COUNT}-application threshold"
            )
        if applications and stalled_share >= STALLED_STAGE_SHARE:
            reasons.append(
                f"{stalled} of {applications} applicants ({int(stalled_share * 100)}%) are still at the "
                f"earliest pipeline stage after {open_days} days"
            )
        if not reasons:
            continue

        flagged.append(
            {
                "job_id": job.id,
                "title": job.title,
                "open_days": open_days,
                "applications": applications,
                "applicants_at_earliest_stage": stalled,
                "earliest_stage_share": stalled_share,
                "reasons": reasons,
            }
        )

    flagged.sort(key=lambda row: (-row["open_days"], row["applications"]))
    return {
        "organization_id": organization_id,
        "scope": "organization",
        "definition": (
            f"A published job is flagged when it has been open at least {MIN_OPEN_DAYS} days AND either "
            f"has fewer than {LOW_APPLICATION_COUNT} applications, or has at least "
            f"{int(STALLED_STAGE_SHARE * 100)}% of its applicants still at the earliest pipeline stage. "
            "This is a fixed rule over pipeline data — no AI judgement is involved."
        ),
        "jobs_evaluated": len(jobs),
        "jobs": flagged[:limit],
    }


def job_performance(db: Session, organization_id: int, *, limit: int = 20) -> dict:
    """Per-job performance, computed by V24.4's ``job_performance``."""
    member_ids = _member_ids(db, organization_id)
    if not member_ids:
        return {"organization_id": organization_id, "status": "no_members", "jobs": []}
    jobs = list(
        db.scalars(
            select(Job).where(Job.owner_user_id.in_(member_ids)).order_by(Job.id.desc()).limit(limit)
        ).all()
    )
    return {
        "organization_id": organization_id,
        "computed_by": "app.recruiter_analytics.service.job_performance (V24.4)",
        "jobs": [v24_service.job_performance(db, job) for job in jobs],
    }


def full_intelligence(db: Session, organization_id: int, *, days: int = 90) -> dict:
    """Everything the organization intelligence screen needs."""
    return {
        "hiring": hiring_overview(db, organization_id, days=days),
        "skill_demand": skill_demand(db, organization_id),
        "candidate_pool_gaps": candidate_pool_skill_gaps(db, organization_id),
        "difficult_to_fill": difficult_to_fill(db, organization_id),
        "thresholds": thresholds.load(db).as_dict(),
    }
