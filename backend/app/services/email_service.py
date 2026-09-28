"""Transactional email used for account verification and (V16)
applicant/offer notifications."""

import logging
import smtplib
from email.message import EmailMessage
from app.core.config import settings

log = logging.getLogger("careeros.email")


def send_otp(email: str, code: str, purpose: str = "verify_email") -> None:
    subject = "CareerOS verification code" if purpose == "verify_email" else "CareerOS password reset code"
    action = "email verification" if purpose == "verify_email" else "password reset"
    body = f"Your CareerOS {action} code is {code}. It expires in {settings.email_otp_minutes} minutes. If you did not request this, ignore this email."
    send_email(email, subject, body)


def send_email(to: str, subject: str, body: str) -> None:
    """V16 — general-purpose transactional email, factored out of
    send_otp so applicant-status/offer-letter notifications (V16
    recruiter ATS) can reuse the same SMTP wiring and dev-mode
    fallback instead of a second implementation.

    Same production guarantee as send_otp: never silently pretend an
    email was sent when SMTP isn't configured — raise instead, so a
    real deployment can't ship with notifications quietly no-op'ing.
    """
    if not settings.smtp_host or not settings.smtp_from_email:
        if settings.is_production:
            raise RuntimeError("SMTP is not configured")
        log.warning("DEV EMAIL to %s: %s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from_email
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password or "")
        server.send_message(msg)
