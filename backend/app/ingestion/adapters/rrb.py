from app.ingestion.adapters.base import BaseJobAdapter
from app.ingestion.models.job_record import JobRecord


class RRBAdapter(BaseJobAdapter):
    source_name = "Railway Recruitment Board"

    def __init__(self, records: list[dict] | None = None):
        self.records = records or []

    def fetch(self) -> list[JobRecord]:
        out = []
        for x in self.records:
            data = dict(x)
            data.setdefault("source_name", self.source_name)
            data.setdefault("organization", self.source_name)
            data.setdefault("job_type", "Government")
            data.setdefault("govt_level", "Central")
            data.setdefault("location", "India")
            data.setdefault("qualification", "See official notification")
            data.setdefault("description", "See official notification")
            out.append(JobRecord(**data))
        return out
