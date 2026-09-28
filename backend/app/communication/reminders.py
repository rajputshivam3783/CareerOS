"""V23.4 — the reminder scan: interview / deadline / task reminders.

Run on a schedule (see app/scheduler.py's ``careeros_communication_reminders``
job), never inside a normal page request (spec section 14).

IDEMPOTENCY (spec sections 6/15) is the central design constraint of
this module. Every reminder has a stable identity —
``(source_type, source_id, reminder_type, scheduled_for)`` — computed
once from the source row's own date, and the ``NotificationReminder``
row for that identity is inserted (status=PENDING) *before* any
Notification/EmailMessage is created for it. A concurrent or retried
worker either:
  * loses the INSERT race on the table's UNIQUE constraint (an
    IntegrityError caught the same way app.notifications.service and
    app.job_alerts.execution already handle their own dedupe rows), or
  * finds the existing row already SENT and skips it outright.
Either way, a worker restart or a duplicate scheduler tick can never
create a second notification/email for the same reminder. See
app.models.domain.NotificationReminder's docstring for the full
rationale for a new table rather than reusing V19.4's ReminderRule.

QUIET HOURS (spec section 17): a reminder that is due but falls inside
the recipient's configured quiet hours (UserNotificationPreference.
quiet_hours_start/end, evaluated in their own timezone — see
_local_hour) is recorded as DELAYED, not silently dropped and not
sent — the next scan tick, once quiet hours have passed, promotes it
straight to SENT (_promote_delayed rebuilds the same content and calls
the same _deliver path a fresh reminder would). URGENT-priority
reminders (an interview literally starting within the hour, or
something already overdue) are never delayed — spec: "URGENT/
security-critical notifications may follow separate rules."

TIMEZONE (spec section 16): every timestamp this module reads or
writes (ApplicationInterview.scheduled_at, Application.deadline,
ApplicationTask.due_at, NotificationReminder.scheduled_for) is naive
UTC, exactly as stored by app.applications.* today — this module does
not change that storage convention anywhere. The user's timezone
preference (UserNotificationPreference.timezone, default "UTC" — see
that column's own docstring) is consulted for exactly one purpose:
deciding whether "now" falls inside their configured quiet hours. If
the stored value isn't a recognized IANA name, this falls back to UTC
rather than raising, and the reminder scan continues rather than
failing loudly for one bad row (spec section 24: "Reminder failure
must not break ... other operations").
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.email import service as email_service
from app.models.domain import (
    Application, ApplicationInterview, ApplicationTask, NotificationReminder, User, UserNotificationPreference,
)
from app.notifications import service as notification_service

logger = logging.getLogger("careeros.communication.reminders")

# Offsets, as (reminder_type, timedelta-before-the-event).
INTERVIEW_OFFSETS: tuple[tuple[str, timedelta], ...] = (
    ("24_HOURS_BEFORE", timedelta(hours=24)),
    ("1_HOUR_BEFORE", timedelta(hours=1)),
)
DEADLINE_OFFSET_DAYS: tuple[tuple[str, int], ...] = (
    ("7_DAYS_BEFORE", 7), ("3_DAYS_BEFORE", 3), ("1_DAY_BEFORE", 1),
)
# Tasks use a smaller offset set than deadlines on purpose — spec
# section 25 "Do not overwhelm users" / "avoid notification spam";
# a task is a lighter-weight object than a deadline and a 7/3-day
# heads-up for it would be noise.
TASK_OFFSET_DAYS: tuple[tuple[str, int], ...] = (("1_DAY_BEFORE", 1),)

# How far in the past a reminder scan will still create/deliver a
# just-noticed reminder for (e.g. the scheduler was down for a few
# hours) — bounded so a long-dead scheduler doesn't suddenly fire a
# flood of stale reminders for events from long ago.
LATE_GRACE = timedelta(hours=6)


# --------------------------------------------------------------------
# Idempotency / preference plumbing
# --------------------------------------------------------------------

def _has_reminder(db: Session, *, source_type: str, source_id: int, reminder_type: str, scheduled_for: datetime) -> NotificationReminder | None:
    return db.scalar(
        select(NotificationReminder).where(
            NotificationReminder.source_type == source_type,
            NotificationReminder.source_id == source_id,
            NotificationReminder.reminder_type == reminder_type,
            NotificationReminder.scheduled_for == scheduled_for,
        )
    )


def _local_hour(pref: UserNotificationPreference | None, now_utc: datetime) -> int:
    tz_name = pref.timezone if pref and pref.timezone else "UTC"
    try:
        return now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(tz_name)).hour
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unrecognized timezone %r on a user's preferences — defaulting to UTC", tz_name)
        return now_utc.hour


def _in_quiet_hours(pref: UserNotificationPreference | None, now_utc: datetime) -> bool:
    if pref is None or pref.quiet_hours_start is None or pref.quiet_hours_end is None:
        return False
    hour = _local_hour(pref, now_utc)
    start, end = pref.quiet_hours_start, pref.quiet_hours_end
    if start == end:
        return False  # a zero-width window means "no quiet hours", not "always quiet"
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # overnight window, e.g. 22 -> 6


def _in_app_enabled(db: Session, user_id: int, notify_column: str) -> bool:
    """Mirrors app.job_alerts.execution._in_app_enabled_for_job's
    shape for INTERVIEW/DEADLINE — see that function's docstring for
    why this checks the flag itself rather than relying on
    app.notifications.service.create_notification to do it (a
    documented pre-existing V23.1 gap)."""
    pref = db.get(UserNotificationPreference, user_id)
    if pref is None:
        return True
    if not pref.in_app_enabled:
        return False
    return bool(getattr(pref, notify_column, True))


def _email_enabled(db: Session, user_id: int) -> bool:
    pref = db.get(UserNotificationPreference, user_id)
    return pref is None or pref.email_enabled


def _priority_for_days(days_until: int) -> str:
    from app.communication.priority import score_by_days_until
    return score_by_days_until(days_until).level


def _time_phrase_for_days(days_until: int) -> str:
    if days_until < 0:
        return f"{abs(days_until)} day(s) overdue"
    if days_until == 0:
        return "due today"
    return f"due in {days_until} day(s)"


def _create_reminder_row(db: Session, **kwargs) -> NotificationReminder | None:
    """Inserts a PENDING NotificationReminder, returning None (never
    raising) if one with this exact identity already exists — see
    module docstring's IDEMPOTENCY section."""
    if _has_reminder(db, source_type=kwargs["source_type"], source_id=kwargs["source_id"],
                      reminder_type=kwargs["reminder_type"], scheduled_for=kwargs["scheduled_for"]):
        return None
    row = NotificationReminder(status="PENDING", **kwargs)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    db.refresh(row)
    return row


