import re
from uuid import uuid4

from sqlalchemy.orm import Session

from app.ingestion.models.job_record import JobRecord
from app.ingestion.services.deduplicate import is_duplicate
from app.models.domain import Job


def generate_slug(record: JobRecord) -> str:
    """
    Generate a URL-safe and unique slug for an ingested job.
    """

    base = f"{record.organization}-{record.title}"

    slug = base.lower()

    # Replace non-alphanumeric characters with "-"
    slug = re.sub(r"[^a-z0-9]+", "-", slug)

    # Remove leading/trailing "-"
    slug = slug.strip("-")

    # Keep slug reasonably short
    slug = slug[:140].rstrip("-")

    # Unique suffix prevents slug collisions
    suffix = uuid4().hex[:8]

    return f"{slug}-{suffix}"


def publish_to_review(
    db: Session,
    record: JobRecord,
):
    """
    Insert a normalized opportunity into the review queue.
    """

    if is_duplicate(db, record):
        return False, None

    job = Job(
        slug=generate_slug(record),

        source_name=record.source_name,
        source_reference=record.source_reference,

        official_url=record.official_url,
        notification_url=record.notification_url,
        apply_url=record.apply_url,

        title=record.title,
        organization=record.organization,
        department=record.department,

        job_type=record.job_type,
        govt_level=record.govt_level,
        category=record.category,
        employment_type=record.employment_type,
        work_mode=record.work_mode,
        industry=record.industry,
        experience_required=record.experience_required,
        stipend=record.stipend,
        duration=record.duration,

        location=record.location,
        vacancies=record.vacancies,

        qualification=record.qualification,
        age_limit=record.age_limit,
        age_relaxation=record.age_relaxation,

        application_fee=record.application_fee,
        salary=record.salary,
        pay_level=record.pay_level,

        start_date=record.start_date,
        deadline=record.deadline,
        exam_date=record.exam_date,
        admit_card_url=record.admit_card_url,
        admit_card_date=record.admit_card_date,
        result_url=record.result_url,
        result_date=record.result_date,

        selection_process=record.selection_process,
        description=record.description,

        # V19.1 — Government Recruitment Core.
        ad_number=record.ad_number,
        answer_key_url=record.answer_key_url,
        organization_id=record.organization_id,

        verified=False,
        status="review",
    )

    try:
        db.add(job)
        db.commit()
        db.refresh(job)

        return True, job

    except Exception:
        db.rollback()
        raise