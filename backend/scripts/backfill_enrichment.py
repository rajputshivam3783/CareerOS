"""V25.7 — fill details for review-queue jobs that only have title + link.
    python -m scripts.backfill_enrichment [limit]
"""
import sys

from app.db.session import SessionLocal
from app.ingestion.services.enrichment import enrich_pending_jobs

if __name__ == "__main__":
    db = SessionLocal()
    try:
        print(enrich_pending_jobs(db, limit=int(sys.argv[1]) if len(sys.argv) > 1 else 100))
    finally:
        db.close()
