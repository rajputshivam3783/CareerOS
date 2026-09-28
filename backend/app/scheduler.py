"""Background scheduler — V2 automated collection + V7 notification scans.

Uses APScheduler's in-process background scheduler rather than an
external cron so `docker compose up` alone gives you a fully working
pipeline.

IMPORTANT — multi-worker/multi-replica deployments: APScheduler's
BackgroundScheduler runs inside whichever process starts it, with no
awareness of other workers. If more than one process calls
start_scheduler() (e.g. `--workers 2`, or multiple container
replicas), every process runs its own copy of every scheduled job —
duplicating outbound ingestion requests, and creating a real race
condition for notifications (two processes can both pass the
"already notified?" check before either commits its insert). Guard
against this with settings.scheduler_enabled: leave it true on
exactly one worker/replica and set it false everywhere else (see
backend/Dockerfile and docker-compose.production.yml).
"""

import logging
import time
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.ingest import run_all_enabled_sources
from app.services.notifications import scan_and_notify

logger = logging.getLogger("careeros.scheduler")

_scheduler: BackgroundScheduler | None = None

# V19.4 — last-run bookkeeping for the admin "Health Monitoring"
# requirement (see GET /admin/automation/health in
# app/api/notification_engine.py). Intentionally process-local, same
# scope as `_scheduler` itself — this is a monitoring convenience, not
# a durable record (AutomationLog/NotificationDeliveryLog already are
# the durable ones).
job_health: dict[str, dict] = {}


def _record_health(job_id: str, ok: bool, detail: str | None = None) -> None:
    job_health[job_id] = {"last_run_at": datetime.now(timezone.utc).isoformat(), "ok": ok, "detail": detail}


def _with_retry(job_id: str, fn, *, retries: int = 3, backoff_seconds: int = 5):
    """V19.4 — Retry + backoff for scheduled jobs. Every job in this
    module already opens/closes its own DB session and commits inside
    the called function, so a retry here is a clean re-attempt of the
    whole unit of work, not a partial one. Exponential backoff
    (backoff_seconds, 2x, 4x, ...) between attempts; the last failure
    is logged and recorded in `job_health` rather than raised, so one
    bad run never crashes the scheduler thread.

    V25.5 — in addition to the in-memory `job_health` entry (which
    only ever holds this job's *last* run), a failure/recovery is now
    also recorded durably via app.reliability.dead_letter so it
    survives a process restart and shows up on GET
    /admin/observability. This is purely additive bookkeeping in its
    own session — a failure while recording it is logged and
    swallowed (see dead_letter.record_failure), never allowed to mask
    the real job outcome computed above.
    """
    from app.db.session import SessionLocal
    from app.reliability import dead_letter

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            result = fn()
            _record_health(job_id, ok=True, detail=str(result) if result is not None else None)
            if attempt > 1:
                # Recovered after at least one prior failure this run.
                _db = SessionLocal()
                try:
                    dead_letter.record_recovery(_db, job_name=job_id)
                finally:
                    _db.close()
            return result
        except Exception as exc:  # noqa: BLE001 — deliberately broad: any failure should retry, not crash the scheduler
            last_error = exc
            logger.warning("%s attempt %s/%s failed: %s", job_id, attempt, retries, exc)
            _db = SessionLocal()
            try:
                dead_letter.record_failure(
                    _db,
                    job_name=job_id,
                    error=str(exc),
                    retries_exhausted=(attempt == retries),
                    backoff_seconds=backoff_seconds * (2**attempt),
                )
            finally:
                _db.close()
            if attempt < retries:
                time.sleep(backoff_seconds * (2 ** (attempt - 1)))
    logger.exception("%s failed after %s attempts", job_id, retries, exc_info=last_error)
    _record_health(job_id, ok=False, detail=str(last_error))
    return None


def _run_ingestion_job() -> None:
    db = SessionLocal()
    try:
        results = run_all_enabled_sources(db)
        logger.info("Scheduled ingestion run complete: %s", results)
        return results
    finally:
        db.close()


