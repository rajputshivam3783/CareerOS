"""Generic metadata adapter — V3 private careers, internships, apprenticeships.

Unlike SSC/UPSC/RRB (one fixed organization per adapter), private-sector
postings come from many different employers, so a single adapter
parameterized by `job_type`/`organization` per call is more honest than
one hardcoded class per company. Feed it a list of dicts (from a
partner submission, an admin bulk import, or a verified feed) and it
emits JobRecord objects the same way the government adapters do.

This intentionally does NOT scrape named commercial job boards
(LinkedIn, Naukri, Internshala, etc.) — their terms of service
generally prohibit automated scraping. The legitimate path for private
listings is direct submission: see app/api/partners.py for the partner
API that lets an employer or an authorized aggregator push postings
into the same normalize -> dedupe -> review pipeline.
"""

from app.ingestion.adapters.base import BaseJobAdapter
from app.ingestion.models.job_record import JobRecord


class GenericMetadataAdapter(BaseJobAdapter):
    def __init__(
        self,
        source_name: str,
        job_type: str,
        records: list[dict] | None = None,
    ):
        self.source_name = source_name
        self.job_type = job_type
        self.records = records or []

    def fetch(self) -> list[JobRecord]:
        jobs: list[JobRecord] = []

        for item in self.records:
            jobs.append(
                JobRecord(
                    source_name=self.source_name,
                    source_reference=item.get("source_reference"),
                    official_url=item.get("official_url"),
                    notification_url=item.get("notification_url"),
                    apply_url=item.get("apply_url"),
                    title=item["title"],
                    organization=item["organization"],
                    department=item.get("department"),
                    job_type=self.job_type,
                    govt_level=item.get("govt_level"),
                    category=item.get("category"),
                    employment_type=item.get("employment_type"),
                    work_mode=item.get("work_mode"),
                    industry=item.get("industry"),
                    experience_required=item.get("experience_required"),
                    stipend=item.get("stipend"),
                    duration=item.get("duration"),
                    location=item.get("location", "India"),
                    vacancies=item.get("vacancies"),
                    qualification=item.get("qualification", "See job description"),
                    age_limit=item.get("age_limit"),
                    age_relaxation=item.get("age_relaxation"),
                    application_fee=item.get("application_fee"),
                    salary=item.get("salary"),
                    pay_level=item.get("pay_level"),
                    start_date=item.get("start_date"),
                    deadline=item.get("deadline"),
                    exam_date=item.get("exam_date"),
                    admit_card_url=item.get("admit_card_url"),
                    admit_card_date=item.get("admit_card_date"),
                    result_url=item.get("result_url"),
                    result_date=item.get("result_date"),
                    selection_process=item.get("selection_process"),
                    description=item.get("description", "See job description"),
                )
            )

        return jobs
