"""V25.3 — the one place a job corpus is assembled.

Every analytics module in this package asks this file for its job set.
That is the whole point: skill frequency, role demand, location
distribution, trends, and organization skill demand are all "count
something over a filtered set of jobs", and writing that filter five
times would guarantee five slightly different definitions of which
jobs count.

WHICH JOBS COUNT
----------------
``published`` only, by default. A job in ``review`` has not been seen
by a candidate; a ``rejected`` or ``suspended`` one was removed for
cause (V25.2). Counting either as market activity would report
moderation backlog as demand. Admin-facing platform intelligence can
opt into the full set explicitly (``statuses=None``), because an
administrator asking "how many jobs are stuck in review" is asking a
different question.

PERFORMANCE
-----------
Two access shapes, deliberately separated:

- ``aggregate_counts`` / ``daily_counts`` push the work into SQL
  (GROUP BY, indexed WHERE) and return small result sets. Used for
  anything whose answer is a distribution.
- ``load_jobs`` materializes rows, but only ever behind a bounded
  ``limit``, and only for analyses that genuinely need per-row text
  (skill parsing has to read ``jobs.skills``, which is a
  comma-separated text column no database can GROUP BY usefully).

There is no code path here that loads every job in the database, and
none that issues a query per job. The V25.3 index added in
``migrations/v25_3_data_intelligence.sql`` covers the
``status + published_at`` filter these queries all share.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.domain import Applicant, Job

# The statuses that represent "a real, candidate-visible listing".
PUBLIC_STATUSES: tuple[str, ...] = ("published",)

# Hard ceiling on rows any single analysis will materialize. Skill
# aggregation needs the text of each job, so it cannot be done in SQL;
# this bounds the cost of that. Corpora larger than this are sampled
# most-recent-first and the response says so (see `truncated`).
MAX_MATERIALIZED_JOBS = 2000

MAX_RANGE_DAYS = 365
DEFAULT_RANGE_DAYS = 90


@dataclass
class CorpusFilter:
    """Every filter the analytics API exposes, in one object.

    Anything not set is simply not filtered — there is no implicit
    default location, role or category, so an unfiltered corpus means
    "all published jobs" rather than a silently narrowed set.
    """

    days: int | None = None
    role_query: str | None = None
    location: str | None = None
    category: str | None = None
    job_type: str | None = None
    work_mode: str | None = None
    employment_type: str | None = None
    owner_user_ids: list[int] | None = None
    statuses: tuple[str, ...] | None = PUBLIC_STATUSES

    def describe(self) -> dict:
        """The filter as applied, echoed back in every response.

        A reader must be able to see what a number was computed over.
        "Java appears in 31 jobs" means nothing without "of the 42
        published Bangalore jobs in the last 90 days".
        """
        return {
            "days": self.days,
            "role_query": self.role_query,
            "location": self.location,
            "category": self.category,
            "job_type": self.job_type,
            "work_mode": self.work_mode,
            "employment_type": self.employment_type,
            "statuses": list(self.statuses) if self.statuses else "all",
            "organization_scoped": bool(self.owner_user_ids),
        }


def clamp_days(days: int | None, *, default: int = DEFAULT_RANGE_DAYS) -> int:
    if not days or days <= 0:
        return default
    return min(days, MAX_RANGE_DAYS)


def _window_start(days: int | None) -> datetime | None:
    if not days:
        return None
    return datetime.utcnow() - timedelta(days=clamp_days(days))


def _clauses(spec: CorpusFilter) -> list:
    """Translate a CorpusFilter into SQLAlchemy clauses.

    Every text comparison is a parameterized ``LIKE`` through the ORM.
    No caller-supplied value is ever concatenated into SQL.
    """
    clauses = []
    if spec.statuses:
        clauses.append(Job.status.in_(list(spec.statuses)))
    start = _window_start(spec.days)
    if start is not None:
        # published_at is the honest date for "when did this enter the
        # market". Jobs published before the window are excluded even
        # if edited inside it; created_at would count a listing from
        # its draft date, which is not when candidates could see it.
        clauses.append(Job.published_at.isnot(None))
        clauses.append(Job.published_at >= start)
    if spec.role_query:
        needle = f"%{spec.role_query.strip().lower()}%"
        clauses.append(func.lower(Job.title).like(needle))
    if spec.location:
        needle = f"%{spec.location.strip().lower()}%"
        clauses.append(func.lower(Job.location).like(needle))
    if spec.category:
        clauses.append(Job.category == spec.category)
    if spec.job_type:
        clauses.append(Job.job_type == spec.job_type)
    if spec.work_mode:
        clauses.append(Job.work_mode == spec.work_mode)
    if spec.employment_type:
        clauses.append(Job.employment_type == spec.employment_type)
    if spec.owner_user_ids is not None:
        # An organization with no members owns no jobs. Match nothing
        # rather than degrading to "match everything" — the difference
        # between an empty report and a cross-tenant data leak.
        clauses.append(Job.owner_user_id.in_(spec.owner_user_ids) if spec.owner_user_ids else Job.id < 0)
    return clauses


def count_jobs(db: Session, spec: CorpusFilter) -> int:
    query = select(func.count()).select_from(Job)
    for clause in _clauses(spec):
        query = query.where(clause)
    return int(db.scalar(query) or 0)


@dataclass
class JobCorpus:
    """A materialized, bounded set of jobs plus its true total."""

    jobs: list[Job] = field(default_factory=list)
    total: int = 0
    truncated: bool = False

    @property
    def size(self) -> int:
        return len(self.jobs)


def load_jobs(db: Session, spec: CorpusFilter, *, limit: int = MAX_MATERIALIZED_JOBS) -> JobCorpus:
    """Materialize a bounded corpus, newest first.

    ``total`` is the true count from a separate COUNT, so a truncated
    corpus still reports honestly how many jobs matched — the response
    never implies the sample was the whole set.
    """
    total = count_jobs(db, spec)
    query = select(Job)
    for clause in _clauses(spec):
        query = query.where(clause)
    rows = list(db.scalars(query.order_by(Job.id.desc()).limit(limit)).all())
    return JobCorpus(jobs=rows, total=total, truncated=total > len(rows))


def aggregate_counts(db: Session, spec: CorpusFilter, column, *, limit: int = 25, include_null: bool = False) -> list[dict]:
    """GROUP BY one job column over the corpus, in SQL.

    Used for every distribution whose grouping key is a real column
    (location, work mode, category, status). Skill distributions
    cannot use this — see ``skills.py`` for why.
    """
    query = select(column, func.count()).select_from(Job)
    for clause in _clauses(spec):
        query = query.where(clause)
    if not include_null:
        query = query.where(column.isnot(None), column != "")
    rows = db.execute(query.group_by(column).order_by(func.count().desc()).limit(limit)).all()
    return [{"key": key if key is not None else "unspecified", "count": int(count)} for key, count in rows]


def daily_counts(db: Session, spec: CorpusFilter, column, *, days: int) -> list[dict]:
    """A dense, zero-filled daily series bucketed in SQL.

    Dense on purpose: a sparse series makes a day with no jobs
    indistinguishable from a day with missing data, and a chart drawn
    from a sparse series silently compresses quiet periods out of
    existence.
    """
    days = clamp_days(days)
    end = datetime.utcnow().date()
    start = end - timedelta(days=days - 1)
    bucket = func.date(column)  # portable: SQLite cast(... AS Date) yields an int (year), not a date
    query = select(bucket, func.count()).select_from(Job).where(
        column >= datetime.combine(start, datetime.min.time())
    )
    for clause in _clauses(spec):
        query = query.where(clause)
    rows = db.execute(query.group_by(bucket).order_by(bucket)).all()
    return densify(rows, start, end)


def densify(rows, start: date, end: date) -> list[dict]:
    counts: dict[str, int] = {}
    for bucket, count in rows:
        if bucket is None:
            continue
        if isinstance(bucket, datetime):
            bucket = bucket.date()
        elif isinstance(bucket, str):
            # SQLite returns a string from date();
            # PostgreSQL returns a date. Both are handled rather than
            # assuming the development backend's behaviour.
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


def application_counts(db: Session, spec: CorpusFilter) -> int:
    """Platform applications made to jobs in this corpus.

    Counts ``Applicant`` — applications made THROUGH CareerOS to a
    CareerOS listing. Deliberately not ``Application``, which is the
    candidate's own private tracker of roles they are pursuing
    anywhere, including off-platform, and may contain private notes.
    Counting it here would both overstate platform activity and reach
    into data the privacy model puts out of scope.
    """
    query = select(func.count()).select_from(Applicant).join(Job, Job.id == Applicant.job_id)
    for clause in _clauses(spec):
        query = query.where(clause)
    return int(db.scalar(query) or 0)


def split_window(days: int) -> tuple[datetime, datetime, datetime]:
    """Two equal, adjacent periods for trend comparison.

    Returns (previous_start, midpoint, now). Equal-length periods
    matter: comparing "the last 30 days" against "everything before"
    would make every established skill look like it is collapsing.
    """
    now = datetime.utcnow()
    days = clamp_days(days)
    midpoint = now - timedelta(days=days)
    previous_start = now - timedelta(days=days * 2)
    return previous_start, midpoint, now


def jobs_between(db: Session, spec: CorpusFilter, start: datetime, end: datetime, *, limit: int = MAX_MATERIALIZED_JOBS) -> list[Job]:
    """Corpus rows published inside an explicit interval.

    Used by trend analysis, which needs two disjoint periods and
    therefore cannot use ``CorpusFilter.days`` (a single trailing
    window).
    """
    query = select(Job).where(Job.published_at.isnot(None), Job.published_at >= start, Job.published_at < end)
    period_spec = CorpusFilter(
        role_query=spec.role_query,
        location=spec.location,
        category=spec.category,
        job_type=spec.job_type,
        work_mode=spec.work_mode,
        employment_type=spec.employment_type,
        owner_user_ids=spec.owner_user_ids,
        statuses=spec.statuses,
    )
    for clause in _clauses(period_spec):
        query = query.where(clause)
    return list(db.scalars(query.order_by(Job.id.desc()).limit(limit)).all())


def deadline_active_clause():
    """Jobs whose application deadline has not passed.

    Expiry is not a stored status in CareerOS — a past-deadline
    listing keeps ``status='published'``. Anything reporting "open
    jobs" must therefore apply this explicitly rather than trusting
    the status column.
    """
    today = datetime.utcnow().date()
    return or_(Job.deadline.is_(None), Job.deadline >= today)
