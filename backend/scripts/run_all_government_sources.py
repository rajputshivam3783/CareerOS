"""Run the registered government-job sources safely.

This command is intentionally conservative: disabled sources are first
validated and fetched as a dry run. Only sources that actually return at
least one record are activated when --activate-verified is supplied. Every
source is isolated so one failed/blocked official site does not abort the
remaining sources.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.db.session import SessionLocal
from app.ingestion.adapters.configured import ConfiguredSourceAdapter
from app.ingestion.orchestrator import run_source
from app.ingestion.registry_seed import seed_framework_organizations
from app.models.domain import SourceRegistry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--activate-verified",
        action="store_true",
        help="Activate disabled sources only when their dry-run fetch returns records.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        seed_framework_organizations(db)
        sources = db.scalars(
            select(SourceRegistry).order_by(SourceRegistry.priority, SourceRegistry.id)
        ).all()

        activated = []
        dry_run_failures = []
        for source in sources:
            if source.status == "active":
                continue
            adapter = ConfiguredSourceAdapter.from_registry_row(source)
            ok, reason = adapter.validate()
            if not ok:
                dry_run_failures.append({"source": source.source_name, "error": reason})
                continue
            try:
                records = adapter.fetch()
            except Exception as exc:  # noqa: BLE001
                dry_run_failures.append({"source": source.source_name, "error": str(exc)[:1000]})
                continue
            if records and args.activate_verified:
                source.status = "active"
                activated.append(source.source_name)
                db.commit()

        active = db.scalars(
            select(SourceRegistry)
            .where(SourceRegistry.status == "active")
            .order_by(SourceRegistry.priority, SourceRegistry.id)
        ).all()

        results = []
        for source in active:
            try:
                results.append(run_source(db, source))
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                results.append({"source": source.source_name, "status": "failed", "error": str(exc)[:1000]})

        print({
            "activated": activated,
            "dry_run_failures": dry_run_failures,
            "active_sources_run": len(results),
            "results": results,
        })
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
