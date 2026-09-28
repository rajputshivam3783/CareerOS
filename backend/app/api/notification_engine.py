"""V19.4 — Government Automation & Notification Engine API.

Additive, layered on top of the existing `current_user` auth dependency
(app.core.security — unmodified, per the V19.4 "Do NOT rewrite
Authentication" instruction) and `guard` admin dependency
(app.api.admin — reused as-is for every admin-only route below).

Sections: Subscriptions, Preferences, Notification Center, Reminders,
Admin (queue/retry/stats/logs/templates/manual run).
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.admin import guard
from app.core.audit import log_audit
from app.core.security import current_user
from app.db.session import get_db
from app.models.domain import (
    Job, Notification, NotificationDeliveryLog, NotificationTemplate, AutomationLog,
    ReminderRule, Subscription, UserNotificationPreference,
)
from app.services import automation as automation_service
from app.services import reminder_engine as reminder_service
from app.services.notification_templates import DEFAULT_TEMPLATES

router = APIRouter()

_SUBSCRIPTION_TYPES = {
    "recruitment", "organization", "exam", "category", "qualification", "state",
    "central", "psu", "bank", "railway", "police", "teaching", "medical", "engineering", "defence",
}


# =============================================================================
# Subscriptions
# =============================================================================

class SubscriptionIn(BaseModel):
    subscription_type: str = Field(pattern="^(" + "|".join(sorted(_SUBSCRIPTION_TYPES)) + ")$")
    value: str | None = Field(default=None, max_length=220)
    job_id: int | None = None


@router.post("/subscriptions", status_code=201)
def create_subscription(payload: SubscriptionIn, u=Depends(current_user), db: Session = Depends(get_db)):
    if payload.subscription_type == "recruitment" and not payload.job_id:
        raise HTTPException(422, "job_id is required for subscription_type=recruitment")
    if payload.subscription_type != "recruitment" and not payload.value:
        raise HTTPException(422, "value is required for this subscription_type")
    if payload.job_id and not db.get(Job, payload.job_id):
        raise HTTPException(404, "Job not found")

    existing = db.scalar(select(Subscription).where(
        Subscription.user_id == u.id, Subscription.subscription_type == payload.subscription_type,
        Subscription.value == payload.value, Subscription.job_id == payload.job_id,
    ))
    if existing:
        existing.enabled = True
        db.commit()
        db.refresh(existing)  # commit expires existing — refresh before returning it (see app/api/company.py for the same bug/fix)
        return existing
    sub = Subscription(user_id=u.id, subscription_type=payload.subscription_type, value=payload.value, job_id=payload.job_id)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.get("/subscriptions")
def list_subscriptions(u=Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Subscription).where(Subscription.user_id == u.id).order_by(Subscription.id.desc())).all()


@router.delete("/subscriptions/{subscription_id}", status_code=204)
def delete_subscription(subscription_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    sub = db.get(Subscription, subscription_id)
    if not sub or sub.user_id != u.id:
        raise HTTPException(404, "Subscription not found")
    db.delete(sub)
    db.commit()


# =============================================================================
# Preferences
# =============================================================================

class PreferencesIn(BaseModel):
    email_enabled: bool | None = None
    in_app_enabled: bool | None = None
    category_preferences: str | None = None
    organization_preferences: str | None = None
    quiet_hours_start: int | None = Field(default=None, ge=0, le=23)
    quiet_hours_end: int | None = Field(default=None, ge=0, le=23)
    digest_mode: str | None = Field(default=None, pattern="^(instant|daily_digest|weekly_summary)$")
    # V23.1 — per-category in-app toggles for the new event-driven
    # notification system (app.notifications.*). See
    # UserNotificationPreference's own docstring for why these are
    # separate from category_preferences above.
    notify_job: bool | None = None
    notify_application: bool | None = None
    notify_interview: bool | None = None
    notify_deadline: bool | None = None
    notify_recruiter: bool | None = None
    notify_ai: bool | None = None
    notify_system: bool | None = None
    # V23.2 — per-category EMAIL toggles (app.email.preferences).
    # Deliberately never checked for email verification/password
    # reset — those always send via
    # app.email.service.send_transactional_email, which never looks
    # at preferences at all (spec: security-critical email "must not
    # be disabled through ordinary notification preferences").
    email_job: bool | None = None
    email_application: bool | None = None
    email_interview: bool | None = None
    email_deadline: bool | None = None
    email_recruiter: bool | None = None
    email_ai: bool | None = None
    email_system: bool | None = None
    # V23.4 — Communication Center. `timezone` must be a real IANA
    # name (validated below) since app.communication.reminders feeds
    # it straight to zoneinfo.ZoneInfo when evaluating quiet hours;
    # `digest_enabled` is the opt-in switch for the new
    # DAILY_CAREER_DIGEST email (see UserNotificationPreference.
    # digest_enabled's own docstring for why it defaults False unlike
    # every email_* flag above).
    timezone: str | None = None
    digest_enabled: bool | None = None

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"{value!r} is not a recognized IANA timezone name") from exc
        return value


def _get_or_create_preferences(db: Session, user_id: int) -> UserNotificationPreference:
    pref = db.get(UserNotificationPreference, user_id)
    if not pref:
        pref = UserNotificationPreference(user_id=user_id)
        db.add(pref)
        db.commit()
        db.refresh(pref)
    return pref


@router.get("/notifications/preferences")
def get_preferences(u=Depends(current_user), db: Session = Depends(get_db)):
    return _get_or_create_preferences(db, u.id)


@router.put("/notifications/preferences")
def update_preferences(payload: PreferencesIn, u=Depends(current_user), db: Session = Depends(get_db)):
    pref = _get_or_create_preferences(db, u.id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(pref, key, value)
    from datetime import datetime
    pref.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(pref)
    return pref


# =============================================================================
# Notification Center
# =============================================================================

@router.get("/notifications/center")
def notification_center(
    status: str = Query("unread", pattern="^(unread|read|archived|all)$"),
    search: str | None = None,
    notification_type: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    u=Depends(current_user),
    db: Session = Depends(get_db),
):
    q = select(Notification).where(Notification.user_id == u.id)
    if status == "unread":
        q = q.where(Notification.read == False, Notification.archived == False)  # noqa: E712
    elif status == "read":
        q = q.where(Notification.read == True, Notification.archived == False)  # noqa: E712
    elif status == "archived":
        q = q.where(Notification.archived == True)  # noqa: E712
    if notification_type:
        q = q.where(Notification.notification_type == notification_type)
    if search:
        term = f"%{search}%"
        q = q.where(or_(Notification.title.ilike(term), Notification.message.ilike(term)))

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(Notification.id.desc()).offset(offset).limit(limit)).all()
    unread_count = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == u.id, Notification.read == False, Notification.archived == False  # noqa: E712
    ))
    return {"items": rows, "total": total, "unread_count": unread_count, "has_more": offset + len(rows) < total}


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if not n or n.user_id != u.id:
        raise HTTPException(404, "Notification not found")
    n.read = True
    db.commit()
    return {"read": True, "id": notification_id}


@router.post("/notifications/read-all")
def mark_all_read(u=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.user_id == u.id, Notification.read == False)).all()  # noqa: E712
    for n in rows:
        n.read = True
    db.commit()
    return {"marked_read": len(rows)}


@router.post("/notifications/{notification_id}/archive")
def archive_notification(notification_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if not n or n.user_id != u.id:
        raise HTTPException(404, "Notification not found")
    n.archived = True
    db.commit()
    return {"archived": True, "id": notification_id}


@router.delete("/notifications/{notification_id}", status_code=204)
def delete_notification(notification_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if not n or n.user_id != u.id:
        raise HTTPException(404, "Notification not found")
    db.delete(n)
    db.commit()


# =============================================================================
# Reminders
# =============================================================================

class ReminderIn(BaseModel):
    job_id: int
    reminder_type: str = Field(pattern="^(deadline|exam_date|result_expected|document_verification|medical|joining|custom)$")
    target_date: date
    offset_days: int = Field(default=0, ge=0, le=30)


@router.post("/reminders", status_code=201)
def create_reminder(payload: ReminderIn, u=Depends(current_user), db: Session = Depends(get_db)):
    if not db.get(Job, payload.job_id):
        raise HTTPException(404, "Job not found")
    fire_date = date.fromordinal(payload.target_date.toordinal() - payload.offset_days)
    reminder = ReminderRule(
        user_id=u.id, job_id=payload.job_id, reminder_type=payload.reminder_type,
        target_date=payload.target_date, offset_days=payload.offset_days, fire_date=fire_date, auto_created=False,
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder


@router.get("/reminders")
def list_reminders(u=Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(ReminderRule).where(ReminderRule.user_id == u.id).order_by(ReminderRule.fire_date)).all()


@router.delete("/reminders/{reminder_id}", status_code=204)
def delete_reminder(reminder_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(ReminderRule, reminder_id)
    if not r or r.user_id != u.id:
        raise HTTPException(404, "Reminder not found")
    db.delete(r)
    db.commit()


# =============================================================================
# Admin — queue, retry, stats, automation logs, templates, manual run
# =============================================================================

@router.get("/admin/notifications/queue", dependencies=[Depends(guard)])
def admin_notification_queue(
    status: str | None = None, channel: str | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = select(NotificationDeliveryLog)
    if status:
        q = q.where(NotificationDeliveryLog.status == status)
    if channel:
        q = q.where(NotificationDeliveryLog.channel == channel)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(NotificationDeliveryLog.id.desc()).offset(offset).limit(limit)).all()
    return {"items": rows, "total": total}


@router.post("/admin/notifications/{log_id}/retry", dependencies=[Depends(guard)])
def admin_retry_notification(log_id: int, db: Session = Depends(get_db)):
    """Re-attempts a failed delivery through the same channel. Only
    meaningful for `email` (in_app never fails after insertion; push/
    sms/whatsapp aren't implemented, so retrying one of those just
    re-confirms `not_implemented`)."""
    from app.models.domain import User
    from app.services.notification_channels import CHANNELS

    log = db.get(NotificationDeliveryLog, log_id)
    if not log:
        raise HTTPException(404, "Delivery log entry not found")
    if log.status not in ("failed", "not_implemented"):
        raise HTTPException(409, f"Only failed/not_implemented deliveries can be retried (status={log.status})")
    user = db.get(User, log.user_id)
    if not user:
        raise HTTPException(404, "User not found")
    channel = CHANNELS.get(log.channel)
    if not channel:
        raise HTTPException(400, f"Unknown channel {log.channel}")

    notif = db.get(Notification, log.notification_id) if log.notification_id else None
    title = notif.title if notif else "CareerOS notification"
    body = notif.message if notif else "You have a pending notification."
    result = channel.deliver(db, user, title=title, body=body, job_id=notif.job_id if notif else None)
    log.status = result.status
    log.provider = result.provider
    log.error = result.error
    log.attempt_count += 1
    if result.status == "sent":
        from datetime import datetime
        log.sent_at = datetime.utcnow()
    log_audit(db, action="retry_notification", entity_type="notification_delivery_log", entity_id=str(log_id))
    db.commit()
    return {"retried": True, "id": log_id, "status": log.status}


@router.get("/admin/notifications/stats", dependencies=[Depends(guard)])
def admin_notification_stats(db: Session = Depends(get_db)):
    by_status = dict(db.execute(
        select(NotificationDeliveryLog.status, func.count()).group_by(NotificationDeliveryLog.status)
    ).all())
    by_channel = dict(db.execute(
        select(NotificationDeliveryLog.channel, func.count()).group_by(NotificationDeliveryLog.channel)
    ).all())
    total_in_app = db.scalar(select(func.count()).select_from(Notification))
    unread_in_app = db.scalar(select(func.count()).select_from(Notification).where(Notification.read == False))  # noqa: E712
    return {"delivery_by_status": by_status, "delivery_by_channel": by_channel,
            "total_in_app_notifications": total_in_app, "unread_in_app_notifications": unread_in_app}


@router.get("/admin/email/overview", dependencies=[Depends(guard)])
def admin_email_overview(db: Session = Depends(get_db)):
    """V23.2 — minimal email delivery overview (spec section 19:
    "Do NOT build a huge analytics system yet" — this is deliberately
    just status counts + the most recent failures, not a dashboard)."""
    from app.models.domain import EmailMessage

    by_status = dict(db.execute(select(EmailMessage.status, func.count()).group_by(EmailMessage.status)).all())
    recent_failures = db.scalars(
        select(EmailMessage).where(EmailMessage.status == "FAILED").order_by(EmailMessage.failed_at.desc()).limit(20)
    ).all()
    return {
        "by_status": by_status,
        "recent_failures": [
            {
                "id": m.id, "template_key": m.template_key, "recipient": m.recipient,
                "attempts": m.attempts, "last_error": m.last_error,
                "failed_at": m.failed_at.isoformat() if m.failed_at else None,
            }
            for m in recent_failures
        ],
    }


@router.get("/admin/automation/logs", dependencies=[Depends(guard)])
def admin_automation_logs(
    trigger: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = select(AutomationLog)
    if trigger:
        q = q.where(AutomationLog.trigger == trigger)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(AutomationLog.id.desc()).offset(offset).limit(limit)).all()
    return {"items": rows, "total": total}


@router.post("/admin/automation/run", dependencies=[Depends(guard)])
def admin_run_automation(db: Session = Depends(get_db)):
    """Manual Run — the spec's Scheduler requirement. Runs the same
    automation scan + reminder sync/fire the scheduled job runs (see
    app/scheduler.py), synchronously, so an admin gets the result
    immediately instead of waiting for the next interval."""
    automation_result = automation_service.run_automation_scan(db)
    reminders_created = reminder_service.sync_auto_reminders(db)
    reminders_fired = reminder_service.fire_due_reminders(db)
    log_audit(db, action="manual_automation_run", entity_type="automation", detail=str(automation_result))
    db.commit()
    return {**automation_result, "reminders_created": reminders_created, "reminders_fired": reminders_fired}


@router.get("/admin/automation/health", dependencies=[Depends(guard)])
def admin_automation_health():
    """Scheduler — Health Monitoring: last run time/outcome for every
    background job, from the in-process bookkeeping in app/scheduler.py
    (_with_retry). Empty until each job has run at least once."""
    from app.scheduler import job_health

    return job_health


@router.post("/admin/automation/run/{job_id}", dependencies=[Depends(guard)])
def admin_run_single_job(job_id: str):
    """Scheduler — Manual Run for one specific background job (as
    opposed to POST /admin/automation/run, which always runs the
    automation+reminder pair together)."""
    from app.scheduler import run_job_now

    try:
        return run_job_now(job_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


# --- Templates -----------------------------------------------------------

class TemplateIn(BaseModel):
    subject: str | None = None
    body: str
    active: bool = True


@router.get("/admin/notification-templates", dependencies=[Depends(guard)])
def list_templates(db: Session = Depends(get_db)):
    return db.scalars(select(NotificationTemplate).order_by(NotificationTemplate.key, NotificationTemplate.channel)).all()


@router.put("/admin/notification-templates/{key}/{channel}")
def upsert_template(key: str, channel: str, payload: TemplateIn, _=Depends(guard), db: Session = Depends(get_db)):
    if channel not in ("in_app", "email"):
        raise HTTPException(422, "channel must be in_app or email")
    tmpl = db.scalar(select(NotificationTemplate).where(NotificationTemplate.key == key, NotificationTemplate.channel == channel))
    from datetime import datetime
    if tmpl:
        tmpl.subject = payload.subject
        tmpl.body = payload.body
        tmpl.active = payload.active
        tmpl.updated_at = datetime.utcnow()
    else:
        tmpl = NotificationTemplate(key=key, channel=channel, subject=payload.subject, body=payload.body, active=payload.active)
        db.add(tmpl)
    log_audit(db, action="upsert_notification_template", entity_type="notification_template", entity_id=f"{key}:{channel}")
    db.commit()
    db.refresh(tmpl)
    return tmpl


@router.get("/notification-template-keys")
def known_template_keys():
    """Every template key the automation/reminder engine can render
    against, for the admin Template Management UI's dropdown — avoids
    hardcoding this list a second time in the frontend."""
    return sorted(DEFAULT_TEMPLATES.keys())