def _run_registry_ingestion_job():
    """V25.7 — run every DB-registered source (source_registry.status='active')
    that is due per its schedule, then backfill details for review-queue
    jobs that still only have a title + link."""
    from app.ingestion.scheduler import run_due_sources
    from app.ingestion.services.enrichment import enrich_pending_jobs

    db = SessionLocal()
    try:
        results = run_due_sources(db)
        backfill = enrich_pending_jobs(db, limit=30) if settings.ingestion_enrich_details else {}
        logger.info("Registry ingestion complete: %s | backfill: %s", results, backfill)
        return {"runs": results, "backfill": backfill}
    finally:
        db.close()


def _run_notification_job() -> None:
    db = SessionLocal()
    try:
        result = scan_and_notify(db)
        logger.info("Scheduled notification scan complete: %s", result)
        return result
    finally:
        db.close()


def _run_automation_job() -> None:
    """V19.4 — subscription/lifecycle-event fan-out (see
    app/services/automation.py) plus firing any reminders due today.
    Reminder *creation* (sync_auto_reminders) runs separately on its
    own, less frequent interval — see _run_reminder_sync_job."""
    from app.services.automation import run_automation_scan
    from app.services.reminder_engine import fire_due_reminders

    db = SessionLocal()
    try:
        automation_result = run_automation_scan(db)
        fired = fire_due_reminders(db)
        result = {**automation_result, "reminders_fired": fired}
        logger.info("Scheduled automation run complete: %s", result)
        return result
    finally:
        db.close()


def _run_reminder_sync_job() -> None:
    """V19.4 — creates new ReminderRule rows for any newly-relevant
    date (deadline/exam_date/etc. just set on a job an interested user
    already saved/applied to)."""
    from app.services.reminder_engine import sync_auto_reminders

    db = SessionLocal()
    try:
        created = sync_auto_reminders(db)
        logger.info("Scheduled reminder sync complete: %s reminders created", created)
        return {"reminders_created": created}
    finally:
        db.close()


def _run_search_reindex_job() -> None:
    """V21.1 — periodic full reindex of search_index_documents. See
    app/search/indexer.py's module docstring for why this is
    scheduled rather than wired into every entity write path."""
    from app.search.indexer import reindex_all

    db = SessionLocal()
    try:
        results = reindex_all(db)
        summary = {r.entity_type: {"indexed": r.indexed, "errors": r.errors} for r in results}
        logger.info("Scheduled search reindex complete: %s", summary)
        return summary
    finally:
        db.close()


def _run_email_queue_job() -> None:
    """V23.2 — processes due QUEUED/RETRYING EmailMessage rows (see
    app/email/service.py::process_queue). Deliberately the same
    "local DB + outbound-only" job shape as every other scheduled job
    here — an SMTP attempt that hangs is bounded by smtplib's own
    15s timeout (app/email/provider.py), not by this scheduler."""
    from app.email.service import process_queue

    db = SessionLocal()
    try:
        result = process_queue(db)
        logger.info("Scheduled email queue run complete: %s", result)
        return result
    finally:
        db.close()


def _run_job_alerts_job() -> None:
    """V23.3 — Smart Job Alerts: runs every due alert (INSTANT alerts
    on every tick — cheap/idempotent no-op if nothing new matches;
    DAILY/WEEKLY once their window has elapsed). See
    app.job_alerts.execution.run_due_alerts."""
    from app.job_alerts.execution import run_due_alerts

    db = SessionLocal()
    try:
        result = run_due_alerts(db)
        logger.info("Scheduled job alerts run complete: %s", result)
        return result
    finally:
        db.close()


def _run_communication_reminders_job() -> None:
    """V23.4 — Communication Center: scans interviews/deadlines/tasks
    for newly-due reminders and promotes any quiet-hours-delayed ones.
    See app.communication.reminders.run_due_reminders."""
    from app.communication.reminders import run_due_reminders

    db = SessionLocal()
    try:
        result = run_due_reminders(db)
        logger.info("Scheduled communication reminder scan complete: %s", result)
        return result
    finally:
        db.close()


