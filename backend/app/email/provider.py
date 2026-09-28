"""V23.2 — Email provider abstraction.

``EmailService`` (service.py) never opens a socket or knows what
"SMTP" means — it calls ``get_provider().send(message)``. Swapping in
a future provider (a transactional-email API, say) means adding one
class here and changing ``get_provider()``'s dispatch, with zero
changes to service.py, templates.py, or any call site.
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage as MimeEmailMessage

from app.core.config import settings

logger = logging.getLogger("careeros.email.provider")


class EmailSendError(Exception):
    """Raised on a delivery failure — always caught by
    service.py, which records it as a failed attempt and decides
    whether to retry. Never leaks a raw smtplib/socket exception or
    credential detail to a caller (message is a short, safe summary)."""


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    text_body: str
    html_body: str | None = None


class EmailProvider:
    name: str = "base"

    def send(self, message: OutgoingEmail) -> None:
        raise NotImplementedError


class ConsoleProvider(EmailProvider):
    """Dev-safe default (settings.email_mode == 'console'): renders
    and logs the email, never opens a network connection. This is the
    "EMAIL_MODE=console" mechanism spec section 13 asks for — nothing
    here can ever accidentally deliver a real email."""

    name = "console"

    def send(self, message: OutgoingEmail) -> None:
        logger.info(
            "CONSOLE EMAIL to=%s subject=%r\n--- text ---\n%s\n--- html ---\n%s",
            message.to, message.subject, message.text_body, message.html_body or "(none)",
        )


class SMTPProvider(EmailProvider):
    """Real delivery. Requires smtp_host + smtp_from_email — see
    get_provider() for the production-safety check (never silently
    falls back to console in production)."""

    name = "smtp"

    def send(self, message: OutgoingEmail) -> None:
        mime = MimeEmailMessage()
        mime["Subject"] = message.subject
        mime["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>" if settings.smtp_from_name else settings.smtp_from_email
        mime["To"] = message.to
        mime.set_content(message.text_body)
        if message.html_body:
            mime.add_alternative(message.html_body, subtype="html")
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                if settings.smtp_use_tls:
                    server.starttls()
                if settings.smtp_username:
                    server.login(settings.smtp_username, settings.smtp_password or "")
                server.send_message(mime)
        except (smtplib.SMTPException, OSError) as exc:
            # Never leak raw exception text (could include connection
            # details) beyond a short class-name summary — the full
            # exception is still logged server-side via logger.error.
            logger.error("SMTP send failed for template email to %s", message.to, exc_info=True)
            raise EmailSendError(f"SMTP delivery failed ({type(exc).__name__})") from exc


def get_provider() -> EmailProvider:
    if settings.email_mode == "smtp":
        if settings.is_production and (not settings.smtp_host or not settings.smtp_from_email):
            # Same guarantee app.services.email_service.send_email
            # already gives V16's OTP/offer emails: never silently
            # pretend an email was sent when SMTP isn't configured.
            raise RuntimeError("EMAIL_MODE=smtp but SMTP is not configured (SMTP_HOST/SMTP_FROM_EMAIL required)")
        return SMTPProvider()
    return ConsoleProvider()
