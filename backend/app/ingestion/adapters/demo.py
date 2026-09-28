from app.ingestion.adapters.base import BaseJobAdapter
from app.ingestion.models.job_record import JobRecord


class DemoAdapter(BaseJobAdapter):
    source_name = "V2 Demo Source"

    def fetch(self) -> list[JobRecord]:
        return [
            JobRecord(
                source_name=self.source_name,
                source_reference="V2-DEMO-001",
                title="  CareerOS V2 Government Job Test  ",
                organization="  CareerOS Demo Department  ",
                job_type="Government",
                govt_level="Central",
                location="India",
                vacancies=25,
                qualification="Graduate",
                salary="See official notification",
                description="  V2 ingestion pipeline database test.  ",
            )
        ]