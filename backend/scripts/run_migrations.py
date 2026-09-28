"""V10 — apply every migration file in migrations/ against DATABASE_URL,
in filename order, tracking what's already been applied.

Every migration in this project is also written to be safe to re-run
on its own (``CREATE TABLE IF NOT EXISTS``, ``ADD COLUMN IF NOT
EXISTS``, etc.) — but this script additionally records each applied
file (name + content checksum) in a ``schema_migrations`` table rather
than relying on that idempotency alone. That gives three real
guarantees the idempotent-SQL-only approach didn't: (1) an explicit,
queryable audit trail of what's been applied and when, (2) a file that
was already applied is never re-executed at all (cheaper, and immune
to a future migration file that *isn't* perfectly idempotent), and (3)
if a previously-applied file's content changes on disk, this warns
loudly instead of silently doing nothing — catching an edited-in-place
migration before it causes a mismatch between environments.

Usage:
    python -m scripts.run_migrations

This targets PostgreSQL (the migrations use Postgres-specific syntax
like SERIAL and ADD COLUMN IF NOT EXISTS). For local development on
SQLite, schema is instead created directly from the SQLAlchemy models
via Base.metadata.create_all() on every app startup (see app/main.py)
— you don't need this script unless DATABASE_URL points at Postgres.

Deployment note: this is deliberately a *separate step* from starting
the API (see the `migrate` service in docker-compose.production.yml,
which the backend service's `depends_on: condition:
service_completed_successfully` waits on) rather than something the
API runs on its own boot — so a migration failure stops the deploy
before any API instance serves traffic against a half-upgraded schema,
and so N API replicas starting together don't race to apply the same
migration concurrently.
"""

import hashlib
import re
import sys
from pathlib import Path

from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def _version_sort_key(path: Path) -> list:
    """Natural/version-aware sort key so files apply in the order
    their version numbers actually mean, not plain alphabetical order.
    Splits the filename stem into alternating text/digit runs and
    converts digit runs to int, e.g. "v11_auth_recruiter" ->
    ["v", 11, "_auth_recruiter"] — this correctly sorts v1 before v11
    (a plain string sort puts v11 first, since '1' < '_'), v9 before
    v11, v16 before v16b, and v17_1/_2/_3 in that numeric order,
    without needing to hardcode every filename's version."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", path.stem)]

_TRACKING_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename VARCHAR(255) PRIMARY KEY,
    checksum VARCHAR(64) NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


def _split_statements(sql: str) -> list[str]:
    """Split a .sql file into individual executable statements.

    Strips every ``--`` line comment from the whole file *before*
    splitting on ``;`` — not after. Splitting on ``;`` first and only
    then stripping comments (an earlier version of this function)
    breaks as soon as any comment contains a semicolon as ordinary
    prose punctuation ("...creates it first; the later migration
    then..."): that semicolon gets treated as a statement terminator
    right in the middle of a comment, corrupting the split for every
    line after it in that chunk — up to and including swallowing part
    of the next real CREATE/ALTER statement into a discarded comment
    fragment. Confirmed by actually running this against a migration
    file with a semicolon in a comment sentence: it silently dropped
    part of a CREATE TABLE's column list.

    Splitting on ``;`` is itself dollar-quote-aware: a PL/pgSQL block
    like ``DO $$ BEGIN ...; ... END $$;`` (see
    v21_1_unified_search.sql's optional pg_trgm setup) legitimately
    contains semicolons *inside* the ``$$...$$`` body that terminate
    statements within the block, not the migration statement itself —
    those must not be treated as split points. Confirmed by actually
    running this against that file: without this, the DO block was
    chopped into invalid fragments partway through.

    (An even earlier version of this function rejected a whole chunk
    just for starting with a comment line, which silently dropped the
    first real statement of almost every migration file and could
    cascade into a later statement failing against a table/column
    that was never created — see ROADMAP.md's bug-review notes. That
    fix is preserved here: comment lines are removed, not used to
    reject the chunk they're in.)
    """
    comment_free_lines = [line for line in sql.split("\n") if not line.strip().startswith("--")]
    comment_free_sql = "\n".join(comment_free_lines)

    statements = []
    current: list[str] = []
    dollar_tag: str | None = None  # e.g. "$$" or "$tag$" while inside a dollar-quoted block
    i, n = 0, len(comment_free_sql)
    while i < n:
        if dollar_tag is None:
            match = re.match(r"\$[a-zA-Z_]*\$", comment_free_sql[i:])
            if match:
                dollar_tag = match.group(0)
                current.append(dollar_tag)
                i += len(dollar_tag)
                continue
            if comment_free_sql[i] == ";":
                statement = "".join(current).strip()
                if statement:
                    statements.append(statement)
                current = []
                i += 1
                continue
            current.append(comment_free_sql[i])
            i += 1
        else:
            if comment_free_sql[i:i + len(dollar_tag)] == dollar_tag:
                current.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            current.append(comment_free_sql[i])
            i += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def main() -> None:
    if settings.database_url.startswith("sqlite"):
        print(
            "DATABASE_URL is SQLite — schema is created automatically from the "
            "models on app startup, so there's nothing for this script to do. "
            "Point DATABASE_URL at Postgres to actually run these migrations."
        )
        return

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"), key=_version_sort_key)
    if not migration_files:
        print(f"No .sql files found in {MIGRATIONS_DIR}")
        return

    with engine.begin() as conn:
        conn.execute(text(_TRACKING_TABLE_DDL))
        already_applied = {
            row[0]: row[1]
            for row in conn.execute(text("SELECT filename, checksum FROM schema_migrations"))
        }

    applied_count = 0
    skipped_count = 0

    for path in migration_files:
        sql = path.read_text(encoding="utf-8")
        checksum = _checksum(sql)

        if path.name in already_applied:
            if already_applied[path.name] != checksum:
                print(
                    f"WARNING: {path.name} was already applied but its content on disk has "
                    f"changed since then (checksum mismatch). Not re-running it automatically — "
                    f"a migration file should never be edited after it's been applied to any "
                    f"environment. If this change is intentional, add a NEW migration file "
                    f"instead of editing this one.",
                    file=sys.stderr,
                )
            skipped_count += 1
            continue

        statements = _split_statements(sql)
        if not statements:
            continue

        print(f"Applying {path.name} ({len(statements)} statements)...")
        try:
            with engine.begin() as conn:
                for statement in statements:
                    conn.execute(text(statement))
                conn.execute(
                    text("INSERT INTO schema_migrations (filename, checksum) VALUES (:f, :c)"),
                    {"f": path.name, "c": checksum},
                )
        except Exception as exc:
            print(f"FAILED on {path.name}: {exc}", file=sys.stderr)
            sys.exit(1)

        applied_count += 1

    print(f"Done: {applied_count} file(s) newly applied, {skipped_count} already up to date.")


if __name__ == "__main__":
    main()
