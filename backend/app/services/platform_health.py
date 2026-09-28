"""V25.2 — platform health, background-job and ingestion monitoring.

Spec sections 16–18 all carry the same instruction in different
words: report what is actually true, and say "unknown" rather than
inventing a green light. That instruction shapes every function here.

THE THREE-STATE RULE
--------------------
Every indicator reports one of:

    "ok"        — checked, and it worked.
    "degraded"  — checked, and it partly worked / is behind.
    "error"     — checked, and it failed.
    "unknown"   — NOT checked, because this deployment has no way to
                  check it (no provider configured, feature disabled,
                  scheduler not running in this process).

"unknown" is a first-class result, not a failure. A deployment with no
AI provider configured is not unhealthy — it simply has no AI provider,
and reporting "ok" there would be a fabricated green light while
reporting "error" would page someone about a feature they chose not to
enable.

WHAT IS NEVER RETURNED
----------------------
No secrets. Provider status is derived from *whether* a credential is
configured, never from its value; no API key, SMTP password, database
password or JWT secret appears in any response from this module. The
database indicator reports connectivity and driver family, not the
DSN — ``sqlite`` / ``postgresql``, never the URL, which contains
credentials in production.

EXTERNAL CALLS
--------------
No health check in this module makes an outbound network request.
An admin dashboard that fans out to every third-party provider on
every page load is a self-inflicted outage amplifier, and a
credential-verifying call would be the exact "make external provider
credentials visible" risk section 16 warns about. Provider indicators
are therefore *configuration* checks plus the durable delivery
records the application already writes (``EmailMessage``,
``AIUsageLog``), which are evidence of whether the provider actually
worked recently — better evidence than a synthetic ping, and free.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.domain import (
    AutomationLog,
    EmailMessage,
    IngestionDeadLetter,
    IngestionRun,
    Notification,
    SourceRegistry,
)

log = logging.getLogger("careeros.platform_health")

OK = "ok"
DEGRADED = "degraded"
ERROR = "error"
UNKNOWN = "unknown"


def _indicator(name: str, status: str, detail: str, **extra) -> dict:
    return {"name": name, "status": status, "detail": detail, **extra}


def database_health(db: Session) -> dict:
    """Connectivity, driver family, and a cheap round-trip timing.

    Deliberately ``SELECT 1`` — the same probe ``/ready`` already uses,
    so this screen and the orchestrator's readiness probe agree about
    what "the database is up" means.
    """
    started = datetime.utcnow()
    try:
        db.execute(text("SELECT 1"))
        elapsed_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
        return _indicator(
            "database",
            OK,
            "Database responded to a connectivity probe.",
            # engine.name is the driver family ("sqlite"/"postgresql"),
            # not the DSN. The DSN carries credentials and is never
            # returned.
            driver=engine.name,
            latency_ms=elapsed_ms,
        )
    except Exception as exc:
        log.warning("Database health probe failed", exc_info=True)
        return _indicator("database", ERROR, f"Database probe failed: {type(exc).__name__}")


def migration_health(db: Session) -> dict:
    """Whether the tables the running code expects actually exist.

    CareerOS applies schema changes with plain SQL files
    (``backend/migrations/*.sql`` + ``scripts/run_migrations.py``) and
    ``Base.metadata.create_all`` on SQLite — there is no Alembic
    version table to read. So "migration status" is answered the only
    honest way available: compare the tables the ORM models declare
    against the tables actually present, and report any that are
    missing. That is the failure this check exists to catch — code
    deployed ahead of its migration.
    """
    try:
        from app.db.base import Base

        inspector = inspect(engine)
        present = set(inspector.get_table_names())
        expected = set(Base.metadata.tables.keys())
        missing = sorted(expected - present)
        if missing:
            return _indicator(
                "migrations",
                ERROR,
                "Tables declared by the application are missing from the database. "
                "A migration has probably not been applied.",
                missing_tables=missing[:20],
                missing_count=len(missing),
            )
        return _indicator(
            "migrations",
            OK,
            "Every table declared by the application exists.",
            table_count=len(expected),
        )
    except Exception:
        log.warning("Migration health check failed", exc_info=True)
        return _indicator("migrations", UNKNOWN, "Could not inspect the database schema.")


def scheduler_health() -> dict:
    """Background scheduler state, read from the in-process record the
    scheduler already keeps (``app.scheduler.job_health``).

    Two honest caveats, both reported rather than hidden:

    - That map is process-local. In a multi-replica deployment only
      one replica runs the scheduler (``settings.scheduler_enabled``),
      so an admin request served by a different replica sees no job
      history. That is reported as "unknown", never as "no jobs have
      run".
    - A job that has never run has no entry at all, which is
      different from a job that ran and failed.
    """
    try:
        from app.scheduler import job_health
    except Exception:  # pragma: no cover - defensive
        return _indicator("scheduler", UNKNOWN, "Scheduler module unavailable in this process.")

    if not settings.scheduler_enabled:
        return _indicator(
            "scheduler",
            UNKNOWN,
            "The scheduler is disabled on this instance by configuration (SCHEDULER_ENABLED=false). "
            "Background job state is reported by whichever instance runs it.",
            jobs=[],
        )
    if not job_health:
        return _indicator(
            "scheduler",
            UNKNOWN,
            "No scheduled job has reported a run in this process yet. In a multi-instance "
            "deployment this instance may not be the one running the scheduler.",
            jobs=[],
        )

    jobs = [
        {
            "job_id": job_id,
            "last_run_at": entry.get("last_run_at"),
            "ok": entry.get("ok"),
            "detail": (str(entry.get("detail"))[:200] if entry.get("detail") else None),
        }
        for job_id, entry in sorted(job_health.items())
    ]
    failing = [j for j in jobs if j["ok"] is False]
    if failing:
        return _indicator(
            "scheduler",
            DEGRADED,
            f"{len(failing)} of {len(jobs)} scheduled jobs reported a failure on their last run.",
            jobs=jobs,
        )
    return _indicator("scheduler", OK, f"{len(jobs)} scheduled jobs reported a successful last run.", jobs=jobs)


def email_health(db: Session) -> dict:
    """Email provider status from configuration plus the durable
    ``EmailMessage`` queue the V23.2 system already maintains."""
    window_start = datetime.utcnow() - timedelta(hours=24)
    try:
        queued = db.scalar(select(func.count()).select_from(EmailMessage).where(EmailMessage.status == "QUEUED")) or 0
        failed = (
            db.scalar(
                select(func.count())
                .select_from(EmailMessage)
                .where(EmailMessage.status == "FAILED", EmailMessage.failed_at >= window_start)
            )
            or 0
        )
        sent = (
            db.scalar(
                select(func.count())
                .select_from(EmailMessage)
                .where(EmailMessage.status == "SENT", EmailMessage.sent_at >= window_start)
            )
            or 0
        )
    except Exception:
        log.warning("Email health query failed", exc_info=True)
        return _indicator("email", UNKNOWN, "Could not read the email queue.")

    if settings.email_mode != "smtp":
        return _indicator(
            "email",
            UNKNOWN,
            f"Email is in '{settings.email_mode}' mode — messages are rendered and logged, not delivered. "
            "No external provider is configured.",
            queued=queued,
            failed_24h=failed,
            sent_24h=sent,
            mode=settings.email_mode,
        )
    # smtp mode — configured flags only, never the credentials.
    if not settings.smtp_host or not settings.smtp_from_email:
        return _indicator(
            "email",
            ERROR,
            "Email mode is 'smtp' but SMTP host/sender are not configured.",
            queued=queued,
            failed_24h=failed,
            sent_24h=sent,
            mode=settings.email_mode,
        )
    status = DEGRADED if failed > 0 else OK
    detail = (
        f"{failed} message(s) failed in the last 24 hours."
        if failed
        else "SMTP is configured and no delivery failures were recorded in the last 24 hours."
    )
    return _indicator(
        "email", status, detail, queued=queued, failed_24h=failed, sent_24h=sent, mode=settings.email_mode
    )


def ai_provider_health(db: Session) -> dict:
    """AI availability from configuration only.

    Reports *which provider is selected* and *whether a credential is
    present* — never the credential, and never a live call to the
    provider to test it.
    """
    provider = settings.ai_default_provider
    key_by_provider = {
        "anthropic": settings.ai_anthropic_api_key,
        "openai": settings.ai_openai_api_key,
        "gemini": settings.ai_gemini_api_key,
        "openrouter": settings.ai_openrouter_api_key,
    }
    configured = bool(key_by_provider.get(provider))
    recent_errors = 0
    try:
        from app.models.domain import AIUsageLog

        window_start = datetime.utcnow() - timedelta(hours=24)
        recent_errors = (
            db.scalar(
                select(func.count())
                .select_from(AIUsageLog)
                .where(AIUsageLog.created_at >= window_start, AIUsageLog.success.is_(False))
            )
            or 0
        )
    except Exception:
        # AIUsageLog may not carry a `success` column in every
        # deployment lineage; a missing signal is "unknown", not an
        # invented zero.
        recent_errors = -1

    if not configured:
        return _indicator(
            "ai_provider",
            UNKNOWN,
            f"No API credential is configured for the selected AI provider ('{provider}'). "
            "AI-backed features report themselves as unavailable.",
            provider=provider,
            configured=False,
        )
    if recent_errors > 0:
        return _indicator(
            "ai_provider",
            DEGRADED,
            f"{recent_errors} AI request(s) failed in the last 24 hours.",
            provider=provider,
            configured=True,
            failed_24h=recent_errors,
        )
    return _indicator(
        "ai_provider",
        OK,
        f"AI provider '{provider}' is configured.",
        provider=provider,
        configured=True,
        failed_24h=None if recent_errors < 0 else 0,
    )


def notification_health(db: Session) -> dict:
    """Notification processing, from the durable rows the V19.4/V23.1
    engines already write."""
    window_start = datetime.utcnow() - timedelta(hours=24)
    try:
        created = (
            db.scalar(select(func.count()).select_from(Notification).where(Notification.created_at >= window_start))
            or 0
        )
        last_automation = db.scalar(select(func.max(AutomationLog.created_at)))
    except Exception:
        log.warning("Notification health query failed", exc_info=True)
        return _indicator("notifications", UNKNOWN, "Could not read notification records.")

    if last_automation is None:
        return _indicator(
            "notifications",
            UNKNOWN,
            "No automation run has been recorded yet.",
            notifications_24h=created,
            last_automation_run_at=None,
        )
    stale = datetime.utcnow() - last_automation > timedelta(
        minutes=max(settings.automation_scan_interval_minutes * 3, 180)
    )
    return _indicator(
        "notifications",
        DEGRADED if stale else OK,
        (
            "The notification automation engine has not run recently."
            if stale
            else "The notification automation engine is running on schedule."
        ),
        notifications_24h=created,
        last_automation_run_at=last_automation,
    )


def ingestion_health(db: Session) -> dict:
    """Top-level ingestion indicator. Per-source detail is in
    ``ingestion_sources`` below."""
    if not settings.ingestion_enabled:
        return _indicator(
            "ingestion",
            UNKNOWN,
            "Automated ingestion is disabled for this deployment (INGESTION_ENABLED=false). "
            "No source is being collected on a schedule.",
            enabled=False,
        )
    try:
        last_run = db.scalar(select(func.max(IngestionRun.started_at)))
        failed = (
            db.scalar(
                select(func.count())
                .select_from(IngestionRun)
                .where(
                    IngestionRun.status == "failed",
                    IngestionRun.started_at >= datetime.utcnow() - timedelta(hours=24),
                )
            )
            or 0
        )
    except Exception:
        log.warning("Ingestion health query failed", exc_info=True)
        return _indicator("ingestion", UNKNOWN, "Could not read ingestion runs.")

    if last_run is None:
        return _indicator("ingestion", UNKNOWN, "Ingestion is enabled but has never run.", enabled=True)
    return _indicator(
        "ingestion",
        DEGRADED if failed else OK,
        (f"{failed} ingestion run(s) failed in the last 24 hours." if failed else "Recent ingestion runs succeeded."),
        enabled=True,
        last_run_at=last_run,
        failed_24h=failed,
    )


def api_health() -> dict:
    """The API is by definition reachable if this code is executing;
    reported for completeness alongside the other indicators rather
    than as a meaningful test."""
    return _indicator(
        "api",
        OK,
        "The API process served this request.",
        environment=settings.environment,
    )


def system_health(db: Session) -> dict:
    """Every indicator, plus a rolled-up overall status.

    The roll-up counts only real problems: "unknown" indicators do not
    degrade the overall status, because an unconfigured optional
    provider is not an outage.
    """
    indicators = [
        api_health(),
        database_health(db),
        migration_health(db),
        scheduler_health(),
        email_health(db),
        ai_provider_health(db),
        notification_health(db),
        ingestion_health(db),
    ]
    if any(i["status"] == ERROR for i in indicators):
        overall = ERROR
    elif any(i["status"] == DEGRADED for i in indicators):
        overall = DEGRADED
    else:
        overall = OK
    return {
        "status": overall,
        "checked_at": datetime.utcnow(),
        "indicators": indicators,
    }


# ---------------------------------------------------------------------------
# Background jobs (spec section 17)
# ---------------------------------------------------------------------------


def background_jobs(db: Session) -> dict:
    """Queue-style state for the two things in CareerOS that actually
    have queue semantics: the V23.2 email queue (durable, with
    attempts/retries/last error) and the APScheduler jobs.

    CareerOS has no Celery/RQ/Sidekiq broker, so there is no
    "running jobs" count to report for scheduled jobs and none is
    invented — the scheduler entry reports last-run state, which is
    what it genuinely knows. Section 17 is explicit: only report
    states the existing infrastructure provides.

    No endpoint anywhere lets an administrator execute an arbitrary
    job. The only action offered is re-queueing a FAILED email, which
    is safe precisely because the email sender is already idempotent
    per ``EmailMessage`` row (it transitions QUEUED -> SENT once and
    the row's ``dedupe_key`` prevents a duplicate ever being created).
    """
    try:
        rows = db.execute(
            select(EmailMessage.status, func.count()).group_by(EmailMessage.status)
        ).all()
        by_status = {status: count for status, count in rows}
        retrying = (
            db.scalar(
                select(func.count())
                .select_from(EmailMessage)
                .where(EmailMessage.status == "QUEUED", EmailMessage.attempts > 0)
            )
            or 0
        )
        last_sent = db.scalar(select(func.max(EmailMessage.sent_at)))
        last_failed = db.scalar(select(func.max(EmailMessage.failed_at)))
    except Exception:
        log.warning("Background job query failed", exc_info=True)
        return {"queues": [], "scheduler": scheduler_health(), "available": False}

    email_queue = {
        "name": "email",
        "description": "V23.2 durable outbound email queue.",
        "queued": by_status.get("QUEUED", 0),
        "sent": by_status.get("SENT", 0),
        "failed": by_status.get("FAILED", 0),
        "retrying": retrying,
        "max_attempts": settings.email_max_retry_attempts,
        "last_success_at": last_sent,
        "last_failure_at": last_failed,
        "retryable": True,
    }
    return {"queues": [email_queue], "scheduler": scheduler_health(), "available": True}


def failed_email_ids(db: Session, limit: int = 100) -> list[int]:
    return list(
        db.scalars(
            select(EmailMessage.id)
            .where(EmailMessage.status == "FAILED")
            .order_by(EmailMessage.id.desc())
            .limit(limit)
        ).all()
    )


# ---------------------------------------------------------------------------
# Ingestion monitoring (spec section 18)
# ---------------------------------------------------------------------------


def ingestion_sources(db: Session) -> dict:
    """Per-source ingestion visibility.

    Everything here is read from ``SourceRegistry`` (the V19.1/V19.2
    standing catalog) and ``IngestionRun`` (the V2 per-run log). The
    ``enabled`` flag reported for each source is the source's ACTUAL
    configured state, combined with the deployment-wide
    ``INGESTION_ENABLED`` switch — a source marked "active" in the
    registry while ingestion is globally off is reported as not
    currently collecting, because it isn't. Section 18 is explicit
    that an administrator must not be able to claim a source is live
    when it is not.

    No government job data is synthesized anywhere in this function:
    ``imported`` counts are sums of ``IngestionRun.created``, which
    are written only by real runs.
    """
    globally_enabled = settings.ingestion_enabled
    try:
        registry_rows = db.scalars(select(SourceRegistry).order_by(SourceRegistry.source_name)).all()
    except Exception:
        log.warning("Source registry query failed", exc_info=True)
        return {"globally_enabled": globally_enabled, "sources": [], "available": False}

    sources = []
    for row in registry_rows:
        try:
            totals = db.execute(
                select(
                    func.coalesce(func.sum(IngestionRun.created), 0),
                    func.coalesce(func.sum(IngestionRun.skipped), 0),
                    func.coalesce(func.sum(IngestionRun.discovered), 0),
                    func.count(),
                ).where(IngestionRun.source_name == row.source_name)
            ).one()
            imported, skipped, discovered, run_count = totals
            dead_letters = (
                db.scalar(
                    select(func.count())
                    .select_from(IngestionDeadLetter)
                    .where(IngestionDeadLetter.source_name == row.source_name, IngestionDeadLetter.resolved.is_(False))
                )
                or 0
            )
        except Exception:
            imported = skipped = discovered = run_count = dead_letters = 0

        sources.append(
            {
                "source_name": row.source_name,
                "collector_type": row.collector_type,
                "registry_status": row.status,
                # The honest, combined answer to "is this collecting?"
                "currently_collecting": bool(globally_enabled and row.status == "active"),
                "schedule": row.schedule,
                "last_run_at": row.last_run_at,
                "last_success_at": row.last_success_at,
                "last_failure_at": row.last_failure_at,
                "error_count": row.error_count,
                "consecutive_failures": row.consecutive_failures,
                "circuit_state": row.circuit_state,
                "availability_pct": row.availability_pct,
                "last_latency_ms": row.last_latency_ms,
                "run_count": run_count,
                "jobs_imported": imported,
                # "skipped" is the existing pipeline's count of records
                # that were discovered but not created — overwhelmingly
                # duplicates of an already-ingested posting. Reported
                # under its real name rather than relabelled
                # "duplicates", which would assert more than the data
                # supports.
                "records_skipped": skipped,
                "records_discovered": discovered,
                "unresolved_dead_letters": dead_letters,
            }
        )

    return {
        "globally_enabled": globally_enabled,
        "note": (
            "Automated ingestion is disabled for this deployment; no source is collecting on a schedule."
            if not globally_enabled
            else None
        ),
        "sources": sources,
        "available": True,
    }
