"""COLD START — new users with limited data, AND new jobs with no
interaction history yet (NEW JOB COLD START).

For a candidate with no resume, no career goal, and no profile skills
(``CandidateFeatures.is_cold_start``), Stage 1 retrieval already falls
back to a broad, recency-sorted pool (see
app.recommendations.retrieval — a blank query sorts by "newest" rather
than a relevance score that would have nothing real to score against).
This module adds the other honest cold-start signal the spec asks
for — "Popular verified opportunities" — without fabricating anything:
verified jobs ranked by real engagement counts (saves + applications)
already recorded in ``SavedJob``/``Application``, never a guessed
popularity number.

V21.4 fix — NEW JOB COLD START: a pure engagement-ranked list
structurally buries every job with zero saves/applications behind any
job with even one, which would bury every newly-indexed job
indefinitely regardless of how good a fit it is ("Newly indexed jobs
must have an opportunity to appear. Do not bury new jobs forever
because they have no interaction history."). ``popular_verified_jobs``
now reserves a fixed fraction of its output for the most-recently-
posted verified jobs *regardless of engagement*, blended with the
top-engagement jobs, deduplicated. This only affects the cold-start
supplemental pool — core ranking (app.recommendations.matching's
`recency` component) already boosts brand-new jobs for every
candidate, cold-start or not, since it scores purely off
``Job.created_at``/``start_date``, never off engagement counts.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.domain import Application, Job, SavedJob

POPULAR_POOL_SIZE = 30
# NEW JOB COLD START: fraction of the pool reserved for freshest
# verified jobs regardless of engagement (0 = old engagement-only
# behavior, 1 = pure recency). Configurable-in-code constant,
# documented here rather than buried inline.
FRESHNESS_RESERVED_FRACTION = 0.3


def _top_engagement_jobs(db: Session, *, exclude_job_ids: set[int], limit: int) -> list[Job]:
    if limit <= 0:
        return []
    save_counts = (
        select(SavedJob.job_id, func.count().label("saves"))
        .group_by(SavedJob.job_id)
        .subquery()
    )
    apply_counts = (
        select(Application.job_id, func.count().label("applies"))
        .where(Application.job_id.isnot(None))
        .group_by(Application.job_id)
        .subquery()
    )
    engagement = (
        func.coalesce(save_counts.c.saves, 0) + func.coalesce(apply_counts.c.applies, 0)
    ).label("engagement")

    stmt = (
        select(Job)
        .outerjoin(save_counts, save_counts.c.job_id == Job.id)
        .outerjoin(apply_counts, apply_counts.c.job_id == Job.id)
        .where(Job.status == "published", Job.verified.is_(True))
        .order_by(engagement.desc(), Job.created_at.desc())
        .limit(limit + len(exclude_job_ids))
    )
    rows = db.scalars(stmt).all()
    return [job for job in rows if job.id not in exclude_job_ids][:limit]


def _freshest_verified_jobs(db: Session, *, exclude_job_ids: set[int], limit: int) -> list[Job]:
    if limit <= 0:
        return []
    stmt = (
        select(Job)
        .where(Job.status == "published", Job.verified.is_(True))
        .order_by(Job.created_at.desc())
        .limit(limit + len(exclude_job_ids))
    )
    rows = db.scalars(stmt).all()
    return [job for job in rows if job.id not in exclude_job_ids][:limit]


def popular_verified_jobs(db: Session, *, exclude_job_ids: set[int], limit: int = POPULAR_POOL_SIZE) -> list[Job]:
    freshness_slots = round(limit * FRESHNESS_RESERVED_FRACTION)
    engagement_slots = limit - freshness_slots

    top_engagement = _top_engagement_jobs(db, exclude_job_ids=exclude_job_ids, limit=engagement_slots)
    already_selected = exclude_job_ids | {job.id for job in top_engagement}
    freshest = _freshest_verified_jobs(db, exclude_job_ids=already_selected, limit=freshness_slots)

    # If either bucket came up short (small pool overall), let the
    # other backfill so the caller still gets up to `limit` results.
    combined = top_engagement + freshest
    if len(combined) < limit:
        already_selected = exclude_job_ids | {job.id for job in combined}
        backfill = _top_engagement_jobs(db, exclude_job_ids=already_selected, limit=limit - len(combined))
        combined.extend(backfill)
    return combined[:limit]
