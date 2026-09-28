"""Run every enabled V2 ingestion source once, from the command line.

Useful for a first manual check after enabling a source in
app/ingestion/sources.py, or as the command an external cron/CI
scheduler calls instead of relying on the in-process scheduler
(recommended for multi-replica deployments — see
app/ingestion/README.md).

Usage:
    python -m scripts.run_ingestion_now
"""

from app.db.session import SessionLocal
from app.ingestion.ingest import run_all_enabled_sources


def main():
    db = SessionLocal()
    try:
        results = run_all_enabled_sources(db)
        if not results:
            print("No enabled sources — see app/ingestion/sources.py")
        for result in results:
            print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
