from datetime import date
from pydantic import BaseModel, Field


class JobRecord(BaseModel):
    # Source information
    source_name: str
    source_reference: str | None = None
    official_url: str | None = None
    notification_url: str | None = None
    apply_url: str | None = None

    # Basic job information
    title: str
    organization: str
    department: str | None = None

    # Classification
    job_type: str = "Government"
    govt_level: str | None = None
    category: str | None = None

    # V3 — private careers, internships, apprenticeships
    employment_type: str | None = None  # Full-time / Part-time / Contract / Internship / Apprenticeship / Freelance
    work_mode: str | None = None  # Onsite / Remote / Hybrid
    industry: str | None = None
    experience_required: str | None = None  # free text, e.g. "0-2 years" or "Freshers"
    stipend: str | None = None  # internships/apprenticeships often pay a stipend rather than a salary
    duration: str | None = None  # e.g. "6 months" — internship/apprenticeship term length

    # Location / vacancies
    location: str = "India"
    vacancies: int | None = Field(default=None, ge=0)

    # Eligibility
    qualification: str = "See official notification"
    age_limit: str | None = None
    age_relaxation: str | None = None

    # Compensation / fees
    application_fee: str | None = None
    salary: str | None = None
    pay_level: str | None = None

    # Important dates
    start_date: date | None = None
    deadline: date | None = None
    exam_date: date | None = None
    # V7 exam lifecycle — usually filled in later via admin edit, not at initial ingestion.
    admit_card_url: str | None = None
    admit_card_date: date | None = None
    result_url: str | None = None
    result_date: date | None = None

    # Recruitment information
    selection_process: str | None = None
    description: str = "See official notification"

    # V19.1 — Government Recruitment Core. Optional; existing adapters
    # that don't set these keep working unchanged (Job.ad_number /
    # Job.answer_key_url / Job.organization_id are all nullable).
    ad_number: str | None = None
    answer_key_url: str | None = None
    organization_id: int | None = None