"""V23.1 — Notification Infrastructure & Event System.

Establishes a general-purpose, extensible notification foundation on
top of the existing V7/V19.4 ``Notification`` table (extended, not
duplicated — see its own docstring in app/models/domain.py) rather
than building a second notification system alongside the one that
already powers the Government Notification Center
(app/api/notification_engine.py).

    service.py     — NotificationService: create / list / unread-count
                      / mark-read / mark-unread / mark-all-read /
                      delete. Every function enforces ownership; none
                      trusts a caller-supplied user_id.
    events.py       — event-trigger functions (application_created,
                      application_status_changed, interview_scheduled,
                      interview_updated) called from
                      app.applications.service/interviews at the exact
                      point each real event happens. Each is a plain
                      Python function call, not a message broker —
                      deliberately simple (see events.py's own
                      docstring for why). Every call is wrapped by its
                      caller (or internally) so a notification failure
                      can never break the business operation that
                      triggered it.

This version is in-app only, same honest-scope rationale V7's
services/notifications.py already documented: no verified email/SMS
provider is wired up here, so nothing claims to have sent one. Email
delivery and richer alerting are explicitly out of scope — see
docs/V23_1_NOTIFICATION_INFRASTRUCTURE.md's "Extensibility" section
for how a future version adds a channel without touching this one's
call sites.
"""
