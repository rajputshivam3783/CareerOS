# NOTIFICATION_ENGINE.md â€” V19.4

## What this is

The delivery layer of the V19.4 Automation & Notification Engine: a
channel abstraction (`app/services/notification_channels.py`), a
template renderer (`app/services/notification_templates.py`), and the
Notification Center API (`app/api/notification_engine.py`) users read
from. It does not decide *when* to notify someone â€” that's the
Automation Engine (see `AUTOMATION_ENGINE.md`) and Reminder Engine
(see `REMINDER_SYSTEM.md`), both of which call into this layer to
actually deliver an event once they've decided it's worth sending.

## Channel abstraction

Every channel implements one interface:

```python
class NotificationChannel:
    name: str
    implemented: bool
    def deliver(self, db, user, *, title, body, job_id=None) -> DeliveryResult: ...
```

| Channel | `implemented` | What it does |
|---|---|---|
| `in_app` | `True` | Inserts a row into the existing V7 `notifications` table |
| `email` | `True` | Calls the existing `app.services.email_service.send_email` (same SMTP wiring already used for OTPs and recruiter emails) |
| `push` | `False` | Returns `DeliveryResult(status="not_implemented")` â€” no FCM/APNs provider wired up |
| `sms` | `False` | Returns `not_implemented` â€” no SMS gateway wired up |
| `whatsapp` | `False` | Returns `not_implemented` â€” no WhatsApp Business API provider wired up |

**Adding a real Push/SMS/WhatsApp provider later** means writing one
new class in `notification_channels.py` with a working `deliver()`
and flipping `implemented = True` â€” nothing else in the engine
(preferences, delivery log, admin queue, automation, reminders)
changes, because they only ever call `CHANNELS[name].deliver(...)`.

Every delivery attempt â€” success, failure, or not-implemented â€” writes
one `NotificationDeliveryLog` row. This is deliberately separate from
the `Notification` table itself: `Notification` means "this user has
an in-app notification"; `NotificationDeliveryLog` means "did channel
X actually go out for this event, and if not, why."

## Templates

21 event keys, each with an `in_app` and an `email` variant, seeded
idempotently at app startup (`seed_default_templates` â€” only inserts
keys that don't exist yet, so an admin's edits are never clobbered by
a restart). Placeholders use `{name}` syntax and never raise on a
missing key (`_SafeDict` â€” an unrendered `{foo}` in the output is a
loud, debuggable failure mode; a 500 on a notification send is not).

Available placeholders (not every template uses every one):
`{title}` `{job_title}` `{organization}` `{event_date}` `{url}`
`{reminder_label}` (reminders only).

Admins manage templates via `GET/PUT /admin/notification-templates`
(also in the Admin console â€” `frontend/src/app/admin/notifications`,
Templates tab). `GET /notification-template-keys` (public) lists every
known key for that UI's dropdown.

## Notification Center

`GET /notifications/center?status=unread|read|archived|all&search=&notification_type=&limit=&offset=`
â€” replaces the minimal V7 notifications list at the same `/notifications`
route in the frontend. Returns `{items, total, unread_count, has_more}`.

Actions: `POST /notifications/{id}/read`, `POST /notifications/read-all`,
`POST /notifications/{id}/archive`, `DELETE /notifications/{id}`.

The pre-existing `GET /notifications` (plain V7 list) and
`GET /notifications/unread-count` (used by `Nav.tsx`'s badge) are
**unmodified** and still work â€” `/notifications/center` is additive,
not a replacement of those endpoints.

## Preferences

One row per user (`UserNotificationPreference`), created lazily on
first read or write, defaulted to "everything on, instant delivery" â€”
the exact behavior V7 already had, so a user who never visits
`/notifications/preferences` is notified exactly as before this
version existed.

`GET/PUT /notifications/preferences`:

| Field | Meaning |
|---|---|
| `email_enabled` / `in_app_enabled` | Per-channel on/off |
| `category_preferences` / `organization_preferences` | Free-text comma-separated filters (not currently enforced by the automation scan beyond subscriptions â€” reserved for a future narrowing pass) |
| `quiet_hours_start` / `quiet_hours_end` | Local-naive hour (0â€“23); email deliveries during quiet hours are logged as `skipped`, not sent. In-app delivery ignores quiet hours â€” it's pull, not push. |
| `digest_mode` | `instant` \| `daily_digest` \| `weekly_summary` â€” currently informational; every send is instant regardless of this value (see Known Limitations in `RELEASE_NOTES_V19_4.md`) |

## Admin tooling

`GET /admin/notifications/queue` (filter by `status`/`channel`),
`POST /admin/notifications/{id}/retry` (failed/not_implemented only),
`GET /admin/notifications/stats` (counts by status/channel).
All admin-key-gated (`Depends(guard)`, the same dependency
`app/api/admin.py` already uses â€” Security untouched).