def _run_daily_digest_job() -> None:
    """V23.4 — Communication Center: queues the opt-in daily digest
    email for every eligible user. See
    app.communication.digest.run_daily_digest."""
    from app.communication.digest import run_daily_digest

    db = SessionLocal()
    try:
        result = run_daily_digest(db)
        logger.info("Scheduled daily digest run complete: %s", result)
        return result
    finally:
        db.close()


def run_job_now(job_id: str) -> dict:
    """V19.4 — Manual Run for a single scheduled job, by id, from the
    admin UI (distinct from POST /admin/automation/run, which always
    runs the automation+reminder pair together synchronously). Reuses
    the exact same retry-wrapped functions the scheduler itself calls,
    so a manual run behaves identically to a scheduled one."""
    jobs = {
        "careeros_notifications": lambda: _with_retry("careeros_notifications", _run_notification_job),
        "careeros_ingestion": lambda: _with_retry("careeros_ingestion", _run_ingestion_job),
        "careeros_registry_ingestion": lambda: _with_retry("careeros_registry_ingestion", _run_registry_ingestion_job),
        "careeros_automation": lambda: _with_retry("careeros_automation", _run_automation_job),
        "careeros_reminder_sync": lambda: _with_retry("careeros_reminder_sync", _run_reminder_sync_job),
        "careeros_search_reindex": lambda: _with_retry("careeros_search_reindex", _run_search_reindex_job),
        "careeros_email_queue": lambda: _with_retry("careeros_email_queue", _run_email_queue_job),
        "careeros_job_alerts": lambda: _with_retry("careeros_job_alerts", _run_job_alerts_job),
        "careeros_communication_reminders": lambda: _with_retry("careeros_communication_reminders", _run_communication_reminders_job),
        "careeros_daily_digest": lambda: _with_retry("careeros_daily_digest", _run_daily_digest_job),
    }
    if job_id not in jobs:
        raise ValueError(f"Unknown job_id {job_id!r}. Known jobs: {sorted(jobs)}")
    return {"job_id": job_id, "result": jobs[job_id]()}


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    if not settings.scheduler_enabled:
        logger.info(
            "scheduler_enabled=false — not starting the background scheduler on this "
            "worker (expected on every worker/replica except your one designated "
            "scheduler instance)"
        )
        return

    _scheduler = BackgroundScheduler(timezone="UTC")

    # V7 — reads the local DB only (no outbound network calls), so it's
    # safe to run unconditionally (once scheduler_enabled has already
    # gated which single worker reaches this point at all). V19.4 wraps
    # it in _with_retry so a transient failure (e.g. a momentary DB
    # connection blip) gets retried with backoff instead of silently
    # skipping that interval.
    _scheduler.add_job(
        lambda: _with_retry("careeros_notifications", _run_notification_job),
        "interval",
        minutes=settings.notification_scan_interval_minutes,
        id="careeros_notifications",
        next_run_time=datetime.now(timezone.utc),
        misfire_grace_time=300,
    )
    logger.info(
        "Notification scan scheduled — every %s minutes", settings.notification_scan_interval_minutes
    )

    # V19.4 — Automation engine (subscriptions + lifecycle-event fan-out
    # + firing due reminders) and the separate, less-frequent reminder
    # sync (creating new ReminderRule rows). Same "local DB only" safety
    # as the notification scan above.
    _scheduler.add_job(
        lambda: _with_retry("careeros_automation", _run_automation_job),
        "interval",
        minutes=settings.automation_scan_interval_minutes,
        id="careeros_automation",
        next_run_time=datetime.now(timezone.utc),
        misfire_grace_time=300,
    )
    logger.info("Automation scan scheduled — every %s minutes", settings.automation_scan_interval_minutes)

    _scheduler.add_job(
        lambda: _with_retry("careeros_reminder_sync", _run_reminder_sync_job),
        "interval",
        minutes=settings.reminder_sync_interval_minutes,
        id="careeros_reminder_sync",
        next_run_time=datetime.now(timezone.utc),
        misfire_grace_time=600,
    )
    logger.info("Reminder sync scheduled — every %s minutes", settings.reminder_sync_interval_minutes)

    # V2 — off by default; see app/ingestion/sources.py.
    if settings.ingestion_enabled:
        _scheduler.add_job(
            lambda: _with_retry("careeros_ingestion", _run_ingestion_job),
            "interval",
            minutes=settings.ingestion_interval_minutes,
            id="careeros_ingestion",
            next_run_time=datetime.now(timezone.utc),
            misfire_grace_time=300,
        )
        logger.info("Ingestion scheduled — every %s minutes", settings.ingestion_interval_minutes)
    else:
        logger.info("Automated ingestion is disabled (ingestion_enabled=false) — not scheduling it")

    # V25.7 — DB-registered government sources (source_registry). Off by default.
    if settings.ingestion_registry_enabled:
        _scheduler.add_job(
            lambda: _with_retry("careeros_registry_ingestion", _run_registry_ingestion_job),
            "interval",
            minutes=settings.ingestion_registry_interval_minutes,
            id="careeros_registry_ingestion",
            next_run_time=datetime.now(timezone.utc),
            misfire_grace_time=300,
        )
        logger.info("Registry ingestion scheduled — every %s minutes", settings.ingestion_registry_interval_minutes)
    else:
        logger.info("Registry ingestion disabled (ingestion_registry_enabled=false)")

    # V21.1 — Unified Search Infrastructure: periodic full reindex.
    _scheduler.add_job(
        lambda: _with_retry("careeros_search_reindex", _run_search_reindex_job),
        "interval",
        minutes=settings.search_reindex_interval_minutes,
        id="careeros_search_reindex",
        next_run_time=datetime.now(timezone.utc),
        misfire_grace_time=300,
    )
    logger.info("Search reindex scheduled — every %s minutes", settings.search_reindex_interval_minutes)

    # V23.2 — email queue: sends whatever app.email.service.queue_email
    # has queued (notification-triggered emails), and retries anything
    # in RETRYING whose backoff window has elapsed. Short interval and
    # generous misfire grace since a delayed email is much better than
    # a lost one.
    _scheduler.add_job(
        lambda: _with_retry("careeros_email_queue", _run_email_queue_job),
        "interval",
        minutes=settings.email_queue_interval_minutes,
        id="careeros_email_queue",
        next_run_time=datetime.now(timezone.utc),
        misfire_grace_time=300,
    )
    logger.info("Email queue processing scheduled — every %s minutes", settings.email_queue_interval_minutes)

    # V23.3 — Smart Job Alerts. Short interval since this is also how
    # INSTANT alerts get their "instant" behavior — the job itself is
    # cheap on a quiet interval (find_matches' since-filter means a
    # tick with nothing new to alert on is a fast no-op per alert).
    _scheduler.add_job(
        lambda: _with_retry("careeros_job_alerts", _run_job_alerts_job),
        "interval",
        minutes=settings.job_alerts_interval_minutes,
        id="careeros_job_alerts",
        next_run_time=datetime.now(timezone.utc),
        misfire_grace_time=300,
    )
    logger.info("Job alerts scheduled — every %s minutes", settings.job_alerts_interval_minutes)

    # V23.4 — Communication Center: interview/deadline/task reminders.
    # More frequent than the job-alerts scan since a 1-hour-before
    # interview reminder loses most of its value if it fires late.
    _scheduler.add_job(
        lambda: _with_retry("careeros_communication_reminders", _run_communication_reminders_job),
        "interval",
        minutes=settings.communication_reminder_interval_minutes,
        id="careeros_communication_reminders",
        next_run_time=datetime.now(timezone.utc),
        misfire_grace_time=300,
    )
    logger.info(
        "Communication reminder scan scheduled — every %s minutes", settings.communication_reminder_interval_minutes
    )

    # V23.4 — daily digest. Coarser interval; DAILY_CAREER_DIGEST's own
    # per-user-per-day dedupe_key (app.communication.digest) makes an
    # extra tick within the same day a harmless no-op.
    _scheduler.add_job(
        lambda: _with_retry("careeros_daily_digest", _run_daily_digest_job),
        "interval",
        minutes=settings.communication_digest_interval_minutes,
        id="careeros_daily_digest",
        next_run_time=datetime.now(timezone.utc),
        misfire_grace_time=600,
    )
    logger.info("Daily digest scheduled — every %s minutes", settings.communication_digest_interval_minutes)

    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
