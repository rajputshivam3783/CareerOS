"""Database engine/session setup.

Works zero-config against local SQLite, and against PostgreSQL when
``DATABASE_URL`` is set (see backend/.env.example). Pool sizing (V10)
only applies to Postgres — SQLite's own driver doesn't support these
pool arguments and doesn't need them for a single-file local database.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

_engine_kwargs = {"pool_pre_ping": True}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=settings.db_pool_recycle_seconds,
    )

engine = create_engine(settings.database_url, **_engine_kwargs)

if _is_sqlite:
    # SQLite ignores every ON DELETE CASCADE/SET NULL in the schema
    # unless foreign key enforcement is turned on per-connection — it
    # is off by default for backward compatibility with SQLite
    # databases older than the feature. Without this, dev/test
    # behavior silently diverges from real Postgres (where these
    # actions always apply): a deleted parent row would leave orphaned
    # or stale-pointing child rows in SQLite, cascades/set-nulls that
    # work correctly in production would appear broken in dev/test.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    """FastAPI dependency yielding a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
