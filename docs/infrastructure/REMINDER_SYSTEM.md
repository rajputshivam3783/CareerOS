# REMINDER_SYSTEM.md â€” V19.4

## What this is

`app/services/reminder_engine.py` â€” date-anchored nudges, distinct
from the event-anchored notifications in `AUTOMATION_ENGINE.md`. A
reminder fires because a date arrived, not because something changed.

## Auto-created reminders

`sync_auto_reminders(db)` â€” for every user who saved or applied to a
published Government job, ensures a `ReminderRule` exists at each
configured offset (currently a fixed default of **3 days before** and
**1 day before** â€” see `_DEFAULT_OFFSETS`; per-user/per-type offset
customization is left to the custom-reminder API below, see Known
Limitations) for every relevant date the job or its updates carry:

| `reminder_type` | Date source |
|---|---|
| `deadline` | `Job.deadline` |
| `exam_date` | `Job.exam_date` |
| `result_expected` | `Job.result_date` |
| `document_verification` | matching `RecruitmentUpdate.event_date` (`update_type="dv"`) |
| `medical` | matching `RecruitmentUpdate.event_date` (`update_type="medical"`) |
| `joining` | matching `RecruitmentUpdate.event_date` (`update_type="joining"`) |

`fire_date = target_date - offset_days`. Never backfills a reminder
whose `fire_date` has already passed, and never inserts a duplicate
`(user, job, reminder_type, target_date, offset_days)` combination â€”
safe to call `sync_auto_reminders` repeatedly (the scheduler does,
daily; see `AUTOMATION_ENGINE.md`).

## Firing reminders

`fire_due_reminders(db)` â€” any `ReminderRule` with `fired_at IS NULL`
and `fire_date <= today` gets delivered (in-app + email, per the
user's preferences) through the same channel abstraction
(`NOTIFICATION_ENGINE.md`) using the `reminder` template key, then
stamped `fired_at` so it's never delivered twice. Runs hourly alongside
the automation scan (`careeros_automation` scheduled job), so a
reminder due today doesn't wait a full day to actually go out.

## Custom reminders

`POST /reminders {job_id, reminder_type, target_date, offset_days}` â€”
a user can create one directly (`reminder_type` may also be `"custom"`
for anything not in the auto-created list, e.g. a future
ATS-integrated interview reminder). `auto_created=False` on these, so
`sync_auto_reminders` never touches or duplicates them.
`GET /reminders` / `DELETE /reminders/{id}` round out the API. UI:
not yet built as a dedicated page â€” reminders are currently
API-only + surfaced as notifications when they fire (see
`RELEASE_NOTES_V19_4.md`, Known Limitations).

## Known limitations, stated plainly

- **Offsets are a fixed 3-day/1-day default for every user**, not yet
  per-user-configurable beyond the manual "custom reminder" escape
  hatch. `UserNotificationPreference` doesn't carry an offsets field
  yet â€” adding one and wiring it into `_offsets_for` is a small,
  contained follow-up.
- **No dedicated "Manage my reminders" frontend page** â€” the API is
  complete and tested; the UI surface for it is Notification Center
  (reminders arrive there when they fire) rather than a separate
  reminders list page.
- Interview reminders ("future ATS integration" in the spec) have no
  automatic trigger yet since ATS wasn't touched this version â€” the
  `custom` reminder type already supports creating one manually once
  an interview is scheduled.

