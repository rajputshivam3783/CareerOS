#!/usr/bin/env python3
"""V25.6 — run the opt-in retention purge.

    python scripts/retention_purge.py              # dry run (default): prints what WOULD be deleted
    python scripts/retention_purge.py --execute    # deletes; requires RETENTION_PURGE_ENABLED=true

Schedule it from cron / your orchestrator, not from the web process. Policy and the list of
data that is never purged: docs/DATA_RETENTION_AND_DELETION.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.retention import purge_expired  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def main() -> int:
    execute = "--execute" in sys.argv
    db = SessionLocal()
    try:
        counts = purge_expired(db, dry_run=not execute)
        if execute:
            db.commit()
        print(("DELETED" if execute else "WOULD DELETE") + ":", counts)
        return 0
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print("ERROR:", exc, file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
