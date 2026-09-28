"""V23.4 — Communication Center, Interview & Deadline Reminders.

Aggregates data that already lives in V22 (Application/Interview/
Task), V23.1 (Notification), V23.2 (Email), and V23.3 (JobAlert) into
one candidate-facing view (``app.api.communication``), and adds one
new capability none of those versions had: a scheduled, idempotent
reminder engine for interviews, deadlines, and tasks
(``app.communication.reminders``) plus an optional daily digest email
(``app.communication.digest``).

This package deliberately owns exactly one new table
(``NotificationReminder`` — see app.models.domain) and zero new
notification/email/task/interview storage. Every read here goes
straight to the existing tables; every write (a reminder's own
bookkeeping row, plus calls into the existing
``app.notifications.service`` / ``app.email.service``) follows the
same ownership and idempotency rules those modules already established.

Module map:
    priority.py   — deterministic LOW/NORMAL/HIGH/URGENT scoring
    aggregator.py — summary / action-required / upcoming-timeline queries
    reminders.py  — the scheduled reminder scan (interviews/deadlines/tasks)
    digest.py     — the optional daily email digest
"""