# --------------------------------------------------------------------
# Content builders — one per source_type, shared by the initial scan
# and by _promote_delayed so a promoted reminder gets identical content.
# --------------------------------------------------------------------

def _interview_content(interview: ApplicationInterview, app: Application, reminder_type: str, user: User) -> dict:
    time_phrase = "in 1 hour" if reminder_type == "1_HOUR_BEFORE" else "in 24 hours"
    job_title = app.job_title or app.role
    return {
        "title": f"Interview {time_phrase}: {job_title}",
        "message": f"Your {interview.interview_type.title()} interview for {job_title} at {app.company} is {time_phrase}.",
        "action_url": f"/applications/{app.id}",
        "category": "INTERVIEW",
        "notify_column": "notify_interview",
        "email_template_key": "INTERVIEW_REMINDER",
        "email_variables": {
            "user_name": user.full_name, "interview_type": interview.interview_type.title(),
            "job_title": job_title, "company_name": app.company,
            "interview_date": interview.scheduled_at.strftime("%b %d, %Y %H:%M UTC"), "time_phrase": time_phrase,
            "action_url": f"/applications/{app.id}",
        },
    }


def _deadline_content(app: Application, days_until: int, user: User) -> dict:
    phrase = _time_phrase_for_days(days_until)
    job_title = app.job_title or app.role
    return {
        "title": f"Deadline {phrase}: {job_title}",
        "message": f"The application deadline for {job_title} at {app.company} is {phrase}.",
        "action_url": f"/applications/{app.id}",
        "category": "DEADLINE",
        "notify_column": "notify_deadline",
        "email_template_key": "DEADLINE_REMINDER",
        "email_variables": {
            "user_name": user.full_name, "job_title": job_title, "company_name": app.company,
            "deadline_date": app.deadline.isoformat(), "time_phrase": phrase, "action_url": f"/applications/{app.id}",
        },
    }


def _task_content(task: ApplicationTask, app: Application, days_until: int, user: User) -> dict:
    phrase = _time_phrase_for_days(days_until)
    job_title = app.job_title or app.role
    return {
        "title": f'Task {phrase}: "{task.title}"',
        "message": f'Your task "{task.title}" on the application for {job_title} is {phrase}.',
        "action_url": f"/applications/{app.id}",
        "category": "DEADLINE",
        "notify_column": "notify_deadline",
        "email_template_key": "TASK_DUE_REMINDER",
        "email_variables": {
            "user_name": user.full_name, "task_title": task.title, "job_title": job_title,
            "due_date": task.due_at.date().isoformat(), "time_phrase": phrase, "action_url": f"/applications/{app.id}",
        },
    }


