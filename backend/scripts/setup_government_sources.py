"""V25.7 — one-shot setup for automatic government-job collection.

    python -m scripts.setup_government_sources            # seed + dry-run report only
    python -m scripts.setup_government_sources --activate # also set status=active for
                                                          # sources whose dry run found >=1 record

What it does
  1. Seeds the ~30 central organisations into source_registry (idempotent, disabled).
  2. For every non-active source: validate() + a real fetch() WITHOUT saving anything,
     and prints how many notices it found plus a sample title + the fields auto-extraction
     would fill.  This is the "operator verification" the project policy asks for, done
     with evidence instead of guesswork.
  3. With --activate, sources that returned >=1 record are switched to active
     (schedule stays 'daily'); everything else is left disabled.

Records always land in the admin review queue — nothing is auto-published.
"""
import argparse

from app.db.session import SessionLocal
from app.ingestion.adapters.configured import ConfiguredSourceAdapter
from app.ingestion.registry_seed import seed_framework_organizations
from app.ingestion.services.enrichment import enrich_record
from app.models.domain import SourceRegistry
from sqlalchemy import select


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--activate", action="store_true")
    ap.add_argument("--only", help="substring of source_name to limit to")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        print("Seed:", seed_framework_organizations(db))
        rows = db.scalars(select(SourceRegistry).order_by(SourceRegistry.priority, SourceRegistry.id)).all()
        for src in rows:
            if args.only and args.only.lower() not in src.source_name.lower():
                continue
            if src.status == "active":
                print(f"[active ] {src.source_name}")
                continue
            adapter = ConfiguredSourceAdapter.from_registry_row(src)
            ok, reason = adapter.validate()
            if not ok:
                print(f"[invalid] {src.source_name}: {reason}")
                continue
            try:
                records = adapter.fetch()
            except Exception as exc:  # noqa: BLE001
                print(f"[failed ] {src.source_name}: {exc}")
                continue
            if not records:
                print(f"[empty  ] {src.source_name}: 0 records (page changed, JS-rendered, or blocked) — left disabled")
                continue
            try:
                sample = enrich_record(records[0], db)
                got = [f for f in ("vacancies", "deadline", "qualification", "age_limit", "application_fee", "ad_number")
                       if getattr(sample, f, None) not in (None, "", "See official notification")]
                sample_title = (sample.title or "Untitled")[:70]
            except Exception as exc:  # noqa: BLE001
                sample = records[0]
                got = []
                sample_title = (getattr(sample, "title", None) or "Untitled")[:70]
                print(f"[warn   ] {src.source_name}: fetch worked but enrichment failed: {exc}")
            print(f"[ok     ] {src.source_name}: {len(records)} records; sample={sample_title!r}; auto-fields={got}")
            if args.activate:
                src.status = "active"
                db.commit()
                print("          -> activated")
    finally:
        db.close()


if __name__ == "__main__":
    main()
