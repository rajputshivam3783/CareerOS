import re
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.domain import Job
from app.ingestion.models.job_record import JobRecord


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _match_conditions(record: JobRecord) -> list:
    conditions = []
    if record.source_name and record.source_reference:
        conditions.append(and_(Job.source_name == record.source_name, Job.source_reference == record.source_reference))
    if record.notification_url:
        conditions.append(Job.notification_url == record.notification_url)
    # V19.1 — Government Recruitment Core. An advertisement number is
    # only unique within its issuing organization (two different
    # organizations can both publish an "Advt No. 01/2026"), so this
    # is deliberately scoped to organization+ad_number, not ad_number
    # alone.
    if record.ad_number:
        conditions.append(and_(
            Job.organization.ilike(record.organization.strip()),
            Job.ad_number == record.ad_number.strip(),
        ))
    if record.official_url:
        conditions.append(Job.official_url == record.official_url)

    # Fallback is intentionally conservative. SQL handles case-insensitive
    # title/org matching; deadline, when supplied, prevents yearly campaigns
    # with reused titles from colliding.
    fallback = and_(
        Job.organization.ilike(record.organization.strip()),
        Job.title.ilike(record.title.strip()),
    )
    if record.deadline is not None:
        fallback = and_(fallback, or_(Job.deadline == record.deadline, Job.deadline.is_(None)))
    conditions.append(fallback)
    return conditions


def is_duplicate(db: Session, record: JobRecord) -> bool:
    """Detect duplicates using stable recruitment identifiers.

    Shared application portals are deliberately *not* identifiers: many
    employers reuse one apply URL for multiple openings.
    """
    return db.scalar(select(Job.id).where(or_(*_match_conditions(record))).limit(1)) is not None


def find_matching_job(db: Session, record: JobRecord) -> Job | None:
    """V19.2 — same matching logic as is_duplicate(), but returns the
    matched row instead of a boolean. Used by
    app.ingestion.services.change_detection to diff an incoming record
    against what's already on file (e.g. to notice a deadline
    extension or a newly-published result) rather than only deciding
    whether to skip it."""
    return db.scalar(select(Job).where(or_(*_match_conditions(record))).limit(1))
