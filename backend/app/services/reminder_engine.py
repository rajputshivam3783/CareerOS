"""V19.4 — Reminder engine.

Two halves:

  * `sync_auto_reminders(db)` — for every interested user (saved/
    applied) of every published Government job with a relevant date
    set (deadline, exam_date, result-expected via `Job.result_date`,
    document-verification/medical/joining via the matching
    RecruitmentUpdate.event_date), ensures a ReminderRule exists at
    each of that user's configured offsets (default 3 and 1 days
    before — see Job.deadline etc. below). Safe to re-run: a
    `(user, job, reminder_type, target_date, offset_days)` combination
    is only ever inserted once (checked before insert; no unique
    constraint needed since this is the only writer).
  * `fire_due_reminders(db)` — the scheduled scan: any ReminderRule
    whose `fire_date` is today (or earlier — covers a missed run) and
    hasn't fired yet gets delivered through the same channel
    abstraction automation.py uses, then stamped `fired_at` so it's
    never delivered twice.

A user can also create a fully custom reminder directly (see
POST /reminders in app.api.notification_engine) with `auto_created=False`
and `offset_days=0` — `fire_date` is simply `target_date` in that case.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import (
    Application, Job, RecruitmentUpdate, ReminderRule, SavedJob, User, UserNotificationPreference,
)
from app.services.notification_templates import get_template, render
from app.services.notification_channels import CHANNELS

_DEFAULT_OFFSETS = [3, 1]

_REMINDER_LABELS = {
    "deadline": "your application deadline", "exam_date": "your exam", "result_expected": "the expected result date",
    "document_verification": "document verification", "medical": "your medical examination", "joining": "your joining date",
}

# reminder_type -> how to read the target date off a Job row (None
# means it instead comes from the matching RecruitmentUpdate.event_date
# — see _job_level_dates / _update_level_dates below).
_JOB_DATE_FIELD = {"deadline": "deadline", "exam_date": "exam_date", "result_expected": "result_date"}
_UPDATE_TYPE_FIELD = {"document_verification": "dv", "medical": "medical", "joining": "joining"}


def _interested_user_ids(db: Session, job_id: int) -> set[int]:
    saved = db.scalars(select(SavedJob.user_id).where(SavedJob.job_id == job_id)).all()
    applied = db.scalars(select(Application.user_id).where(Application.job_id == job_id)).all()
    return set(saved) | set(applied)


def _offsets_for(db: Session, user_id: int) -> list[int]:
    # V19.4 leaves per-type/offset customization to POST /reminders
    # (custom reminders); auto-created ones use the same sensible
    # default for every user for now, same as V7's fixed
    # deadline_reminder_days default before this version existed.
    return _DEFAULT_OFFSETS


def _ensure_reminder(db: Session, user_id: int, job_id: int, reminder_type: str, target: date, offset: int) -> bool:
    fire_date = date.fromordinal(target.toordinal() - offset)
    if fire_date < date.today():
        return False  # don't backfill reminders for dates already in the past
    existing = db.scalar(
        select(ReminderRule.id).where(
            ReminderRule.user_id == user_id, ReminderRule.job_id == job_id,
            ReminderRule.reminder_type == reminder_type, ReminderRule.target_date == target,
            ReminderRule.offset_days == offset,
        )
    )
    if existing:
        return False
    db.add(ReminderRule(
        user_id=user_id, job_id=job_id, reminder_type=reminder_type,
        target_date=target, offset_days=offset, fire_date=fire_date, auto_created=True,
    ))
    return True


def sync_auto_reminders(db: Session) -> int:
    created = 0
    jobs = db.scalars(select(Job).where(Job.status == "published", Job.job_type.ilike("Government"))).all()
    for job in jobs:
        interested = _interested_user_ids(db, job.id)
        if not interested:
            continue
        for reminder_type, field in _JOB_DATE_FIELD.items():
            target = getattr(job, field, None)
            if not target or target < date.today():
                continue
            for user_id in interested:
                for offset in _offsets_for(db, user_id):
                    if _ensure_reminder(db, user_id, job.id, reminder_type, target, offset):
                        created += 1

    for reminder_type, update_type in _UPDATE_TYPE_FIELD.items():
        updates = db.scalars(
            select(RecruitmentUpdate).where(
                RecruitmentUpdate.update_type == update_type, RecruitmentUpdate.status == "published",
                RecruitmentUpdate.event_date.is_not(None), RecruitmentUpdate.event_date >= date.today(),
            )
        ).all()
        for update in updates:
            interested = _interested_user_ids(db, update.job_id)
            for user_id in interested:
                for offset in _offsets_for(db, user_id):
                    if _ensure_reminder(db, user_id, update.job_id, reminder_type, update.event_date, offset):
                        created += 1

    if created:
        db.commit()
    return created


def fire_due_reminders(db: Session) -> int:
    due = db.scalars(
        select(ReminderRule).where(ReminderRule.fired_at.is_(None), ReminderRule.fire_date <= date.today())
    ).all()
    fired = 0
    for reminder in due:
        job = db.get(Job, reminder.job_id)
        user = db.get(User, reminder.user_id)
        if not job or not user:
            reminder.fired_at = datetime.utcnow()
            continue
        pref = db.get(UserNotificationPreference, user.id)
        in_app_on = pref.in_app_enabled if pref else True
        email_on = pref.email_enabled if pref else True
        context = {
            "title": job.title, "job_title": job.title, "organization": job.organization,
            "event_date": reminder.target_date, "url": f"/jobs/{job.id}",
            "reminder_label": _REMINDER_LABELS.get(reminder.reminder_type, reminder.reminder_type),
        }
        if in_app_on:
            tmpl = get_template(db, "reminder", "in_app")
            if tmpl:
                _, body = render(tmpl, context)
                CHANNELS["in_app"].deliver(db, user, title=body[:220], body=body, job_id=job.id)
        if email_on:
            tmpl = get_template(db, "reminder", "email")
            if tmpl:
                subject, body = render(tmpl, context)
                CHANNELS["email"].deliver(db, user, title=subject, body=body, job_id=job.id)
        reminder.fired_at = datetime.utcnow()
        fired += 1
    if due:
        db.commit()
    return fired
