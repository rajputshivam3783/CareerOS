"""V23.1/V23.2 — Notification event triggers.

Deliberately plain function calls, not a message broker/event bus:
this project has one process, one database, and (per the V22.5 audit)
an explicit "do not prematurely complicate architecture" guardrail —
a full pub/sub layer would be solving a scaling problem this codebase
doesn't have yet. What this module *does* give the rest of the
codebase is the actual requirement: business logic (app.applications.
service, app.applications.interviews) never builds a Notification (or,
as of V23.2, an EmailMessage) directly — it calls one of these named
functions, which is where "what does this event mean, who does it
notify, on which channels, what's the dedupe key" lives, in one
place, extensibly (see this file's bottom for how a future event is
added).

FAILURE ISOLATION: every function here is a wrapper around
NotificationService.create_notification (and, as of V23.2,
app.email.service.queue_email) that catches *any* exception, logs it,
and returns — never re-raises. A notification/email failure must
never break the business operation that triggered it (an application
status change must succeed even if the notification/email insert
fails) — see app/applications/service.py's and interviews.py's call
sites, each of which calls straight into these functions with no
additional try/except of their own, because the safety is already
here.

V23.2 EMAIL SCOPE: only application_status_changed and
interview_scheduled queue an email (matching the spec's "at minimum"
list and the two dedicated templates that exist for them) —
application_created and interview_updated remain in-app-only this
version, same as before. queue_email() itself checks the recipient's
email preferences (app.email.preferences) before ever creating an
EmailMessage row — nothing here bypasses that.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.email import service as email_service
from app.models.domain import User
from app.notifications import service as notification_service

logger = logging.getLogger("careeros.notifications.events")


def _safe_notify(db: Session, event_name: str, *, email_template_key: str | None = None, email_variables: dict | None = None, **kwargs) -> None:
    try:
        notification_service.create_notification(db, **kwargs)
    except Exception:
        # Logged loudly (ERROR + stack trace), not silently swallowed —
        # just never re-raised, so the caller's own business operation
        # (already committed by the time these functions run — see
        # each call site) is unaffected either way.
        logger.error("Notification event %s failed for user_id=%s", event_name, kwargs.get("user_id"), exc_info=True)

    if email_template_key is None:
        return
    try:
        user = db.get(User, kwargs["user_id"])
        if user is None or not user.email:
            return
        email_service.queue_email(
            db,
            user_id=kwargs["user_id"],
            recipient=user.email,
            template_key=email_template_key,
            variables=email_variables or {},
            category=kwargs.get("category"),
            dedupe_key=kwargs.get("dedupe_key"),
        )
    except Exception:
        logger.error("Email queueing for event %s failed for user_id=%s", event_name, kwargs.get("user_id"), exc_info=True)


def application_created(db: Session, application) -> None:
    _safe_notify(
        db,
        "ApplicationCreated",
        user_id=application.user_id,
        notification_type="application_created",
        category="APPLICATION",
        priority="LOW",
        title="Application tracked",
        message=f"You're now tracking your application to {application.job_title} at {application.company}.",
        action_url=f"/applications/{application.id}",
        job_id=application.job_id,
        dedupe_key=f"application_created:{application.id}",
    )


def application_status_changed(db: Session, application, *, old_status: str | None, new_status: str, history_id: int) -> None:
    if old_status is None:
        return  # the creation-time history row is covered by application_created above, not a second notification
    priority = "HIGH" if new_status in ("OFFER", "INTERVIEW") else "NORMAL"
    old_label = old_status.replace("_", " ").title()
    new_label = new_status.replace("_", " ").title()
    dedupe_key = f"application_status_changed:{history_id}"
    _safe_notify(
        db,
        "ApplicationStatusChanged",
        user_id=application.user_id,
        notification_type="application_status_changed",
        category="APPLICATION",
        priority=priority,
        title=f"{application.company}: {new_label}",
        message=f"Your application to {application.job_title} at {application.company} moved from {old_label} to {new_label}.",
        action_url=f"/applications/{application.id}",
        job_id=application.job_id,
        metadata={"old_status": old_status, "new_status": new_status},
        dedupe_key=dedupe_key,
        email_template_key="APPLICATION_STATUS_CHANGED",
        email_variables={
            "user_name": _user_name(db, application.user_id),
            "job_title": application.job_title,
            "company_name": application.company,
            "application_status": new_label,
            "action_url": f"/applications/{application.id}",
        },
    )


def interview_scheduled(db: Session, *, user_id: int, application, interview) -> None:
    when = interview.scheduled_at.strftime("%b %d, %Y at %H:%M") if interview.scheduled_at else "a date to be confirmed"
    label = interview.round_name or interview.interview_type.replace("_", " ").title()
    dedupe_key = f"interview_scheduled:{interview.id}"
    _safe_notify(
        db,
        "InterviewScheduled",
        user_id=user_id,
        notification_type="interview_scheduled",
        category="INTERVIEW",
        priority="HIGH",
        title=f"Interview scheduled: {application.company}",
        message=f"{label} for {application.job_title} at {application.company} is scheduled for {when}.",
        action_url=f"/applications/{application.id}",
        job_id=application.job_id,
        metadata={"interview_id": interview.id},
        dedupe_key=dedupe_key,
        email_template_key="INTERVIEW_SCHEDULED",
        email_variables={
            "user_name": _user_name(db, user_id),
            "job_title": application.job_title,
            "company_name": application.company,
            "interview_date": when,
            "interview_type": interview.interview_type.replace("_", " ").title(),
            "action_url": f"/applications/{application.id}",
        },
    )


def interview_updated(db: Session, *, user_id: int, application, interview) -> None:
    label = interview.round_name or interview.interview_type.replace("_", " ").title()
    _safe_notify(
        db,
        "InterviewUpdated",
        user_id=user_id,
        notification_type="interview_updated",
        category="INTERVIEW",
        priority="NORMAL",
        title=f"Interview updated: {application.company}",
        message=f"{label} for {application.job_title} at {application.company} was updated (result: {interview.result}).",
        action_url=f"/applications/{application.id}",
        job_id=application.job_id,
        metadata={"interview_id": interview.id, "result": interview.result},
        # updated_at is set fresh by the caller on every real edit, so
        # this naturally dedupes a retried identical write while still
        # notifying separately for each distinct edit — same pattern
        # application_status_changed uses with a status-history row id.
        dedupe_key=f"interview_updated:{interview.id}:{interview.updated_at.isoformat()}",
    )


def _user_name(db: Session, user_id: int) -> str:
    user = db.get(User, user_id)
    return (user.full_name if user and user.full_name else None) or "there"


# --- Extensibility note -----------------------------------------------
# Adding a new event (e.g. TaskDue, ApplicationDeadlineApproaching,
# AIRecommendationGenerated, JobSaved, RecruiterMessageReceived — the
# spec's broader category list, deliberately not all wired up yet):
#   1. Add a function here following the same shape: build a title/
#      message/action_url/dedupe_key, call _safe_notify with a real
#      event_name string.
#   2. If it should also email, pass email_template_key (must be one
#      of app.email.templates.TEMPLATE_KEYS — SYSTEM_NOTIFICATION works
#      for anything without its own dedicated template) and
#      email_variables — _safe_notify handles the preference check,
#      the User lookup, and the same failure isolation the in-app
#      notification already gets.
#   3. Call it from wherever that event actually happens, no other
#      code needs to change — NotificationService, EmailService, the
#      API layer, and the frontend bell/center all already work off
#      Notification.category/priority generically.
