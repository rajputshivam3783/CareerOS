"""V3 Partner submissions — the legitimate intake path for private-sector
postings.

Rather than scraping commercial job boards (whose terms of service
generally prohibit it), an employer or an authorized aggregator
registers as a Partner (see `/admin/partners` in api/admin.py) and
pushes postings here directly. Submissions flow through the same
normalize -> dedupe -> review pipeline as everything else — a partner
key does not skip human review before a listing goes public.
"""

from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.constants import EMPLOYMENT_TYPES, JOB_TYPES, WORK_MODES
from app.core.rate_limit import enforce_rate_limit
from app.core.security import verify_password
from app.core.validators import http_url_validator
from app.db.session import get_db
from app.ingestion.adapters.generic_metadata import GenericMetadataAdapter
from app.ingestion.ingest import run_ingestion
from app.models.domain import Partner

router = APIRouter()

_PRIVATE_JOB_TYPES = [t for t in JOB_TYPES if t != "Government"]


def partner_guard(
    request: Request,
    x_partner_id: int = Header(...),
    x_partner_key: str = Header(...),
    db: Session = Depends(get_db),
) -> Partner:
    # V25.6: partner keys were previously verifiable with unlimited attempts. Same limiter
    # (per client IP) the login and admin-key endpoints already use.
    enforce_rate_limit(request, bucket="partner-key", limit=30, window=60)
    partner = db.get(Partner, x_partner_id)
    if not partner or not partner.active or not verify_password(x_partner_key, partner.api_key_hash):
        raise HTTPException(401, "Invalid partner credentials")
    return partner


class PartnerJobIn(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    organization: str | None = Field(default=None, max_length=220)
    department: str | None = None
    job_type: str = "Private"
    category: str | None = None
    employment_type: str | None = None
    work_mode: str | None = None
    industry: str | None = None
    experience_required: str | None = None
    location: str = "India"
    vacancies: int | None = Field(default=None, ge=0)
    qualification: str = "See job description"
    salary: str | None = None
    stipend: str | None = None
    duration: str | None = None
    application_fee: str | None = None
    start_date: date | None = None
    deadline: date | None = None
    selection_process: str | None = None
    description: str = "See job description"
    apply_url: str | None = None
    notification_url: str | None = None
    official_url: str | None = None
    _validate_urls = http_url_validator("apply_url", "notification_url", "official_url")
    source_reference: str | None = None

    @field_validator("job_type")
    @classmethod
    def job_type_must_be_private_category(cls, value: str) -> str:
        if value not in _PRIVATE_JOB_TYPES:
            raise ValueError(f"job_type must be one of {_PRIVATE_JOB_TYPES}")
        return value

    @field_validator("employment_type")
    @classmethod
    def employment_type_must_be_known(cls, value: str | None) -> str | None:
        if value is not None and value not in EMPLOYMENT_TYPES:
            raise ValueError(f"employment_type must be one of {EMPLOYMENT_TYPES}")
        return value

    @field_validator("work_mode")
    @classmethod
    def work_mode_must_be_known(cls, value: str | None) -> str | None:
        if value is not None and value not in WORK_MODES:
            raise ValueError(f"work_mode must be one of {WORK_MODES}")
        return value


@router.post("/jobs", status_code=201)
def submit_job(
    payload: PartnerJobIn,
    partner: Partner = Depends(partner_guard),
    db: Session = Depends(get_db),
):
    record = payload.model_dump()
    record["organization"] = record["organization"] or partner.name
    record["source_reference"] = record["source_reference"] or f"partner-{partner.id}-{payload.title}"

    adapter = GenericMetadataAdapter(
        source_name=f"Partner: {partner.name}",
        job_type=payload.job_type,
        records=[record],
    )
    result = run_ingestion(db, adapter)
    return result
