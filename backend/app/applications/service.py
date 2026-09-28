"""APPLICATION SERVICE LAYER — the one place that reads or writes an
``Application``/``ApplicationStatusHistory`` row. Every function here
takes a ``user_id`` explicitly and scopes every query to it — nothing
in this module ever trusts a caller-supplied user id from anywhere
else; ``app/api/applications.py`` always derives it from
``current_user`` (SECURITY: "Do not trust user_id supplied by
frontend. Always derive the current user from authentication.").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.notifications import events as notification_events

from app.applications.status import (
    DEFAULT_STATUS_FOR_EXTERNAL,
    DEFAULT_STATUS_FOR_MARK_APPLIED,
    DEFAULT_STATUS_FOR_TRACK,
    STATUS_VALUES,
    TerminalStatusReopenRequiredError,
    can_transition,
    normalize,
)
from app.models.domain import Application, ApplicationStatusHistory, Job


class ApplicationNotFoundError(Exception):
    pass


class DuplicateApplicationError(Exception):
    def __init__(self, existing: Application):
        self.existing = existing
        super().__init__(f"An application already exists (id={existing.id}, status={existing.status})")


@dataclass
class ApplicationFilters:
    status: str | None = None
    company: str | None = None
    source: str | None = None
    job_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    search: str | None = None  # V22.2 — matches company, job_title, OR location (see list_applications)


_SORTABLE_FIELDS = {
    "created_at": Application.created_at,
    "updated_at": Application.updated_at,
    "applied_on": Application.applied_on,
    "deadline": Application.deadline,
    "status_updated_at": Application.status_updated_at,
    "company": Application.company,
}


def _get_owned(db: Session, user_id: int, application_id: int) -> Application:
    record = db.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user_id)
    )
    if record is None:
        raise ApplicationNotFoundError(f"Application {application_id} not found")
    return record


def _find_duplicate(db: Session, user_id: int, *, job_id: int | None, company: str, job_title: str) -> Application | None:
    """PREVENT DUPLICATE APPLICATIONS "where appropriate": a second
    *active* (non-terminal) tracker for the exact same CareerOS job, or
    the exact same (company, job_title) pair for an external one, is
    almost always a double-submit rather than a genuine second attempt.
    A candidate who was REJECTED/WITHDRAWN and is now trying again
    (or genuinely reapplying) is explicitly allowed — terminal
    applications are never considered a duplicate blocker."""
    from app.applications.status import TERMINAL_STATUSES

    if job_id is not None:
        stmt = select(Application).where(
            Application.user_id == user_id,
            Application.job_id == job_id,
            Application.status.not_in(TERMINAL_STATUSES),
        )
    else:
        stmt = select(Application).where(
            Application.user_id == user_id,
            Application.job_id.is_(None),
            func.lower(Application.company) == company.strip().lower(),
            func.lower(Application.job_title) == job_title.strip().lower(),
            Application.status.not_in(TERMINAL_STATUSES),
        )
    return db.scalar(stmt.limit(1))


def create_application(
    db: Session,
    user_id: int,
    *,
    job_id: int | None,
    company: str,
    job_title: str,
    status: str | None = None,
    job_url: str | None = None,
    location: str | None = None,
    employment_type: str | None = None,
    source: str | None = None,
    salary: str | None = None,
    deadline: date | None = None,
    applied_on: date | None = None,
    next_deadline: date | None = None,
    recruiter_name: str | None = None,
    recruiter_email: str | None = None,
    external_reference: str | None = None,
    notes: str | None = None,
    allow_duplicate: bool = False,
) -> Application:
    if job_id is not None and db.get(Job, job_id) is None:
        raise ApplicationNotFoundError(f"Job {job_id} not found")

    canonical_status = normalize(status) if status else (DEFAULT_STATUS_FOR_EXTERNAL if job_id is None else DEFAULT_STATUS_FOR_TRACK)

    if not allow_duplicate:
        duplicate = _find_duplicate(db, user_id, job_id=job_id, company=company, job_title=job_title)
        if duplicate is not None:
            raise DuplicateApplicationError(duplicate)

    now = datetime.utcnow()
    record = Application(
        user_id=user_id,
        job_id=job_id,
        company=company,
        role=job_title,  # kept in sync — see Application's own docstring
        job_title=job_title,
        job_url=job_url,
        location=location,
        employment_type=employment_type,
        source=source,
        salary=salary,
        deadline=deadline,
        applied_on=applied_on,
        next_deadline=next_deadline,
        recruiter_name=recruiter_name,
        recruiter_email=recruiter_email,
        external_reference=external_reference,
        notes=notes,
        status=canonical_status,
        status_updated_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.flush()  # assign record.id before writing its first history row

    db.add(ApplicationStatusHistory(application_id=record.id, old_status=None, new_status=canonical_status, changed_at=now))
    db.commit()
    db.refresh(record)
    # V23.1 — fires after commit, so a notification failure can never
    # roll back or fail the application creation itself (see
    # app.notifications.events' own failure-isolation docstring).
    notification_events.application_created(db, record)
    return record


def create_from_job(
    db: Session,
    user_id: int,
    *,
    job_id: int,
    mark_applied: bool = False,
    notes: str | None = None,
) -> Application:
    """APPLY FROM CAREEROS JOB — "Track Application" (mark_applied=False)
    or "Mark as Applied" (mark_applied=True). Copies a snapshot of the
    job's own fields at *this moment* rather than relying on a live
    join, so a later edit to the Job (title change, closed posting,
    etc.) never rewrites this application's own history — see
    Application's docstring ("If the original job later changes,
    historical application information must remain meaningful")."""
    job = db.get(Job, job_id)
    if job is None:
        raise ApplicationNotFoundError(f"Job {job_id} not found")

    status = DEFAULT_STATUS_FOR_MARK_APPLIED if mark_applied else DEFAULT_STATUS_FOR_TRACK
    return create_application(
        db,
        user_id,
        job_id=job.id,
        company=job.organization,
        job_title=job.title,
        status=status,
        location=job.location,
        employment_type=job.employment_type,
        salary=job.salary,
        deadline=job.deadline,
        applied_on=date.today() if mark_applied else None,
        source="careeros",
        job_url=job.apply_url or job.official_url,
        notes=notes,
    )


