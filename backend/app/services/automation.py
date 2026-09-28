"""V19.4 — Automation engine.

Scans, since each trigger's own AutomationCursor high-water mark:

  * newly-published Government Jobs -> "recruitment_published" to
    interested users + "subscription_match" to anyone subscribed to
    that job's organization/category/qualification/govt_level, plus
    RECRUITMENT type-specific subscribers.
  * new RecruitmentUpdate rows -> the matching alert template (see
    _UPDATE_TYPE_TEMPLATE_KEY) to everyone who saved/applied to the
    parent job, plus anyone subscribed to it directly or to its
    organization/category.
  * AuditLog rows recording an admin `update_job_lifecycle` call whose
    changes touched `deadline` on an already-published job ->
    "deadline_extended". (Best-effort: the audit log records the new
    value, not the old one, so this fires on any post-publish deadline
    edit — see the module docstring in app.models.domain.AuditLog for
    why that log exists at all. A true "extended vs shortened" distinction
    would need to store the previous deadline, which is out of scope here.)

Each matched (user, event) pair is delivered through every channel the
user's UserNotificationPreference has enabled (default: in-app + email
both on), respecting quiet hours for anything other than in-app.
Every attempt — success or failure — gets one NotificationDeliveryLog
row, which is what the admin queue/retry/stats endpoints read.

Callable two ways: `run_automation_scan(db)` for the scheduled job
(see app/scheduler.py), and the same function again from
`POST /admin/automation/run` for a manual run (spec: Scheduler ->
Manual Run).
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import (
    Application,
    AuditLog,
    AutomationCursor,
    AutomationLog,
    Job,
    NotificationDeliveryLog,
    RecruitmentUpdate,
    SavedJob,
    Subscription,
    User,
    UserNotificationPreference,
)
from app.services.notification_channels import CHANNELS
from app.services.notification_templates import get_template, render

logger = logging.getLogger("careeros.automation")

_UPDATE_TYPE_TEMPLATE_KEY = {
    "result": "result", "admit_card": "admit_card", "answer_key": "answer_key",
    "exam_date": "exam_date", "cutoff": "cutoff", "merit_list": "merit_list",
    "dv": "document_verification", "joining": "joining", "medical": "medical_examination",
    "cancelled": "recruitment_cancelled", "application_open": "application_open",
    "correction_window": "correction_window", "city_intimation": "city_intimation",
    "objection_window": "objection_window", "final_answer_key": "final_answer_key",
    "score_card": "score_card",
    # Everything else RECRUITMENT_UPDATE_TYPES allows (admission, syllabus,
    # counselling, application_closed, final_selection, completed, notice,
    # notification) falls back to the generic "New Notification" template
    # rather than being silently dropped.
}

# subscription_type -> Job column(s) it's matched against. "recruitment"
# and the plain org/exam/category/qualification/state ones are handled
# separately in _matches_subscription; this covers the flat govt-level/
# category checkbox subscriptions from the spec (Central Jobs, PSU, Bank
# Jobs, ...), reusing the exact vocabulary app.api.platform's FILTERS
# section and Job.category/govt_level already use.
_CATEGORY_SUBSCRIPTION_VALUES = {
    "central": "Central", "psu": "PSU", "bank": "Bank", "railway": "Railway",
    "police": "Police", "teaching": "Teaching", "medical": "Medical",
    "engineering": "Engineering", "defence": "Defence",
}


def _get_cursor(db: Session, trigger: str) -> int:
    row = db.get(AutomationCursor, trigger)
    return row.last_id if row else 0


def _set_cursor(db: Session, trigger: str, last_id: int) -> None:
    row = db.get(AutomationCursor, trigger)
    if row is None:
        db.add(AutomationCursor(trigger=trigger, last_id=last_id))
    else:
        row.last_id = last_id
        row.updated_at = datetime.utcnow()


def _matches_subscription(sub: Subscription, job: Job) -> bool:
    if sub.subscription_type == "recruitment":
        return sub.job_id == job.id
    if sub.subscription_type == "organization":
        return bool(sub.value) and sub.value.strip().lower() in (job.organization or "").lower()
    if sub.subscription_type == "exam":
        return bool(sub.value) and sub.value.strip().lower() in (job.title or "").lower()
    if sub.subscription_type == "category":
        return bool(sub.value) and sub.value.strip().lower() in (job.category or "").lower()
    if sub.subscription_type == "qualification":
        return bool(sub.value) and sub.value.strip().lower() in (job.qualification or "").lower()
    if sub.subscription_type == "state":
        if job.govt_level != "State":
            return False
        return not sub.value or sub.value.strip().lower() in (job.location or "").lower()
    if sub.subscription_type in _CATEGORY_SUBSCRIPTION_VALUES:
        wanted = _CATEGORY_SUBSCRIPTION_VALUES[sub.subscription_type]
        return wanted.lower() in (job.category or "").lower() or wanted == job.govt_level
    return False


def _quiet_hours_active(pref: UserNotificationPreference | None) -> bool:
    if not pref or pref.quiet_hours_start is None or pref.quiet_hours_end is None:
        return False
    hour = datetime.utcnow().hour
    start, end = pref.quiet_hours_start, pref.quiet_hours_end
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end  # wraps past midnight


def _deliver(db: Session, user: User, *, template_key: str, context: dict, job_id: int | None) -> int:
    """Delivers one event to one user across every channel their
    preferences enable. Returns the number of channels that actually
    sent (in-app always counts if enabled; email counts even during
    quiet hours suppression as `skipped`, not `sent`)."""
    pref = db.get(UserNotificationPreference, user.id)
    email_on = pref.email_enabled if pref else True
    in_app_on = pref.in_app_enabled if pref else True
    quiet = _quiet_hours_active(pref)

    sent = 0
    if in_app_on:
        tmpl = get_template(db, template_key, "in_app")
        if tmpl:
            _, body = render(tmpl, context)
            result = CHANNELS["in_app"].deliver(db, user, title=body[:220], body=body, job_id=job_id)
            db.add(NotificationDeliveryLog(
                notification_id=result.notification_id, user_id=user.id, channel="in_app",
                status=result.status, provider=result.provider, error=result.error,
            ))
            if result.status == "sent":
                sent += 1

    if email_on:
        tmpl = get_template(db, template_key, "email")
        if tmpl:
            if quiet:
                db.add(NotificationDeliveryLog(user_id=user.id, channel="email", status="skipped", provider="smtp", error="quiet_hours"))
            else:
                subject, body = render(tmpl, context)
                result = CHANNELS["email"].deliver(db, user, title=subject or template_key, body=body, job_id=job_id)
                db.add(NotificationDeliveryLog(
                    user_id=user.id, channel="email", status=result.status, provider=result.provider, error=result.error,
                ))
                if result.status == "sent":
                    sent += 1
    return sent


def _job_context(job: Job, *, event_date=None, reminder_label: str | None = None) -> dict:
    return {
        "title": job.title, "job_title": job.title, "organization": job.organization,
        "event_date": event_date or "", "url": f"/jobs/{job.id}", "reminder_label": reminder_label or "",
    }


def _interested_user_ids(db: Session, job_id: int) -> set[int]:
    saved = db.scalars(select(SavedJob.user_id).where(SavedJob.job_id == job_id)).all()
    applied = db.scalars(select(Application.user_id).where(Application.job_id == job_id)).all()
    return set(saved) | set(applied)


def _subscribed_user_ids_for_job(db: Session, job: Job) -> set[int]:
    subs = db.scalars(select(Subscription).where(Subscription.enabled == True)).all()  # noqa: E712
    return {s.user_id for s in subs if _matches_subscription(s, job)}


def _scan_new_recruitments(db: Session) -> tuple[int, int]:
    cursor = _get_cursor(db, "recruitment_published")
    jobs = db.scalars(
        select(Job).where(Job.id > cursor, Job.status == "published", Job.job_type.ilike("Government")).order_by(Job.id)
    ).all()
    notifications = 0
    for job in jobs:
        context = _job_context(job)
        recipients = _interested_user_ids(db, job.id) | _subscribed_user_ids_for_job(db, job)
        for user_id in recipients:
            user = db.get(User, user_id)
            if not user:
                continue
            key = "subscription_match" if user_id not in _interested_user_ids(db, job.id) else "recruitment_published"
            notifications += _deliver(db, user, template_key=key, context=context, job_id=job.id)
        db.add(AutomationLog(trigger="recruitment_published", job_id=job.id, notifications_created=len(recipients),
                              detail=f"{len(recipients)} recipient(s)"))
    if jobs:
        _set_cursor(db, "recruitment_published", jobs[-1].id)
    return len(jobs), notifications


def _scan_recruitment_updates(db: Session) -> tuple[int, int]:
    cursor = _get_cursor(db, "recruitment_update")
    rows = db.scalars(
        select(RecruitmentUpdate).where(RecruitmentUpdate.id > cursor, RecruitmentUpdate.status == "published").order_by(RecruitmentUpdate.id)
    ).all()
    notifications = 0
    for update in rows:
        job = db.get(Job, update.job_id)
        if not job:
            continue
        key = _UPDATE_TYPE_TEMPLATE_KEY.get(update.update_type, "new_notification")
        context = _job_context(job, event_date=update.event_date)
        recipients = _interested_user_ids(db, job.id) | _subscribed_user_ids_for_job(db, job)
        for user_id in recipients:
            user = db.get(User, user_id)
            if user:
                notifications += _deliver(db, user, template_key=key, context=context, job_id=job.id)
        db.add(AutomationLog(trigger=key, job_id=job.id, notifications_created=len(recipients),
                              detail=f"update_type={update.update_type}, {len(recipients)} recipient(s)"))
    if rows:
        _set_cursor(db, "recruitment_update", rows[-1].id)
    return len(rows), notifications


def _scan_deadline_extensions(db: Session) -> tuple[int, int]:
    cursor = _get_cursor(db, "deadline_extended")
    rows = db.scalars(
        select(AuditLog).where(
            AuditLog.id > cursor, AuditLog.action == "update_job_lifecycle", AuditLog.detail.ilike("%'deadline'%")
        ).order_by(AuditLog.id)
    ).all()
    notifications = 0
    for row in rows:
        job = db.get(Job, int(row.entity_id)) if row.entity_id and row.entity_id.isdigit() else None
        if not job or job.status != "published":
            continue
        context = _job_context(job, event_date=job.deadline)
        recipients = _interested_user_ids(db, job.id)
        for user_id in recipients:
            user = db.get(User, user_id)
            if user:
                notifications += _deliver(db, user, template_key="deadline_extended", context=context, job_id=job.id)
        if recipients:
            db.add(AutomationLog(trigger="deadline_extended", job_id=job.id, notifications_created=len(recipients),
                                  detail=f"{len(recipients)} recipient(s)"))
    if rows:
        _set_cursor(db, "deadline_extended", rows[-1].id)
    return len(rows), notifications


def run_automation_scan(db: Session) -> dict:
    """Idempotent, safe to call on a schedule or manually — every scan
    only looks past its own trigger's cursor."""
    jobs_scanned, jobs_notified = _scan_new_recruitments(db)
    updates_scanned, updates_notified = _scan_recruitment_updates(db)
    audit_scanned, audit_notified = _scan_deadline_extensions(db)
    db.commit()
    result = {
        "recruitments_scanned": jobs_scanned, "recruitment_notifications": jobs_notified,
        "updates_scanned": updates_scanned, "update_notifications": updates_notified,
        "deadline_audit_rows_scanned": audit_scanned, "deadline_notifications": audit_notified,
        "total_notifications": jobs_notified + updates_notified + audit_notified,
    }
    logger.info("Automation scan complete: %s", result)
    return result
