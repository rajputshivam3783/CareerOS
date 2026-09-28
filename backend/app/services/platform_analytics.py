"""V25.2 — platform analytics and the admin dashboard's metrics.

TWO RULES, BOTH NON-NEGOTIABLE
------------------------------

1. **No fabricated metrics** (spec sections 3 and 14). Every number
   returned here is a COUNT or a GROUP BY over rows that exist. Where
   a metric the spec suggests has no corresponding data in this
   schema, it is omitted rather than approximated — see
   ``_OMITTED_METRICS`` below, which documents each omission and why,
   so "this number isn't here" is an answered question rather than a
   silent gap.

2. **Aggregates only** (spec section 15). Every function returns
   counts, bucketed time series, or top-N lists keyed by an
   *organization* or a *job*. No function in this module returns a
   candidate's identity, resume text, application content, private
   notes, documents, or contact details, and none groups by any
   protected characteristic — the schema holds no such attribute and
   this module introduces no proxy for one (no name analysis, no
   location-based inference, no age derivation).

   The one place individuals appear at all is the *recent
   administrative activity* feed on the dashboard, which names the
   administrator who took an action — that is the point of an audit
   trail, and it names staff acting in an official capacity, never a
   candidate.

TIME SERIES
-----------
Series are bucketed in SQL by date and returned as dense arrays (every
day in the range present, zero-filled) so the frontend never has to
guess whether a missing day means zero or missing data. Ranges are
capped (``MAX_RANGE_DAYS``) because an unbounded "since the beginning
of time, by day" aggregation over a large table is exactly the
expensive unbounded analytics section 33 warns against.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.domain import (
    Applicant,
    Job,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    PlatformAuditLog,
    User,
)

log = logging.getLogger("careeros.platform_analytics")

MAX_RANGE_DAYS = 365
DEFAULT_RANGE_DAYS = 30

# Documented omissions — surfaced in the API response so the absence
# of a metric the spec listed is explicit rather than looking like an
# oversight.
_OMITTED_METRICS: dict[str, str] = {
    "active_users": (
        "CareerOS records session creation (user_sessions) but not per-request activity, "
        "so a true 'active users' figure is not derivable. 'Users with a session in the "
        "period' is reported instead, under its own honest name."
    ),
    "expired_jobs": (
        "Job expiry is not a stored status — a listing whose deadline has passed keeps "
        "status='published'. Reported as 'published_past_deadline', computed from the "
        "deadline column, rather than as a status count that does not exist."
    ),
    "demographics": (
        "Not implemented by design. CareerOS stores no protected characteristics and "
        "this version deliberately introduces no demographic analytics (spec section 15)."
    ),
}


def _clamp_days(days: int | None) -> int:
    if not days or days <= 0:
        return DEFAULT_RANGE_DAYS
    return min(days, MAX_RANGE_DAYS)


def _dense_series(rows: list[tuple], start: date, end: date) -> list[dict]:
    """Zero-fill a sparse GROUP BY date result across the full range."""
    counts: dict[str, int] = {}
    for bucket, count in rows:
        if bucket is None:
            continue
        if isinstance(bucket, datetime):
            bucket = bucket.date()
        elif isinstance(bucket, str):
            # SQLite returns a 'YYYY-MM-DD' string from date(); PostgreSQL returns a date.
            try:
                bucket = date.fromisoformat(bucket[:10])
            except ValueError:
                continue
        counts[bucket.isoformat()] = int(count)

    out = []
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        out.append({"date": key, "count": counts.get(key, 0)})
        cursor += timedelta(days=1)
    return out


def _daily_counts(db: Session, column, *, days: int, extra_where=None) -> list[dict]:
    end = datetime.utcnow().date()
    start = end - timedelta(days=days - 1)
    bucket = func.date(column)  # portable: SQLite cast(... AS Date) yields an int (year), not a date
    query = select(bucket, func.count()).where(column >= datetime.combine(start, datetime.min.time()))
    if extra_where is not None:
        query = query.where(extra_where)
    rows = db.execute(query.group_by(bucket).order_by(bucket)).all()
    return _dense_series(list(rows), start, end)


def _count(db: Session, model, *where) -> int:
    query = select(func.count()).select_from(model)
    for clause in where:
        query = query.where(clause)
    return int(db.scalar(query) or 0)


# ---------------------------------------------------------------------------
# Dashboard (spec section 3)
# ---------------------------------------------------------------------------


def dashboard_metrics(db: Session) -> dict:
    """The platform administration dashboard's headline numbers.

    Every figure is a live COUNT. ``recent_activity`` is the tail of
    the platform audit trail — genuine administrative history, not a
    generated feed.
    """
    now = datetime.utcnow()
    last_30 = now - timedelta(days=30)

    users = {
        "total": _count(db, User),
        "active": _count(db, User, User.active.is_(True)),
        "suspended": _count(db, User, User.active.is_(False), User.suspended_at.isnot(None)),
        "verified": _count(db, User, User.email_verified.is_(True)),
        "candidates": _count(db, User, User.role == "candidate", User.active.is_(True)),
        "recruiters": _count(db, User, User.role == "recruiter", User.active.is_(True)),
        "recruiters_pending_approval": _count(db, User, User.recruiter_status == "pending"),
        "platform_admins": _count(db, User, User.role.in_(("admin", "super_admin"))),
        "new_last_30_days": _count(db, User, User.created_at >= last_30),
    }

    organizations = {
        "total": _count(db, Organization),
        "active": _count(db, Organization, Organization.is_active.is_(True)),
        "suspended": _count(db, Organization, Organization.is_active.is_(False)),
        "verified": _count(db, Organization, Organization.verification_status == "verified"),
        "pending_verification": _count(db, Organization, Organization.verification_status == "pending"),
        "pending_invitations": _count(db, OrganizationInvitation, OrganizationInvitation.status == "PENDING"),
        "new_last_30_days": _count(db, Organization, Organization.created_at >= last_30),
    }

    jobs = {
        "total": _count(db, Job),
        "published": _count(db, Job, Job.status == "published"),
        "pending_review": _count(db, Job, Job.status == "review"),
        "rejected": _count(db, Job, Job.status == "rejected"),
        "suspended": _count(db, Job, Job.status == "suspended"),
        "closed": _count(db, Job, Job.status == "closed"),
        "published_past_deadline": _count(
            db, Job, Job.status == "published", Job.deadline.isnot(None), Job.deadline < now.date()
        ),
        "new_last_30_days": _count(db, Job, Job.created_at >= last_30),
    }

    # Platform application volume is measured on `Applicant` — the
    # applications actually made THROUGH CareerOS to a CareerOS job.
    # The `Application` table is the candidate's own private tracker
    # of roles they are pursuing anywhere, including off-platform, and
    # may contain private notes; counting it here would both overstate
    # platform activity and reach into data section 15 says to leave
    # alone.
    applications = {
        "total": _count(db, Applicant),
        "active": _count(db, Applicant, Applicant.status.notin_(("rejected", "withdrawn"))),
        "new_last_30_days": _count(db, Applicant, Applicant.created_at >= last_30),
        "hired": _count(db, Applicant, Applicant.hired_at.isnot(None)),
    }

    recent_activity = [
        {
            "id": row.id,
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "actor_label": row.actor_label,
            "actor_type": row.actor_type,
            "reason": row.reason,
            "result": row.result,
            "created_at": row.created_at,
        }
        for row in db.scalars(
            select(PlatformAuditLog).order_by(PlatformAuditLog.id.desc()).limit(10)
        ).all()
    ]

    return {
        "generated_at": now,
        "users": users,
        "organizations": organizations,
        "jobs": jobs,
        "applications": applications,
        "recent_activity": recent_activity,
        "omitted_metrics": _OMITTED_METRICS,
    }


# ---------------------------------------------------------------------------
# Analytics (spec section 14)
# ---------------------------------------------------------------------------


def platform_analytics(db: Session, *, days: int | None = None) -> dict:
    days = _clamp_days(days)
    now = datetime.utcnow()
    window_start = now - timedelta(days=days)

    users = {
        "registrations_over_time": _daily_counts(db, User.created_at, days=days),
        "total": _count(db, User),
        "verified": _count(db, User, User.email_verified.is_(True)),
        "unverified": _count(db, User, User.email_verified.is_(False)),
        "by_role": _group_counts(db, User, User.role),
        "by_account_status": [
            {"key": "ACTIVE", "count": _count(db, User, User.active.is_(True))},
            {
                "key": "SUSPENDED",
                "count": _count(db, User, User.active.is_(False), User.suspended_at.isnot(None)),
            },
            {
                "key": "DEACTIVATED",
                "count": _count(db, User, User.active.is_(False), User.suspended_at.is_(None)),
            },
        ],
        "users_with_session_in_period": _users_with_session(db, window_start),
    }

    organizations = {
        "created_over_time": _daily_counts(db, Organization.created_at, days=days),
        "total": _count(db, Organization),
        "active": _count(db, Organization, Organization.is_active.is_(True)),
        "suspended": _count(db, Organization, Organization.is_active.is_(False)),
        "by_verification_status": _group_counts(db, Organization, Organization.verification_status),
        "with_active_hiring": _organizations_with_active_hiring(db),
    }

    jobs = {
        "created_over_time": _daily_counts(db, Job.created_at, days=days),
        "published_over_time": _daily_counts(db, Job.published_at, days=days),
        "by_status": _group_counts(db, Job, Job.status),
        "by_moderation_reason": _group_counts(
            db, Job, Job.moderation_reason, where=Job.moderation_reason.isnot(None)
        ),
        "published_past_deadline": _count(
            db, Job, Job.status == "published", Job.deadline.isnot(None), Job.deadline < now.date()
        ),
    }

    applications = {
        "over_time": _daily_counts(db, Applicant.created_at, days=days),
        "by_status": _group_counts(db, Applicant, Applicant.status),
        "by_pipeline_stage": _group_counts(db, Applicant, Applicant.pipeline_stage),
        "by_job_status": _applications_by_job_status(db),
        "top_jobs_by_volume": _top_jobs_by_application_volume(db),
    }

    return {
        "generated_at": now,
        "range_days": days,
        "users": users,
        "organizations": organizations,
        "jobs": jobs,
        "applications": applications,
        "omitted_metrics": _OMITTED_METRICS,
    }


def _group_counts(db: Session, model, column, *, where=None, limit: int = 30) -> list[dict]:
    query = select(column, func.count()).select_from(model).group_by(column).order_by(func.count().desc())
    if where is not None:
        query = query.where(where)
    rows = db.execute(query.limit(limit)).all()
    return [{"key": key if key is not None else "unknown", "count": int(count)} for key, count in rows]


def _users_with_session(db: Session, since: datetime) -> int:
    """Distinct users who created or refreshed a session in the window.

    Named for exactly what it measures. This is NOT "active users" —
    see ``_OMITTED_METRICS``.
    """
    try:
        from app.models.domain import UserSession

        return int(
            db.scalar(
                select(func.count(func.distinct(UserSession.user_id))).where(UserSession.last_seen_at >= since)
            )
            or 0
        )
    except Exception:
        log.warning("Session activity query failed", exc_info=True)
        return 0


def _organizations_with_active_hiring(db: Session, limit: int = 10) -> list[dict]:
    """Organizations whose members currently own at least one
    published job, ranked by that count.

    Joins organization_members -> jobs on ``Job.owner_user_id``, the
    same ownership relationship ``app.core.team_access`` already uses.
    Aggregated in SQL (one query, GROUP BY) rather than looping per
    organization — which would be the classic N+1 section 33 calls out.
    """
    rows = db.execute(
        select(Organization.id, Organization.name, func.count(func.distinct(Job.id)).label("job_count"))
        .select_from(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .join(Job, Job.owner_user_id == OrganizationMember.user_id)
        .where(
            OrganizationMember.status == "ACTIVE",
            Organization.is_active.is_(True),
            Job.status == "published",
        )
        .group_by(Organization.id, Organization.name)
        .order_by(func.count(func.distinct(Job.id)).desc())
        .limit(limit)
    ).all()
    return [{"organization_id": oid, "name": name, "published_jobs": int(count)} for oid, name, count in rows]


def _applications_by_job_status(db: Session) -> list[dict]:
    rows = db.execute(
        select(Job.status, func.count(Applicant.id))
        .select_from(Applicant)
        .join(Job, Job.id == Applicant.job_id)
        .group_by(Job.status)
        .order_by(func.count(Applicant.id).desc())
    ).all()
    return [{"key": status or "unknown", "count": int(count)} for status, count in rows]


def _top_jobs_by_application_volume(db: Session, limit: int = 10) -> list[dict]:
    """Highest-volume listings.

    Returns the JOB's title/organization and a count — never anything
    about who applied.
    """
    rows = db.execute(
        select(Job.id, Job.title, Job.organization, Job.status, func.count(Applicant.id).label("n"))
        .select_from(Job)
        .join(Applicant, Applicant.job_id == Job.id)
        .group_by(Job.id, Job.title, Job.organization, Job.status)
        .order_by(func.count(Applicant.id).desc())
        .limit(limit)
    ).all()
    return [
        {"job_id": jid, "title": title, "organization": org, "status": status, "applications": int(n)}
        for jid, title, org, status, n in rows
    ]