def _build_content(db: Session, reminder: NotificationReminder, *, today: date) -> dict | None:
    """Rebuilds delivery content for an existing reminder row purely
    from its (source_type, source_id) — used by _promote_delayed so a
    DELAYED reminder is re-derived from current source data rather
    than replaying stale wording. Returns None if the source row no
    longer exists (deleted/cancelled since the reminder was created)."""
    user = db.get(User, reminder.user_id)
    if user is None:
        return None
    if reminder.source_type == "INTERVIEW":
        interview = db.get(ApplicationInterview, reminder.source_id)
        if interview is None or interview.result != "SCHEDULED":
            return None
        app = db.get(Application, interview.application_id)
        if app is None:
            return None
        return _interview_content(interview, app, reminder.reminder_type, user)
    if reminder.source_type == "DEADLINE":
        app = db.get(Application, reminder.source_id)
        if app is None or app.deadline is None:
            return None
        days_until = (app.deadline - today).days
        return _deadline_content(app, days_until, user)
    if reminder.source_type == "TASK":
        task = db.get(ApplicationTask, reminder.source_id)
        if task is None or task.completed or task.due_at is None:
            return None
        app = db.get(Application, task.application_id)
        if app is None:
            return None
        days_until = (task.due_at.date() - today).days
        return _task_content(task, app, days_until, user)
    return None


def _deliver(db: Session, reminder: NotificationReminder, *, user: User, content: dict) -> None:
    """Sends one due (non-delayed) reminder through the existing
    V23.1/V23.2 systems and marks the row SENT. Never raises — any
    failure is recorded on the row and logged (spec section 24)."""
    try:
        if _in_app_enabled(db, user.id, content["notify_column"]):
            record = notification_service.create_notification(
                db, user.id, notification_type=f"reminder_{content['category'].lower()}", category=content["category"],
                priority=reminder.priority, title=content["title"], message=content["message"], action_url=content["action_url"],
                dedupe_key=f"reminder:{reminder.source_type}:{reminder.source_id}:{reminder.reminder_type}",
            )
            if record is not None:
                reminder.notification_id = record.id
        if _email_enabled(db, user.id) and user.email:
            email = email_service.queue_email(
                db, user_id=user.id, recipient=user.email, template_key=content["email_template_key"],
                variables=content["email_variables"], category=content["category"],
                dedupe_key=f"reminder_email:{reminder.source_type}:{reminder.source_id}:{reminder.reminder_type}",
            )
            if email is not None:
                reminder.email_message_id = email.id
        reminder.status = "SENT"
        reminder.sent_at = datetime.utcnow()
    except Exception:  # noqa: BLE001 — a reminder failure must never break the scan (spec section 24)
        logger.error("Failed to deliver reminder id=%s", reminder.id, exc_info=True)
        reminder.status = "FAILED"
        reminder.attempts += 1
        reminder.last_error = "delivery failed — see server logs"
    db.commit()


def _promote_delayed(db: Session, user_id: int, *, today: date) -> int:
    """Delivers any of this user's DELAYED reminders whose quiet hours
    have since ended, rebuilding content fresh from current source
    data. Returns the count actually sent."""
    pref = db.get(UserNotificationPreference, user_id)
    now = datetime.utcnow()
    if _in_quiet_hours(pref, now):
        return 0
    delayed = db.scalars(
        select(NotificationReminder).where(NotificationReminder.user_id == user_id, NotificationReminder.status == "DELAYED")
    ).all()
    sent = 0
    for reminder in delayed:
        content = _build_content(db, reminder, today=today)
        if content is None:
            reminder.status = "SKIPPED"
            db.commit()
            continue
        user = db.get(User, user_id)
        _deliver(db, reminder, user=user, content=content)
        sent += 1
    return sent


# --------------------------------------------------------------------
# Scans
# --------------------------------------------------------------------

def _scan_interviews(db: Session, *, now: datetime) -> dict:
    created = sent = 0
    rows = db.execute(
        select(ApplicationInterview, Application)
        .join(Application, Application.id == ApplicationInterview.application_id)
        .where(ApplicationInterview.result == "SCHEDULED", ApplicationInterview.scheduled_at.is_not(None))
    ).all()
    for interview, app in rows:
        target = interview.scheduled_at
        if target < now:
            continue  # spec section 6: never remind for an interview that has already passed
        for reminder_type, offset in INTERVIEW_OFFSETS:
            scheduled_for = target - offset
            if scheduled_for > now or scheduled_for < now - LATE_GRACE:
                continue
            row = _create_reminder_row(
                db, user_id=app.user_id, source_type="INTERVIEW", source_id=interview.id,
                reminder_type=reminder_type, scheduled_for=scheduled_for,
                priority="URGENT" if reminder_type == "1_HOUR_BEFORE" else "HIGH",
            )
            if row is None:
                continue
            created += 1
            user = db.get(User, app.user_id)
            pref = db.get(UserNotificationPreference, app.user_id)
            if row.priority != "URGENT" and _in_quiet_hours(pref, now):
                row.status = "DELAYED"
                db.commit()
                continue
            _deliver(db, row, user=user, content=_interview_content(interview, app, reminder_type, user))
            sent += 1
    return {"created": created, "sent": sent}


