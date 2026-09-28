from app.ingestion.adapters.base import BaseJobAdapter
from app.ingestion.models.job_record import JobRecord


class SSCAdapter(BaseJobAdapter):
    source_name = "Staff Selection Commission"

    def __init__(self, records: list[dict] | None = None):
        self.records = records or []

    def fetch(self) -> list[JobRecord]:
        """
        Convert verified SSC notification metadata into
        CareerOS JobRecord objects.

        Automatic notice discovery will be added separately.
        """

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
                    organization="Staff Selection Commission",
                    department=item.get("department"),

                    job_type="Government",
                    govt_level="Central",
                    category=item.get("category"),

                    location=item.get("location", "India"),
                    vacancies=item.get("vacancies"),

                    qualification=item.get(
                        "qualification",
                        "See official SSC notification",
                    ),

                    age_limit=item.get("age_limit"),
                    age_relaxation=item.get("age_relaxation"),

                    application_fee=item.get("application_fee"),
                    salary=item.get("salary"),
                    pay_level=item.get("pay_level"),

                    start_date=item.get("start_date"),
                    deadline=item.get("deadline"),
                    exam_date=item.get("exam_date"),

                    selection_process=item.get("selection_process"),

                    description=item.get(
                        "description",
                        "See official SSC notification",
                    ),
                )
            )

        return jobs