def get_application(db: Session, user_id: int, application_id: int) -> Application:
    return _get_owned(db, user_id, application_id)


def list_applications(
    db: Session,
    user_id: int,
    *,
    filters: ApplicationFilters | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Application], int]:
    """Returns (page of applications, total matching count). Filtering,
    sorting, and pagination all happen in the database — this never
    loads a user's full application history into Python to slice it
    (DATABASE PERFORMANCE: efficient at scale)."""
    filters = filters or ApplicationFilters()
    stmt = select(Application).where(Application.user_id == user_id)
    count_stmt = select(func.count()).select_from(Application).where(Application.user_id == user_id)

    if filters.status:
        canonical = normalize(filters.status)
        stmt = stmt.where(Application.status == canonical)
        count_stmt = count_stmt.where(Application.status == canonical)
    if filters.company:
        pattern = f"%{filters.company.strip()}%"
        stmt = stmt.where(Application.company.ilike(pattern))
        count_stmt = count_stmt.where(Application.company.ilike(pattern))
    if filters.search:
        # SEARCH (V22.2): "company name, job title, location" — OR'd,
        # not AND'd, since a candidate typing into one search box
        # doesn't know or care which field the match will land in.
        pattern = f"%{filters.search.strip()}%"
        search_clause = (
            Application.company.ilike(pattern)
            | Application.job_title.ilike(pattern)
            | Application.location.ilike(pattern)
        )
        stmt = stmt.where(search_clause)
        count_stmt = count_stmt.where(search_clause)
    if filters.source:
        stmt = stmt.where(Application.source == filters.source)
        count_stmt = count_stmt.where(Application.source == filters.source)
    if filters.job_id is not None:
        stmt = stmt.where(Application.job_id == filters.job_id)
        count_stmt = count_stmt.where(Application.job_id == filters.job_id)
    if filters.date_from is not None:
        stmt = stmt.where(Application.created_at >= filters.date_from)
        count_stmt = count_stmt.where(Application.created_at >= filters.date_from)
    if filters.date_to is not None:
        stmt = stmt.where(Application.created_at <= filters.date_to)
        count_stmt = count_stmt.where(Application.created_at <= filters.date_to)

    sort_column = _SORTABLE_FIELDS.get(sort_by, Application.created_at)  # unrecognized sort_by silently
    # falls back to created_at rather than raising or building a raw/unsafe ORDER BY clause from user input
    order = sort_column.asc() if sort_dir == "asc" else sort_column.desc()
    stmt = stmt.order_by(order, Application.id.desc())  # id as a stable tiebreaker

    total = db.scalar(count_stmt) or 0
    items = db.scalars(stmt.limit(limit).offset(offset)).all()
    return items, total


