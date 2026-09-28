"""V19.4 — Notification template engine.

Templates live in the `notification_templates` table
(app.models.domain.NotificationTemplate) so an admin can edit copy
without a deploy; this module only renders them (`{placeholder}`
substitution against a plain dict, never raising on a missing key —
see `_SafeDict`) and seeds the defaults every alert type in the V19.4
spec needs the first time the app starts against a fresh database.

Two templates per event key (`{key}:in_app`, `{key}:email`) — an email
needs a subject line and reads better slightly longer; an in-app card
doesn't have either constraint.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import NotificationTemplate


class _SafeDict(dict):
    """Missing placeholders render as themselves (e.g. "{exam_date}")
    instead of raising — a template referencing a field this
    particular trigger didn't pass should degrade gracefully, not 500."""

    def __missing__(self, key):
        return "{" + key + "}"


def render(template: NotificationTemplate, context: dict) -> tuple[str | None, str]:
    """Returns (subject, body). subject is None for in_app templates."""
    safe = _SafeDict(**context)
    subject = template.subject.format_map(safe) if template.subject else None
    body = template.body.format_map(safe)
    return subject, body


# key -> {"in_app": (body,), "email": (subject, body)}
# Placeholders available to every trigger: {title} {organization}
# {job_title} {event_date} {url}. Individual triggers may pass extras
# (see app.services.automation) which simply won't be used by
# templates that don't reference them.
DEFAULT_TEMPLATES: dict[str, dict[str, tuple]] = {
    "new_notification": {
        "in_app": ("New notification for {job_title} at {organization}.",),
        "email": ("New notification: {job_title}",
                   "{organization} has posted a new update for {job_title}.\n\n{url}"),
    },
    "recruitment_published": {
        "in_app": ("New notification: {job_title} at {organization} was just published.",),
        "email": ("New recruitment notification: {job_title}",
                   "{organization} has published a new recruitment notification for {job_title}. Check the details and apply before the deadline.\n\n{url}"),
    },
    "application_open": {
        "in_app": ("Applications are open for {job_title} at {organization}.",),
        "email": ("Applications open: {job_title}",
                   "You can now apply for {job_title} at {organization}.\n\n{url}"),
    },
    "application_closing_soon": {
        "in_app": ("Closing soon: {job_title} applications close on {event_date}.",),
        "email": ("Applications closing soon: {job_title}",
                   "The application window for {job_title} at {organization} closes on {event_date}. Don't miss it.\n\n{url}"),
    },
    "correction_window": {
        "in_app": ("Correction window open for {job_title} — {event_date}.",),
        "email": ("Application correction window: {job_title}",
                   "{organization} has opened a correction window for {job_title}, closing {event_date}.\n\n{url}"),
    },
    "exam_date": {
        "in_app": ("Exam date announced for {job_title}: {event_date}.",),
        "email": ("Exam date announced: {job_title}",
                   "{organization} has announced the exam date for {job_title}: {event_date}.\n\n{url}"),
    },
    "exam_reminder": {
        "in_app": ("Reminder: your {job_title} exam is on {event_date}.",),
        "email": ("Exam reminder: {job_title}",
                   "This is a reminder that your exam for {job_title} at {organization} is on {event_date}. All the best!\n\n{url}"),
    },
    "city_intimation": {
        "in_app": ("Exam city intimation released for {job_title}.",),
        "email": ("Exam city intimation slip: {job_title}",
                   "The exam city intimation slip for {job_title} at {organization} is now available.\n\n{url}"),
    },
    "admit_card": {
        "in_app": ("Admit card released for {job_title}.",),
        "email": ("Admit card released: {job_title}",
                   "The admit card for {job_title} at {organization} is now available for download.\n\n{url}"),
    },
    "answer_key": {
        "in_app": ("Provisional answer key released for {job_title}.",),
        "email": ("Answer key released: {job_title}",
                   "{organization} has released the provisional answer key for {job_title}.\n\n{url}"),
    },
    "objection_window": {
        "in_app": ("Objection window open for {job_title} answer key.",),
        "email": ("Answer key objection window open: {job_title}",
                   "You can raise objections to the {job_title} answer key until the window closes.\n\n{url}"),
    },
    "final_answer_key": {
        "in_app": ("Final answer key released for {job_title}.",),
        "email": ("Final answer key released: {job_title}",
                   "{organization} has released the final answer key for {job_title}.\n\n{url}"),
    },
    "result": {
        "in_app": ("Result declared for {job_title}.",),
        "email": ("Result declared: {job_title}",
                   "The result for {job_title} at {organization} has been declared.\n\n{url}"),
    },
    "score_card": {
        "in_app": ("Score card available for {job_title}.",),
        "email": ("Score card available: {job_title}",
                   "Your score card for {job_title} at {organization} is now available.\n\n{url}"),
    },
    "cutoff": {
        "in_app": ("Cutoff marks published for {job_title}.",),
        "email": ("Cutoff marks published: {job_title}",
                   "{organization} has published cutoff marks for {job_title}.\n\n{url}"),
    },
    "merit_list": {
        "in_app": ("Merit list published for {job_title}.",),
        "email": ("Merit list published: {job_title}",
                   "{organization} has published the merit list for {job_title}.\n\n{url}"),
    },
    "document_verification": {
        "in_app": ("Document verification scheduled for {job_title} — {event_date}.",),
        "email": ("Document verification: {job_title}",
                   "Document verification for {job_title} at {organization} is scheduled for {event_date}. Please carry all originals.\n\n{url}"),
    },
    "medical_examination": {
        "in_app": ("Medical examination scheduled for {job_title} — {event_date}.",),
        "email": ("Medical examination: {job_title}",
                   "Your medical examination for {job_title} at {organization} is scheduled for {event_date}.\n\n{url}"),
    },
    "joining": {
        "in_app": ("Joining instructions released for {job_title}.",),
        "email": ("Joining instructions: {job_title}",
                   "Joining instructions for {job_title} at {organization} are now available.\n\n{url}"),
    },
    "recruitment_cancelled": {
        "in_app": ("{job_title} at {organization} has been cancelled.",),
        "email": ("Recruitment cancelled: {job_title}",
                   "{organization} has officially cancelled the recruitment for {job_title}.\n\n{url}"),
    },
    "deadline_extended": {
        "in_app": ("Deadline extended for {job_title} — now {event_date}.",),
        "email": ("Deadline extended: {job_title}",
                   "The application deadline for {job_title} at {organization} has been extended to {event_date}.\n\n{url}"),
    },
    "reminder": {
        "in_app": ("Reminder: {reminder_label} for {job_title} — {event_date}.",),
        "email": ("Reminder: {reminder_label} — {job_title}",
                   "This is a reminder that {reminder_label} for {job_title} at {organization} is on {event_date}.\n\n{url}"),
    },
    "subscription_match": {
        "in_app": ("New recruitment matching your subscription: {job_title} at {organization}.",),
        "email": ("New recruitment matches your subscription: {job_title}",
                   "A new recruitment matching one of your subscriptions was just published: {job_title} at {organization}.\n\n{url}"),
    },
}


def seed_default_templates(db: Session) -> int:
    """Idempotent — inserts only templates that don't already exist by
    (key, channel), so an admin's edits to an existing template are
    never overwritten by a re-seed on the next app startup."""
    existing = set(db.execute(select(NotificationTemplate.key, NotificationTemplate.channel)).all())
    created = 0
    for key, channels in DEFAULT_TEMPLATES.items():
        if (key, "in_app") not in existing:
            (body,) = channels["in_app"]
            db.add(NotificationTemplate(key=key, channel="in_app", subject=None, body=body))
            created += 1
        if (key, "email") not in existing:
            subject, body = channels["email"]
            db.add(NotificationTemplate(key=key, channel="email", subject=subject, body=body))
            created += 1
    if created:
        db.commit()
    return created


def get_template(db: Session, key: str, channel: str) -> NotificationTemplate | None:
    return db.scalar(
        select(NotificationTemplate).where(
            NotificationTemplate.key == key, NotificationTemplate.channel == channel, NotificationTemplate.active == True  # noqa: E712
        )
    )
