from datetime import date
from app.ingestion.models.job_record import JobRecord


def test_job_record_allows_shared_apply_url():
    a = JobRecord(source_name="Example", title="Engineer I", organization="Acme", apply_url="https://jobs.example/apply", deadline=date(2026, 8, 1))
    b = JobRecord(source_name="Example", title="Engineer II", organization="Acme", apply_url="https://jobs.example/apply", deadline=date(2026, 8, 2))
    assert a.title != b.title and a.apply_url == b.apply_url