def _scan_deadlines(db: Session, *, today: date, now: datetime) -> dict:
    created = sent = 0
    from app.applications.status import TERMINAL_STATUSES

    applications = db.scalars(
        select(Application).where(Application.deadline.is_not(None), Application.status.not_in(TERMINAL_STATUSES))
    ).all()
    for app in applications:
        days_until = (app.deadline - today).days
        reminder_type = None
        for label, offset_days in DEADLINE_OFFSET_DAYS:
            if days_until == offset_days:
                reminder_type = label
                break
        if reminder_type is None:
            if days_until == 0:
                reminder_type = "DUE_TODAY"
            elif days_until == -1:
                # OVERDUE fires once, the day after the deadline passes —
                # not every day forever (spec section 25: no repeat spam).
                reminder_type = "OVERDUE"
            else:
                continue
        scheduled_for = datetime(app.deadline.year, app.deadline.month, app.deadline.day)
        row = _create_reminder_row(
            db, user_id=app.user_id, source_type="DEADLINE", source_id=app.id, reminder_type=reminder_type,
            scheduled_for=scheduled_for, priority=_priority_for_days(days_until),
        )
        if row is None:
            continue
        created += 1
        user = db.get(User, app.user_id)
        pref = db.get(UserNotificationPreference, app.user_id)
        if row.priority != "URGENT" and _in_quiet_hours(pref, now):
            row.status = "DELAYED"
            db.commit()
            continue
        _deliver(db, row, user=user, content=_deadline_content(app, days_until, user))
        sent += 1
    return {"created": created, "sent": sent}


def _scan_tasks(db: Session, *, today: date, now: datetime) -> dict:
    created = sent = 0
    rows = db.execute(
        select(ApplicationTask, Application)
        .join(Application, Application.id == ApplicationTask.application_id)
        .where(ApplicationTask.completed.is_(False), ApplicationTask.due_at.is_not(None))
    ).all()
    for task, app in rows:
        days_until = (task.due_at.date() - today).days
        reminder_type = None
        for label, offset_days in TASK_OFFSET_DAYS:
            if days_until == offset_days:
                reminder_type = label
                break
        if reminder_type is None:
            if days_until == 0:
                reminder_type = "DUE_TODAY"
            elif days_until == -1:
                reminder_type = "OVERDUE"
            else:
                continue
        scheduled_for = datetime(task.due_at.year, task.due_at.month, task.due_at.day)
        row = _create_reminder_row(
            db, user_id=app.user_id, source_type="TASK", source_id=task.id, reminder_type=reminder_type,
            scheduled_for=scheduled_for, priority=_priority_for_days(days_until),
        )
        if row is None:
            continue
        created += 1
        user = db.get(User, app.user_id)
        pref = db.get(UserNotificationPreference, app.user_id)
        if row.priority != "URGENT" and _in_quiet_hours(pref, now):
            row.status = "DELAYED"
            db.commit()
            continue
        _deliver(db, row, user=user, content=_task_content(task, app, days_until, user))
        sent += 1
    return {"created": created, "sent": sent}


def run_due_reminders(db: Session) -> dict:
    """The single entry point the scheduler (and the admin manual-run
    endpoint) calls. Promotes any previously-DELAYED reminder whose
    quiet hours have since ended, then scans interviews, deadlines,
    and tasks for newly-due reminders. Bounded, idempotent, and never
    raises past a single source row's own failure (spec section 24)."""
    now = datetime.utcnow()
    today = now.date()

    promoted = 0
    delayed_user_ids = db.scalars(
        select(NotificationReminder.user_id).where(NotificationReminder.status == "DELAYED").distinct()
    ).all()
    for user_id in delayed_user_ids:
        promoted += _promote_delayed(db, user_id, today=today)

    interview_result = _scan_interviews(db, now=now)
    deadline_result = _scan_deadlines(db, today=today, now=now)
    task_result = _scan_tasks(db, today=today, now=now)

    return {
        "interviews": interview_result,
        "deadlines": deadline_result,
        "tasks": task_result,
        "promoted_from_quiet_hours": promoted,
    }
