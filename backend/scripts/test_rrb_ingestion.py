"""Local verification script for RRBAdapter — mirrors
test_ssc_ingestion.py's pattern. Run manually against a local DB:

    cd backend
    python -m scripts.test_rrb_ingestion

Same caveat as every curated example script in this project: this is
a hand-entered record for smoke-testing the adapter and pipeline, not
a live-scraped or independently verified notification. It still lands
in admin review, not auto-published.
"""
from datetime import date

from app.db.session import SessionLocal
from app.ingestion.adapters.rrb import RRBAdapter
from app.ingestion.ingest import run_ingestion


def main():
    records = [
        {
            "source_reference": "RRB-NTPC-2026",
            "official_url": "https://www.rrbcdg.gov.in/employment-notices.php",
            "notification_url": "https://www.rrbcdg.gov.in/employment-notices.php",
            "title": "Non-Technical Popular Categories (NTPC) Recruitment, 2026",
            "department": "Railway Recruitment Boards",
            "category": "Railways",
            "govt_level": "Central",
            "location": "India",
            "qualification": "See official RRB notification",
            "start_date": date(2026, 1, 15),
            "deadline": date(2026, 2, 20),
            "selection_process": "Computer Based Test, Skill Test/Typing Test, Document Verification",
            "description": "Recruitment to various non-technical popular category posts across Indian Railways.",
        }
    ]

    db = SessionLocal()
    try:
        result = run_ingestion(db=db, adapter=RRBAdapter(records))
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
