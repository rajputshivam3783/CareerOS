"""V19.4 — Notification channel abstraction.

Every delivery channel implements the same tiny interface
(`NotificationChannel.deliver`), so app.services.automation can fan a
single event out to however many channels a user has enabled without
knowing anything about SMTP, push tokens, or SMS gateways itself.

Only In-App and Email are fully implemented, per the V19.4 spec:

  * `InAppChannel` — inserts the existing V7 `Notification` row
    (app.models.domain.Notification). This is the one that must never
    fail silently, since it's still this project's only guaranteed-
    delivered channel (see app/services/notifications.py's docstring).
  * `EmailChannel` — reuses app.services.email_service.send_email
    as-is (the same SMTP wiring that already sends OTPs and recruiter/
    applicant emails), rather than a second implementation.

`PushChannel`, `SMSChannel`, `WhatsAppChannel` below are the
"interfaces for future channels" the spec asks for: registered in
CHANNELS so the rest of the engine (preferences, delivery log, admin
queue) already has a slot for them, but deliberately not implemented —
`deliver()` returns a `not_implemented` DeliveryResult instead of
pretending to send something. Wiring in a real provider later means
writing one new class here and nothing else in the engine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.domain import Notification, User

logger = logging.getLogger("careeros.notification_channels")


@dataclass
class DeliveryResult:
    status: str  # sent / failed / skipped / not_implemented
    provider: str
    error: str | None = None
    notification_id: int | None = None  # set when this delivery created/reused an in-app Notification row


class NotificationChannel:
    """Base interface every channel implements."""

    name: str = "base"
    implemented: bool = False

    def deliver(self, db: Session, user: User, *, title: str, body: str, job_id: int | None = None) -> DeliveryResult:
        raise NotImplementedError


class InAppChannel(NotificationChannel):
    name = "in_app"
    implemented = True

    def deliver(self, db: Session, user: User, *, title: str, body: str, job_id: int | None = None) -> DeliveryResult:
        row = Notification(user_id=user.id, job_id=job_id, notification_type="automation", title=title[:220], message=body)
        db.add(row)
        db.flush()  # assigns row.id without committing the caller's transaction
        return DeliveryResult(status="sent", provider="in_app_db", notification_id=row.id)


class EmailChannel(NotificationChannel):
    name = "email"
    implemented = True

    def deliver(self, db: Session, user: User, *, title: str, body: str, job_id: int | None = None) -> DeliveryResult:
        from app.services.email_service import send_email  # local import — mirrors email_service's own lazy-dependency style

        try:
            send_email(user.email, title, body)
            return DeliveryResult(status="sent", provider="smtp")
        except Exception as exc:  # never let a bad SMTP config break the in-app delivery this ran alongside
            logger.warning("Email delivery failed for user %s: %s", user.id, exc)
            return DeliveryResult(status="failed", provider="smtp", error=str(exc)[:500])


class PushChannel(NotificationChannel):
    """Future-ready — no push provider (FCM/APNs/etc.) is wired up
    yet. Deliberately raises no exception and sends nothing real."""

    name = "push"
    implemented = False

    def deliver(self, db: Session, user: User, *, title: str, body: str, job_id: int | None = None) -> DeliveryResult:
        return DeliveryResult(status="not_implemented", provider="push")


class SMSChannel(NotificationChannel):
    """Future-ready — no SMS gateway is wired up yet."""

    name = "sms"
    implemented = False

    def deliver(self, db: Session, user: User, *, title: str, body: str, job_id: int | None = None) -> DeliveryResult:
        return DeliveryResult(status="not_implemented", provider="sms")


class WhatsAppChannel(NotificationChannel):
    """Future-ready — no WhatsApp Business API provider is wired up yet."""

    name = "whatsapp"
    implemented = False

    def deliver(self, db: Session, user: User, *, title: str, body: str, job_id: int | None = None) -> DeliveryResult:
        return DeliveryResult(status="not_implemented", provider="whatsapp")


CHANNELS: dict[str, NotificationChannel] = {
    c.name: c for c in (InAppChannel(), EmailChannel(), PushChannel(), SMSChannel(), WhatsAppChannel())
}
