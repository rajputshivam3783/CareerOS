import re

from app.ingestion.models.job_record import JobRecord


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None

    # Remove excessive whitespace/newlines
    value = re.sub(r"\s+", " ", value).strip()

    return value or None


def normalize_job(record: JobRecord) -> JobRecord:
    """
    Convert adapter output into a clean, consistent CareerOS JobRecord.
    """

    data = record.model_dump()

    # Clean all string fields
    for key, value in data.items():
        if isinstance(value, str):
            data[key] = clean_text(value)

    # Required/default fields
    data["title"] = data["title"] or "Untitled Opportunity"
    data["organization"] = data["organization"] or "Unknown Organization"
    data["location"] = data["location"] or "India"
    data["job_type"] = data["job_type"] or "Government"

    data["qualification"] = (
        data["qualification"] or "See official notification"
    )

    data["description"] = (
        data["description"] or "See official notification"
    )

    # Normalize common classification values
    data["job_type"] = data["job_type"].title()

    if data["govt_level"]:
        data["govt_level"] = data["govt_level"].title()

    return JobRecord(**data)