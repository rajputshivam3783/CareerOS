"""V7 Application OS — deadline, admit-card, and result notifications.

Delivery is in-app only. This project has no verified, working
email/SMS provider wired up, and a notification claiming to have been
texted/emailed when nothing was actually sent would be a worse failure
than a plain in-app inbox — so that's the honest scope for now. See
the "Upgrade path" note at the bottom for wiring in a real channel
later without changing this module's logic.

Runs on the existing background scheduler (see app/scheduler.py) so
there's one background-job mechanism in the project, not two.
"""

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.domain import Alert, Application, Job, Notification, SavedJob

logger = logging.getLogger("careeros.notifications")


def _interested_user_ids(db: Session, job_id: int) -> set[int]:
    saved = db.scalars(select(SavedJob.user_id).where(SavedJob.job_id == job_id)).all()
    applied = db.scalars(select(Application.user_id).where(Application.job_id == job_id)).all()
    return set(saved) | set(applied)


def _already_notified(db: Session, user_id: int, job_id: int, notification_type: str) -> bool:
    return (
        db.scalar(
            select(Notification.id).where(
                Notification.user_id == user_id,
                Notification.job_id == job_id,
                Notification.notification_type == notification_type,
            )
        )
        is not None
    )


def _notify_once(db: Session, user_id: int, job: Job, notification_type: str, title: str, message: str) -> bool:
    """Insert a notification unless this user already has one of this
    type for this job. Returns True if a new notification was created."""
    if _already_notified(db, user_id, job.id, notification_type):
        return False
    db.add(
        Notification(
            user_id=user_id,
            job_id=job.id,
            notification_type=notification_type,
            title=title,
            message=message,
        )
    )
    return True


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _check_saved_search_alerts(db: Session) -> int:
    """For every enabled "job" alert, notify its owner about jobs
    published since the alert was last checked that match the saved
    search term (same title/organization/description/qualification
    match used by GET /jobs). Advances each alert's watermark
    regardless of whether anything matched, so a quiet period doesn't
    cause a flood later."""
    now = datetime.utcnow()
    created = 0

    alerts = db.scalars(
        select(Alert).where(Alert.enabled == True, Alert.alert_type == "job")  # noqa: E712
    ).all()

    for alert in alerts:
        since = alert.last_checked_at or alert.created_at
        query = select(Job).where(Job.status == "published", Job.created_at > since)

        if alert.query and alert.query.strip():
            term = f"%{_escape_like(alert.query.strip())}%"
            query = query.where(
                or_(
                    Job.title.ilike(term, escape="\\"),
                    Job.organization.ilike(term, escape="\\"),
                    Job.description.ilike(term, escape="\\"),
                    Job.qualification.ilike(term, escape="\\"),
                )
            )

        for job in db.scalars(query).all():
            if _notify_once(
                db,
                alert.user_id,
                job,
                "alert_match",
                f"New match for your alert: {job.title}",
                f"{job.title} at {job.organization} was just published and matches your saved alert"
                + (f' "{alert.query}"' if alert.query else "") + ".",
            ):
                created += 1

        alert.last_checked_at = now

    return created


def scan_and_notify(db: Session) -> dict:
    """Scan published jobs for approaching deadlines, newly-released
    admit cards/results, and saved-search alert matches, creating
    in-app notifications for anyone affected. Idempotent: safe to call
    repeatedly (e.g. every hour) without duplicating notifications.
    """
    today = date.today()
    deadline_horizon = today + timedelta(days=settings.deadline_reminder_days)
    created = 0

    # --- Deadlines approaching ---
    deadline_jobs = db.scalars(
        select(Job).where(
            Job.status == "published",
            Job.deadline.is_not(None),
            Job.deadline >= today,
            Job.deadline <= deadline_horizon,
        )
    ).all()
    for job in deadline_jobs:
        for user_id in _interested_user_ids(db, job.id):
            days_left = (job.deadline - today).days
            if _notify_once(
                db,
                user_id,
                job,
                "deadline",
                f"Deadline approaching: {job.title}",
                f"The application deadline for {job.title} at {job.organization} is {job.deadline} "
                f"({days_left} day{'s' if days_left != 1 else ''} left).",
            ):
                created += 1

    # --- Admit cards released ---
    admit_card_jobs = db.scalars(
        select(Job).where(
            Job.status == "published",
            Job.admit_card_date.is_not(None),
            Job.admit_card_date <= today,
        )
    ).all()
    for job in admit_card_jobs:
        for user_id in _interested_user_ids(db, job.id):
            if _notify_once(
                db,
                user_id,
                job,
                "admit_card",
                f"Admit card released: {job.title}",
                f"The admit card for {job.title} at {job.organization} is now available."
                + (f" {job.admit_card_url}" if job.admit_card_url else ""),
            ):
                created += 1

    # --- Results declared ---
    result_jobs = db.scalars(
        select(Job).where(
            Job.status == "published",
            Job.result_date.is_not(None),
            Job.result_date <= today,
        )
    ).all()
    for job in result_jobs:
        for user_id in _interested_user_ids(db, job.id):
            if _notify_once(
                db,
                user_id,
                job,
                "result",
                f"Result declared: {job.title}",
                f"The result for {job.title} at {job.organization} has been declared."
                + (f" {job.result_url}" if job.result_url else ""),
            ):
                created += 1

    # --- Saved-search alert matches ---
    alert_notifications = _check_saved_search_alerts(db)
    created += alert_notifications

    db.commit()
    logger.info(
        "Notification scan: %s deadline jobs, %s admit-card jobs, %s result jobs, %s alert matches, %s notifications created",
        len(deadline_jobs),
        len(admit_card_jobs),
        len(result_jobs),
        alert_notifications,
        created,
    )
    return {
        "deadline_jobs_checked": len(deadline_jobs),
        "admit_card_jobs_checked": len(admit_card_jobs),
        "result_jobs_checked": len(result_jobs),
        "alert_matches_notified": alert_notifications,
        "notifications_created": created,
    }


# Upgrade path: to add real email/SMS delivery, call an outbound
# provider inside _notify_once alongside the DB insert (guarded by a
# settings flag + the user's contact preference), and keep the in-app
# row either way as the reliable fallback record of what was sent.