def update_application(db: Session, user_id: int, application_id: int, *, reopen: bool = False, **fields) -> Application:
    """Partial update (PATCH semantics) — only fields explicitly passed
    are changed; a status change here does NOT go through
    change_status/history (use that function for an explicit status
    transition with an audit trail). If a caller passes ``status`` to
    this function anyway, it's routed through change_status so a
    history row is never silently skipped."""
    record = _get_owned(db, user_id, application_id)

    if "job_id" in fields and fields["job_id"] is not None and db.get(Job, fields["job_id"]) is None:
        raise ApplicationNotFoundError(f"Job {fields['job_id']} not found")

    status_value = fields.pop("status", None)
    for key, value in fields.items():
        if value is not None or key in {"notes", "job_url", "recruiter_name", "recruiter_email"}:
            # allow explicitly clearing a free-text field with null,
            # but never overwrite a real value with an *absent* field —
            # callers only pass keys they actually intend to change.
            setattr(record, key, value)
        if key == "job_title" and value is not None:
            record.role = value  # keep the legacy field in sync

    record.updated_at = datetime.utcnow()

    if status_value is not None:
        return change_status(db, user_id, application_id, status_value, reopen=reopen)

    db.commit()
    db.refresh(record)
    return record


def change_status(
    db: Session, user_id: int, application_id: int, new_status_raw: str, *, metadata: dict | None = None, reopen: bool = False
) -> Application:
    record = _get_owned(db, user_id, application_id)
    new_status = normalize(new_status_raw)
    old_status = record.status

    if not can_transition(old_status, new_status, reopen=reopen):
        raise TerminalStatusReopenRequiredError(old_status, new_status)

    now = datetime.utcnow()

    record.status = new_status
    record.status_updated_at = now
    record.updated_at = now
    if new_status == "APPLIED" and record.applied_on is None:
        record.applied_on = date.today()

    history = ApplicationStatusHistory(
        application_id=record.id,
        old_status=old_status,
        new_status=new_status,
        changed_at=now,
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    db.add(history)
    db.commit()
    db.refresh(record)
    # V23.1 — fires after commit; history.id is populated by the
    # commit above. See notification_events' failure-isolation note —
    # a notification failure here must never fail the status change
    # itself, which has already succeeded by this point.
    notification_events.application_status_changed(db, record, old_status=old_status, new_status=new_status, history_id=history.id)
    return record


def delete_application(db: Session, user_id: int, application_id: int) -> None:
    record = _get_owned(db, user_id, application_id)
    db.delete(record)  # cascades to ApplicationStatusHistory (ON DELETE CASCADE)
    db.commit()


def get_history(db: Session, user_id: int, application_id: int) -> list[ApplicationStatusHistory]:
    _get_owned(db, user_id, application_id)  # ownership check — 404s before ever touching history
    return db.scalars(
        select(ApplicationStatusHistory)
        .where(ApplicationStatusHistory.application_id == application_id)
        .order_by(ApplicationStatusHistory.changed_at.asc(), ApplicationStatusHistory.id.asc())
    ).all()


def get_stats(db: Session, user_id: int) -> dict:
    """DASHBOARD INTEGRATION — one cheap grouped-count query (never
    N+1: a single ``GROUP BY status``), plus a small "recent activity"
    read from the same status-history table every other part of this
    module already writes to."""
    rows = db.execute(
        select(Application.status, func.count())
        .where(Application.user_id == user_id)
        .group_by(Application.status)
    ).all()
    counts = {status: count for status, count in rows}
    total = sum(counts.values())

    recent = db.execute(
        select(ApplicationStatusHistory, Application.company, Application.job_title)
        .join(Application, Application.id == ApplicationStatusHistory.application_id)
        .where(Application.user_id == user_id)
        .order_by(ApplicationStatusHistory.changed_at.desc())
        .limit(10)
    ).all()

    return {
        "total": total,
        "by_status": {s: counts.get(s, 0) for s in STATUS_VALUES},
        "recent_activity": [
            {
                "application_id": history.application_id,
                "company": company,
                "job_title": job_title,
                "old_status": history.old_status,
                "new_status": history.new_status,
                "changed_at": history.changed_at.isoformat(),
            }
            for history, company, job_title in recent
        ],
    }


def _deadline_urgency(d: date, *, today: date | None = None) -> str:
    """UPCOMING DEADLINES — "clearly distinguish upcoming, due soon,
    and overdue" (V22.2 spec). Fixed, documented thresholds: overdue
    (past), due soon (within 3 days inclusive), upcoming (later)."""
    today = today or date.today()
    delta = (d - today).days
    if delta < 0:
        return "overdue"
    if delta <= 3:
        return "due_soon"
    return "upcoming"


def get_upcoming_deadlines(db: Session, user_id: int, *, days: int = 30, limit: int = 20) -> list[dict]:
    """GET /applications/upcoming-deadlines. Nearest deadline first;
    only non-terminal applications (an ACCEPTED/REJECTED/WITHDRAWN
    application's old deadline is no longer actionable). Overdue
    deadlines (yesterday or earlier) are included too, up to `days` in
    the past, since a candidate should still see "this one slipped,"
    not have it silently vanish — sorted after any future deadlines."""
    from datetime import timedelta

    from app.applications.status import TERMINAL_STATUSES

    today = date.today()
    horizon = today + timedelta(days=days)
    past_horizon = today - timedelta(days=days)

    rows = db.scalars(
        select(Application)
        .where(
            Application.user_id == user_id,
            Application.deadline.is_not(None),
            Application.deadline >= past_horizon,
            Application.deadline <= horizon,
            Application.status.not_in(TERMINAL_STATUSES),
        )
        .order_by(Application.deadline.asc())
        .limit(limit)
    ).all()

    return [
        {
            "application_id": a.id,
            "company": a.company,
            "job_title": a.job_title or a.role,
            "status": a.status,
            "deadline": a.deadline.isoformat(),
            "urgency": _deadline_urgency(a.deadline, today=today),
        }
        for a in rows
    ]


def get_dashboard(db: Session, user_id: int) -> dict:
    """GET /applications/dashboard — the richer V22.2 statistics
    surface. Reuses get_stats()'s by_status/recent_activity (never
    duplicates that query) and adds: this-week/this-month counts,
    upcoming deadlines/interviews, and stage-conversion rates computed
    from ApplicationStatusHistory (an application's *current* status
    alone would undercount, e.g. a rejected-after-interview
    application's current status is REJECTED, not INTERVIEW — history
    tracks every stage it ever actually reached)."""
    from datetime import timedelta

    base = get_stats(db, user_id)

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    this_week = db.scalar(
        select(func.count()).select_from(Application).where(Application.user_id == user_id, Application.created_at >= week_start)
    ) or 0
    this_month = db.scalar(
        select(func.count()).select_from(Application).where(Application.user_id == user_id, Application.created_at >= month_start)
    ) or 0

    ever_reached_rows = db.execute(
        select(ApplicationStatusHistory.new_status, func.count(func.distinct(ApplicationStatusHistory.application_id)))
        .join(Application, Application.id == ApplicationStatusHistory.application_id)
        .where(Application.user_id == user_id)
        .group_by(ApplicationStatusHistory.new_status)
    ).all()
    ever_reached = {status: count for status, count in ever_reached_rows}

    def _rate(numerator_status: str, denominator_status: str) -> float | None:
        # AVOID MISLEADING STATISTICS WHEN THE SAMPLE SIZE IS ZERO —
        # None (not 0, not a divide-by-zero) when nothing ever reached
        # the denominator stage; the frontend renders this as "Not
        # enough data yet" rather than a misleading "0%".
        denom = ever_reached.get(denominator_status, 0)
        if denom == 0:
            return None
        return round(ever_reached.get(numerator_status, 0) / denom, 4)

    return {
        **base,
        "applications_this_week": this_week,
        "applications_this_month": this_month,
        "upcoming_deadlines": get_upcoming_deadlines(db, user_id, limit=5),
        "conversion_rates": {
            "applied_to_interview": _rate("INTERVIEW", "APPLIED"),
            "interview_to_offer": _rate("OFFER", "INTERVIEW"),
            "offer_to_acceptance": _rate("ACCEPTED", "OFFER"),
        },
    }
