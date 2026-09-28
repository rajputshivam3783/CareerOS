"""V23.2 — Email Notification & Template Engine.

Builds a production-grade email layer on top of the existing V16/V19.4
transactional-email wiring (app.services.email_service.send_email) —
extends it, does not replace it: that module's send_otp/send_email
functions are untouched and still used directly nowhere new needs the
extra machinery here.

    provider.py     — EmailProvider abstraction: ConsoleProvider (dev-
                       safe, never opens a socket) and SMTPProvider
                       (wraps smtplib directly, same settings as
                       app.services.email_service). Selected by
                       settings.email_mode, never hardcoded.
    templates.py     — the 6 required system templates (seeded lazily
                       into SystemEmailTemplate, same pattern
                       app.api.email_templates already uses for
                       recruiter templates) + safe {{variable}}
                       rendering (HTML-escaped values, unknown
                       placeholders left untouched, required-variable
                       validation before render).
    preferences.py   — should_send_email(): the one place that checks
                       a category's email preference. Security-
                       critical sends never call this at all.
    service.py       — EmailService: queue_email / process_queue /
                       send_transactional_email / retry-with-backoff /
                       status tracking. The one place that creates or
                       updates an EmailMessage row.

FAILURE ISOLATION (spec section 9): every public function here that's
called from business logic (app.notifications.events,
app.api.auth) is wrapped so an email-layer exception can never
propagate into and fail the operation that triggered it — see
service.py's queue_email/send_transactional_email docstrings for
exactly where that boundary is.
"""
