"""V23.3 — Smart Job Alerts execution pipeline.

    Job ingestion -> New/updated job -> [handled by real-time search
    indexing, app.search.hooks — already exists, not duplicated here]
       -> Alert matching -> Relevance filtering -> Deduplication
       -> Notification event -> In-app notification / Email queue

Reuses, rather than reimplements, every piece of that pipeline spec
section 9 asks for:
  - matching/relevance: app.job_alerts.matching (V21 search/recommendations)
  - notification event: app.notifications.service.create_notification,
    the same table/dedupe_key mechanism every other V23.1 event uses
  - email queue: app.email.service.queue_email, the same QUEUED-row +
    background-worker delivery V23.2 already built — this module
    NEVER calls an SMTP provider directly (spec section 9: "Do not
    tightly couple job ingestion directly to SMTP")

CONCURRENCY (spec section 22): a worker restart or two overlapping
runs of the same alert must not double-notify. Two independent,
compounding safeguards:
  1. JobAlertDelivery's UNIQUE(job_alert_id, job_id, channel) —
     enforced at the DB layer, so a race between two processes is
     resolved by the database, not by application-level locking.
  2. Notification.dedupe_key / EmailMessage.dedupe_key (V23.1/V23.2's
     own idempotency keys) as defense in depth underneath (1).
No SELECT ... FOR UPDATE row lock is taken on JobAlert itself — with
(1)+(2) already making a duplicate *delivery* structurally impossible,
a lock would only prevent two processes from doing redundant (but
harmless) matching work concurrently, which is an efficiency question,
not a correctness one, and this codebase's Postgres/SQLite dual
support makes a portable advisory-lock story more complexity than that
efficiency question currently justifies — see docs/V23_3_SMART_JOB_ALERTS.md
"Known limitations".
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.email import service as email_service
from app.email.templates import DIGEST_TOP_N
from app.job_alerts import matching
from app.models.domain import Job, JobAlert, JobAlertDelivery, JobAlertRun, User, UserNotificationPreference
from app.notifications import service as notification_service

logger = logging.getLogger("careeros.job_alerts")

_DIGEST_TEMPLATE = {"DAILY": "JOB_ALERT_DAILY", "WEEKLY": "JOB_ALERT_WEEKLY"}
_FREQUENCY_WINDOW = {"DAILY": timedelta(days=1), "WEEKLY": timedelta(days=7)}


def _in_app_enabled_for_job(db: Session, user_id: int) -> bool:
    """Mirrors app.email.preferences.should_send_email's shape for the
    in-app channel (spec section 13: "Respect: JOB in-app preference").
    NOTE: app.notifications.service.create_notification itself does not
    gate on UserNotificationPreference for any category (a pre-existing
    V23.1 gap — notify_job/notify_application/etc. are stored and
    settable via the API but not yet read anywhere) — see
    docs/V23_3_SMART_JOB_ALERTS.md "Known limitations". Rather than
    changing that shared function's behavior for every existing V23.1
    event (out of scope here and a real regression risk), this alert
    pipeline checks the flag itself before calling it, so job alerts at
    least honor their own spec requirement.
    """
    pref = db.get(UserNotificationPreference, user_id)
    if pref is None:
        return True
    if not pref.in_app_enabled:
        return False
    return bool(pref.notify_job)


def _delivered_job_ids(db: Session, alert_id: int, channel: str) -> set[int]:
    return set(
        db.scalars(
            select(JobAlertDelivery.job_id).where(
                JobAlertDelivery.job_alert_id == alert_id, JobAlertDelivery.channel == channel
            )
        ).all()
    )


def _record_delivery(db: Session, *, alert: JobAlert, job_id: int, channel: str, score: int) -> bool:
    """Best-effort insert of the durable dedup record — see module
    docstring's CONCURRENCY note. Returns False (never raises) if this
    exact (alert, job, channel) was already recorded, including by a
    concurrent worker that won the race."""
    db.add(
        JobAlertDelivery(
            job_alert_id=alert.id, job_id=job_id, user_id=alert.user_id, channel=channel, relevance_score=score
        )
    )
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _notify_in_app(db: Session, alert: JobAlert, user: User, job: Job, candidate: matching.MatchCandidate) -> bool:
    if not _in_app_enabled_for_job(db, user.id):
        return False
    record = notification_service.create_notification(
        db,
        user.id,
        notification_type="job_alert_match",
        category="JOB",
        priority="NORMAL",
        title=f"New match: {job.title}",
        message=f"{job.title} at {job.organization} matches your alert \"{alert.name}\". "
        + candidate.match_reasons[0],
        action_url=f"/jobs/{job.id}",
        job_id=job.id,
        metadata={"job_alert_id": alert.id, "relevance_score": candidate.relevance_score, "reasons": candidate.match_reasons},
        dedupe_key=f"job_alert_match:{alert.id}:{job.id}",
    )
    return record is not None


def _queue_instant_email(db: Session, alert: JobAlert, user: User, job: Job, candidate: matching.MatchCandidate) -> bool:
    message = email_service.queue_email(
        db,
        user_id=user.id,
        recipient=user.email,
        template_key="JOB_ALERT_INSTANT",
        variables={
            "user_name": user.full_name or "there",
            "alert_name": alert.name,
            "job_title": job.title,
            "company_name": job.organization,
            "job_location": job.location or "Not specified",
            "match_reason": candidate.match_reasons[0],
            "action_url": f"/jobs/{job.id}",
        },
        category="JOB",
        dedupe_key=f"job_alert_instant:{alert.id}:{job.id}",
    )
    return message is not None


def _queue_digest_email(
    db: Session, alert: JobAlert, user: User, run: JobAlertRun, jobs_by_id: dict[int, Job], candidates: list[matching.MatchCandidate]
) -> bool:
    template_key = _DIGEST_TEMPLATE[alert.frequency]
    top = candidates[:DIGEST_TOP_N]
    variables: dict[str, str] = {
        "user_name": user.full_name or "there",
        "alert_name": alert.name,
        "match_count": str(len(candidates)),
        "action_url": "/job-alerts",
    }
    for i in range(1, DIGEST_TOP_N + 1):
        c = top[i - 1] if i <= len(top) else None
        job = jobs_by_id.get(c.job_id) if c else None
        variables[f"job_{i}_title"] = job.title if job else ""
        variables[f"job_{i}_company"] = job.organization if job else ""
        variables[f"job_{i}_location"] = (job.location or "Not specified") if job else ""
        variables[f"job_{i}_reason"] = c.match_reasons[0] if c else ""
    remaining = len(candidates) - len(top)
    variables["more_count_text"] = f"and {remaining} more matching job(s) — view them all in CareerOS." if remaining > 0 else ""

    message = email_service.queue_email(
        db,
        user_id=user.id,
        recipient=user.email,
        template_key=template_key,
        variables=variables,
        category="JOB",
        dedupe_key=f"job_alert_digest:{alert.id}:{run.id}",
    )
    return message is not None


def run_alert(db: Session, alert: JobAlert) -> JobAlertRun:
    """Executes exactly one alert end to end. Never raises — a failure
    is recorded on the JobAlertRun and on the alert's own
    last_run_status, matching every other scheduled-job's failure
    isolation in this codebase (see app.scheduler._with_retry and
    app.notifications.events's failure-isolation docstring) — one
    broken alert must never take down a batch run of many alerts."""
    run = JobAlertRun(job_alert_id=alert.id, user_id=alert.user_id, status="RUNNING")
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        user = db.get(User, alert.user_id)
        if user is None or not user.active:
            raise ValueError(f"Alert owner user_id={alert.user_id} not found or inactive")

        # First run (last_run_at is None): no "since" bound at all — a
        # freshly created alert should surface every currently-matching
        # job, including ones that already existed before the alert
        # was created (they're genuinely new *to this alert*, which is
        # spec section 10's actual test — "new to the user/alert," not
        # "created after the alert row"). JobAlertDelivery's dedup
        # table is what actually prevents re-notification on every
        # later run (see module docstring); the since-filter below is
        # purely a performance narrowing for those later runs, not a
        # correctness mechanism, so it would be actively wrong to apply
        # it on the one run where there's no prior delivery history yet.
        since = alert.last_run_at
        candidates, scanned = matching.find_matches(db, alert, user, since=since)

        already_in_app = _delivered_job_ids(db, alert.id, "IN_APP")
        already_email = _delivered_job_ids(db, alert.id, "EMAIL")

        new_for_in_app = [c for c in candidates if c.job_id not in already_in_app]
        new_for_email = [c for c in candidates if c.job_id not in already_email]

        jobs_by_id: dict[int, Job] = {}
        for c in candidates:
            if c.job_id not in jobs_by_id:
                job = db.get(Job, c.job_id)
                if job is not None:
                    jobs_by_id[c.job_id] = job

        notifications_created = 0
        for c in new_for_in_app:
            job = jobs_by_id.get(c.job_id)
            if job is None:
                continue
            if _notify_in_app(db, alert, user, job, c):
                notifications_created += 1
            _record_delivery(db, alert=alert, job_id=c.job_id, channel="IN_APP", score=c.relevance_score)

        emails_queued = 0
        if alert.frequency == "INSTANT":
            for c in new_for_email:
                job = jobs_by_id.get(c.job_id)
                if job is None:
                    continue
                if _queue_instant_email(db, alert, user, job, c):
                    emails_queued += 1
                _record_delivery(db, alert=alert, job_id=c.job_id, channel="EMAIL", score=c.relevance_score)
        elif new_for_email:
            # DAILY/WEEKLY — one digest email covering every newly
            # matched, not-yet-emailed job (spec section 11: "Do not
            # send one email per job for digest alerts").
            if _queue_digest_email(db, alert, user, run, jobs_by_id, new_for_email):
                emails_queued += 1
            for c in new_for_email:
                _record_delivery(db, alert=alert, job_id=c.job_id, channel="EMAIL", score=c.relevance_score)

        now = datetime.utcnow()
        alert.last_run_at = now
        alert.last_run_status = "SUCCESS"
        alert.last_match_count = len(candidates)

        run.completed_at = now
        run.status = "SUCCESS"
        run.candidates_scanned = scanned
        run.jobs_matched = len(candidates)
        run.notifications_created = notifications_created
        run.emails_queued = emails_queued
        db.commit()
        logger.info(
            "Job alert %s run complete: scanned=%s matched=%s notifications=%s emails=%s",
            alert.id, scanned, len(candidates), notifications_created, emails_queued,
        )
    except Exception as exc:  # noqa: BLE001 — one alert's failure must never abort the batch
        db.rollback()
        error_summary = str(exc)[:500]
        logger.error("Job alert %s run failed: %s", alert.id, error_summary, exc_info=True)
        # Re-fetch — the rollback above discarded any in-memory changes
        # to `run`/`alert` from the try block.
        run = db.get(JobAlertRun, run.id) or run
        run.status = "FAILED"
        run.completed_at = datetime.utcnow()
        run.error_summary = error_summary
        alert_row = db.get(JobAlert, alert.id)
        if alert_row is not None:
            alert_row.last_run_status = "FAILED"
        db.commit()

    return run


def due_alerts(db: Session, now: datetime | None = None) -> list[JobAlert]:
    """Alerts due for a scheduled run right now, per spec section 3's
    frequency semantics: INSTANT alerts are always "due" (a run is a
    cheap, idempotent no-op if nothing new matches — see find_matches'
    since-filter) and are picked up on every scheduler tick; DAILY/
    WEEKLY are due once their window has elapsed since last_run_at."""
    now = now or datetime.utcnow()
    alerts = db.scalars(select(JobAlert).where(JobAlert.enabled == True)).all()  # noqa: E712
    due: list[JobAlert] = []
    for alert in alerts:
        if alert.frequency == "INSTANT":
            due.append(alert)
            continue
        window = _FREQUENCY_WINDOW.get(alert.frequency)
        if window is None:
            continue  # unknown/future frequency — never auto-run until explicitly supported (see spec section 3)
        if alert.last_run_at is None or now - alert.last_run_at >= window:
            due.append(alert)
    return due


def run_due_alerts(db: Session, now: datetime | None = None) -> dict:
    """The scheduler entry point (app.scheduler's careeros_job_alerts
    job) — sequential, in-process, same shape as every other scheduled
    scan in this codebase (app.services.notifications.scan_and_notify,
    app.ingestion.scheduler.run_due_sources)."""
    alerts = due_alerts(db, now)
    runs = [run_alert(db, alert) for alert in alerts]
    return {
        "alerts_due": len(alerts),
        "alerts_succeeded": sum(1 for r in runs if r.status == "SUCCESS"),
        "alerts_failed": sum(1 for r in runs if r.status == "FAILED"),
        "total_jobs_matched": sum(r.jobs_matched for r in runs),
        "total_notifications_created": sum(r.notifications_created for r in runs),
        "total_emails_queued": sum(r.emails_queued for r in runs),
    }
