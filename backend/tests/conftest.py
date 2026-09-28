"""Test-suite bootstrap.

Everything here runs before any test module (and therefore before ``app.core.config.settings`` -
a process-wide singleton - is created), so it is a *test-environment* change only; no
application code path is touched.

* ``AUTH_RATE_LIMIT_ATTEMPTS`` is raised so test files that seed several fixtures with
  back-to-back logins do not share one tiny budget (V19.5 fix, carried forward).
  ``test_v16d_rate_limit.py`` deliberately exercises real rate limiting with its own explicit limit.
* ``AUTO_VERIFY_EMAIL_IN_TESTS`` must be set here, not only inside individual test modules: the
  settings singleton is frozen by whichever test module imports the app first, and if that module
  does not set the flag every later module's login fails with "Verify your email before logging in".
* ``DATABASE_URL`` gets a throwaway SQLite default for the same reason (modules that need their own
  file still assign it before importing the app, which takes precedence when they are run alone).
* Leftover SQLite files / upload folders from a previous run are removed so every run starts from
  an empty database (stale rows otherwise cause "Email already registered" style failures).
* A module-scoped autouse fixture rebuilds the schema before every test module. In one pytest
  process all modules share the single database chosen when the settings singleton was created, so
  without this, data seeded by one module (same e-mails, same ``(organization, title)`` job pairs that
  the ingestion de-duplicator rejects, thresholds, ...) leaks into the next. Each module therefore
  starts from an empty database, exactly as it does when run on its own.
* An autouse fixture clears the in-memory rate-limit counters before each test, so a limited bucket
  (for example ``account-lifecycle``: 5 requests / 300 s per IP) cannot be exhausted by an earlier
  test that shares the same TestClient IP.
"""

import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("AUTH_RATE_LIMIT_ATTEMPTS", "1000")
os.environ.setdefault("AUTO_VERIFY_EMAIL_IN_TESTS", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_careeros.db")


def _clean_previous_run_artifacts() -> None:
    for base in {Path.cwd(), Path(__file__).resolve().parents[1]}:
        for pattern in ("test_careeros*.db", "test_careeros*.db-journal", "test_careeros*.db-wal", "test_careeros*.db-shm"):
            for path in base.glob(pattern):
                path.unlink(missing_ok=True)
        for path in base.glob("test_*uploads"):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)


_clean_previous_run_artifacts()


@pytest.fixture(autouse=True)
def _reset_in_memory_rate_limits():
    from app.core import rate_limit

    with rate_limit._lock:
        rate_limit._hits.clear()
    yield


@pytest.fixture(autouse=True, scope="module")
def _fresh_database_per_module():
    import app.main  # noqa: F401  - make sure every model is registered on Base.metadata
    from app.db.base import Base
    from app.db.session import engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
