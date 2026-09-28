from datetime import date

from app.db.session import SessionLocal
from app.ingestion.adapters.ssc import SSCAdapter
from app.ingestion.ingest import run_ingestion


def main():
    records = [
        {
            "source_reference": "SSC-CHT-2026",
            "official_url": "https://ssc.gov.in/",
            "notification_url": (
                "https://ssc.gov.in/api/attachment/uploads/"
                "masterData/NoticeBoards/Notice_of_adv_cht_2026.pdf"
            ),
            "title": "Combined Hindi Translators Examination, 2026",
            "department": "Government of India",
            "category": "Translation",
            "location": "India",
            "qualification": "See official SSC notification",
            "start_date": date(2026, 4, 23),
            "deadline": date(2026, 5, 14),
            "selection_process": (
                "Computer Based Examination and subsequent "
                "stages as specified by SSC"
            ),
            "description": (
                "Recruitment for Junior Hindi Translator, "
                "Junior Translation Officer, Junior Translator, "
                "Senior Hindi Translator and Senior Translation "
                "Officer posts."
            ),
        }
    ]

    db = SessionLocal()

    try:
        result = run_ingestion(
            db=db,
            adapter=SSCAdapter(records),
        )

        print(result)

    finally:
        db.close()


if __name__ == "__main__":
    main()