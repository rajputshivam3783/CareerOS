"""Local verification script for UPSCAdapter — mirrors
test_ssc_ingestion.py's pattern. Run manually against a local DB to
exercise the curated (non-scraped) manual-record ingestion path:

    cd backend
    python -m scripts.test_upsc_ingestion

This is a curated example record for smoke-testing the adapter and
the ingest->normalize->review pipeline end to end — it is not a
live-scraped or independently verified notification, the same
caveat every other source in this project carries (see
app/ingestion/sources.py). The record still lands in admin review
like anything else; nothing here auto-publishes.
"""
from datetime import date

from app.db.session import SessionLocal
from app.ingestion.adapters.upsc import UPSCAdapter
from app.ingestion.ingest import run_ingestion


def main():
    records = [
        {
            "source_reference": "UPSC-CSE-2026",
            "official_url": "https://www.upsc.gov.in/examinations/active-exams",
            "notification_url": "https://www.upsc.gov.in/examinations/active-exams",
            "title": "Civil Services Examination, 2026",
            "department": "Union Public Service Commission",
            "category": "Civil Services",
            "govt_level": "Central",
            "location": "India",
            "qualification": "Bachelor's degree from a recognized university",
            "start_date": date(2026, 2, 1),
            "deadline": date(2026, 3, 4),
            "selection_process": "Preliminary examination, Main examination, Interview",
            "description": (
                "Recruitment to the Indian Administrative Service, Indian "
                "Foreign Service, Indian Police Service, and other Central "
                "civil services and posts."
            ),
        }
    ]

    db = SessionLocal()
    try:
        result = run_ingestion(db=db, adapter=UPSCAdapter(records))
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
