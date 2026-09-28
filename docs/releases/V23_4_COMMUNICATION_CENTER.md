# V23.4 — Communication Center, Interview & Deadline Reminders

One candidate-facing hub (`/communication`, `app/api/communication.py`)
aggregating what already exists — V22 Application/Interview/Task, V23.1
Notification, V23.3 JobAlertDelivery — plus one genuinely new
capability: a scheduled, idempotent reminder engine for interviews,
deadlines, and tasks, and an opt-in daily digest email. This version
adds exactly one new table (`notification_reminders`) and zero new
notification/email/task/interview storage — see "Why one new table"
below.

## Architecture

```
app/communication/
  priority.py    deterministic LOW/NORMAL/HIGH/URGENT scoring (no LLM)
  aggregator.py  read-only: summary / action-required / upcoming-timeline
  reminders.py   the scheduled scan: interviews, deadlines, tasks
  digest.py      the opt-in daily digest email

app/api/communication.py   GET summary/actions/upcoming/reminders,
                            POST reminders/run (admin-only)
app/models/domain.py        NotificationReminder (new table);
                            UserNotificationPreference.timezone /
                            .digest_enabled (new columns)
app/email/templates.py      INTERVIEW_REMINDER, DEADLINE_REMINDER,
                            TASK_DUE_REMINDER, DAILY_CAREER_DIGEST
app/scheduler.py             careeros_communication_reminders (15 min),
                            careeros_daily_digest (60 min)
frontend/src/app/communication/page.tsx   Overview / Notifications /
                            Upcoming / Action Required / Job Alerts /
                            Preferences tabs
frontend/src/lib/communication.ts
```

`aggregator.py` is read-only and queries existing tables directly
(`Application`, `ApplicationInterview`, `ApplicationTask`,
`JobAlertDelivery`) — it reuses `app.applications.service.
get_upcoming_deadlines` (V22.2) and `app.applications.ai.signals.
compute_signals` (V22.4) rather than re-deriving deadline urgency or
application health from scratch. The Notifications and Job Alerts tabs
in the frontend call the existing `/notifications/*` and `/job-alerts/*`
endpoints directly (via the existing `src/lib/notifications.ts` /
`src/lib/jobAlerts.ts`) rather than re-querying that data through
`/communication/*` a second way.

## Why one new table, not a reuse of V19.4's `ReminderRule`

V19.4's `reminder_rules` table is purpose-built for a single narrow
case: one date on a Government `Job`/`RecruitmentUpdate`, an
offset-in-days, fired through `app.services.reminder_engine`. This
version's reminders cover a structurally different set of sources (an
`ApplicationInterview`, an `Application` deadline, or an
`ApplicationTask` due date) with a different identity shape
(`source_type`/`source_id`/`reminder_type`/`scheduled_for` rather than
a `job_id` + `offset_days`), fired through the V23.1/V23.2
notification/email systems. Forcing this version's reminders into
`ReminderRule`'s shape would mean overloading its `job_id` foreign key
to sometimes mean "application id" or "task id" — a correctness risk
for no real benefit. The two systems intentionally coexist; see
`app.models.domain.NotificationReminder`'s own docstring.

## Reminder types and offsets

| Source | Reminder types |
|---|---|
| Interview (`ApplicationInterview`, result=SCHEDULED) | `24_HOURS_BEFORE`, `1_HOUR_BEFORE` |
| Deadline (`Application.deadline`, non-terminal status) | `7_DAYS_BEFORE`, `3_DAYS_BEFORE`, `1_DAY_BEFORE`, `DUE_TODAY`, `OVERDUE` (fires once, the day after) |
| Task (`ApplicationTask.due_at`, not completed) | `1_DAY_BEFORE`, `DUE_TODAY`, `OVERDUE` |

Tasks deliberately get a smaller offset set than deadlines — spec
section 25 ("avoid notification spam"): a task is lighter-weight than
a deadline and a 7/3-day heads-up for it would be noise.

**Scope decision**: deadline reminders cover `Application.deadline`
only, not `Job.deadline` for saved-but-not-applied-to jobs — V19.4's
`ReminderRule` already covers that case for government jobs. Extending
this version's deadline reminders to private-sector saved jobs as well
was out of scope for this pass; see "Known limitations."

## Idempotency (spec sections 6/15)

Every reminder's identity is `(source_type, source_id, reminder_type,
scheduled_for)`, computed once from the source row's own date. A
`NotificationReminder` row for that identity is inserted
(`status=PENDING`) *before* any `Notification`/`EmailMessage` is
created for it. A concurrent or retried worker either:

- loses the INSERT race on the table's `UNIQUE(source_type, source_id,
  reminder_type, scheduled_for)` constraint (the same pattern
  `app.notifications.service.create_notification` and
  `app.job_alerts.execution` already use for their own dedupe keys), or
- finds the identity already exists and skips straight to the next
  candidate.

A worker restart, a duplicate scheduler tick, or a manual re-run can
never create a second notification/email for the same reminder. This
is exercised directly in `tests/test_v23_4_communication_center.py::
test_interview_reminder_fires_once_and_is_idempotent_on_rerun`, which
calls `run_due_reminders` twice and asserts exactly one
`NotificationReminder` row and exactly one `Notification` exist
afterward.

A cancelled/failed/completed/deleted interview is never reminded —
`_scan_interviews` only considers `result == "SCHEDULED"` rows, so
cancelling an interview before its reminder fires produces zero
`NotificationReminder` rows for it, by construction (no separate
"is this cancelled" check needed at reminder time).

## Timezone handling (spec section 16)

Every timestamp this version reads or writes
(`ApplicationInterview.scheduled_at`, `Application.deadline`,
`ApplicationTask.due_at`, `NotificationReminder.scheduled_for`) is
naive UTC — exactly the existing storage convention from V22. This
version does not change that anywhere. `UserNotificationPreference.
timezone` (new column, default `"UTC"`, validated as a real IANA name
via Pydantic's `field_validator` in `app/api/notification_engine.py`)
is consulted for exactly one purpose: converting "now" to the
candidate's local hour to evaluate quiet hours
(`app.communication.reminders._local_hour`). If the stored value isn't
a recognized IANA name, this falls back to UTC and logs a warning
rather than raising — a reminder failure must never break the scan
(spec section 24).

## Quiet hours (spec section 17)

`UserNotificationPreference.quiet_hours_start`/`quiet_hours_end`
already existed (V19.4) but were never actually consulted before this
version. A reminder that is due but falls inside the recipient's
quiet-hours window (evaluated in their own timezone) is marked
`DELAYED`, not silently dropped and not sent. The next scan tick, once
quiet hours have passed, `_promote_delayed` rebuilds the same delivery
content fresh from current source data (so a promoted reminder never
replays stale wording) and delivers it, marking the row `SENT`.
**URGENT-priority reminders are never delayed** — an interview
starting within the hour, or a deadline that's already overdue, always
goes out immediately regardless of quiet hours (spec: "URGENT/
security-critical notifications may follow separate rules").

## Priority scoring (spec section 9)

`app.communication.priority.score_by_days_until` is a plain,
deterministic function of "days until the event" (negative = already
past): ≤1 day → `URGENT`, ≤3 → `HIGH`, ≤7 → `NORMAL`, beyond → `LOW`.
No LLM is involved in the score itself anywhere in this package.
`from_application_priority` maps V22.4's existing application-health
vocabulary (Low/Medium/High/Critical) onto the same four levels for
actions derived from `compute_signals`, so an application-derived
action's priority is always traceable back to the same signals V22.4
already computes.

## Notification / email integration

Reused verbatim: `app.notifications.service.create_notification` (with
a `dedupe_key`) and `app.email.service.queue_email` (with a
`dedupe_key` and `category`). No second notification or email table
was created. Four new email templates were added to the existing
`SEED_TEMPLATES` in `app/email/templates.py`:
`INTERVIEW_REMINDER`, `DEADLINE_REMINDER`, `TASK_DUE_REMINDER`, and
`DAILY_CAREER_DIGEST` (the digest reuses the same fixed-5-slot +
"and N more" pattern the existing `JOB_ALERT_DAILY` template already
established, since this template engine deliberately has no loop
syntax).

In-app delivery for `INTERVIEW`/`DEADLINE` categories checks
`notify_interview`/`notify_deadline` directly before calling
`create_notification` — mirroring `app.job_alerts.execution.
_in_app_enabled_for_job`'s documented workaround for a pre-existing
V23.1 gap (per-category in-app toggles are stored but not universally
enforced by `create_notification` itself). This version follows the
established workaround rather than fixing that gap, which is out of
this version's scope.

## Daily digest (spec section 12)

Opt-in via a new `UserNotificationPreference.digest_enabled` column
(default `False` — unlike every existing `email_*` flag, which
defaults `True` to preserve "notified exactly as before this column
existed"; a digest is brand-new bundled content nobody has ever
received, so there's no existing behavior to preserve). Built from the
exact same `aggregator.get_action_required` list the Action Required
tab shows — the digest is a restatement of that list by email, never a
second opinion about what matters. Never sent with no content (spec:
"Do NOT send empty emails"). Deduplicated per user per calendar day by
checking for an existing `EmailMessage` with that day's `dedupe_key`
*before* calling `queue_email` — note that `queue_email`'s own
dedupe-key handling returns the *existing* row (not `None`) on a
repeat call, so relying on its return value alone would have reported
"sent" on every repeat call; the pre-check in `digest.py` is what
actually makes `send_digest_for_user`'s return value mean "did I just
queue a new one."

## Preferences (spec section 13)

Extended the existing `PUT /notifications/preferences` endpoint
(`app/api/notification_engine.py`) with `timezone` and
`digest_enabled` fields — no second preferences endpoint or table.
Job alerts / application updates / interview reminders / deadline
reminders / AI recommendations already had in-app + email toggles from
V23.1/V23.2; only the digest and timezone were new. The existing
`/notifications/preferences` frontend page gained two new form fields
for these; the Communication Center's own Preferences tab links to
that one page rather than re-implementing the form.

## Security (spec section 26)

- Every `/communication/*` GET resolves the user from the verified JWT
  (`current_user`) and every aggregator/reminder query is scoped by
  that user's own id — never a caller-supplied `user_id`.
- `GET /communication/reminders` is the candidate's own reminder
  history only (`WHERE user_id == u.id`) — verified directly by
  `test_action_required_ownership_isolation`.
- `POST /communication/reminders/run` (spec section 20's "manual
  reminder-run endpoint... safely restricted") reuses the exact same
  shared-admin-key `guard` dependency every other manual-run endpoint
  in this codebase already requires (`app.api.admin.guard`), rather
  than exposing it to ordinary candidates or inventing a second
  admin-auth mechanism.
- Every `action_url` this version generates (`/applications/{id}`,
  `/jobs/{id}`) is already inside `app.notifications.service`'s
  existing safe-prefix allowlist — no allowlist change was needed.

## Performance (spec section 27)

New indexes added (additive only — see the migration):
`applications(deadline)`, `application_tasks(completed, due_at)`,
`application_interviews(result, scheduled_at)` — the reminder scan's
three global queries (across all users, since it's a background job,
not a per-request call) are index-backed lookups rather than full
table scans. The scan itself only ever runs on a schedule
(`app/scheduler.py`), never inside a normal page request. A late-
arrival grace window (6 hours) bounds how far in the past a
just-recovered scheduler will still fire interview reminders for,
preventing a flood of stale reminders after extended downtime.

## Known limitations

- **Not executed end-to-end in the authoring sandbox.** This
  environment has no outbound network access, so `pip install -r
  requirements.txt` (fastapi/sqlalchemy/etc. are not present) and
  `npm install` both fail with 403s from their registries, and the
  full `pytest`/`next build` suite could not run. What *was* actually
  executed, for real, against the real source files (not
  reimplemented copies):
  - `app.communication.priority` in full (zero external dependencies)
    — every boundary of `score_by_days_until` (LOW/NORMAL/HIGH/URGENT
    thresholds, `None`), `from_application_priority`'s full mapping
    including an unknown input, and `max_priority`.
  - `app.communication.reminders`'s pure timezone/quiet-hours logic —
    `_local_hour` (including an unrecognized-timezone fallback to
    UTC), `_in_quiet_hours` (normal window, overnight/wraparound
    window, zero-width "no quiet hours" case, no-preference-row case),
    `_time_phrase_for_days`, and `_priority_for_days` — by importing
    the real `reminders.py` module against minimal hand-written
    stand-ins for `sqlalchemy`/`app.models.domain`/`app.email.service`/
    `app.notifications.service` (just enough for the module to import
    successfully; none of its DB-touching functions were exercised
    this way).
  - The entire backend `py_compile`s cleanly and a standalone `tsc
    --noEmit` syntax pass on the new/edited frontend files reports no
    real syntax errors.
  Everything else (the full `pytest` suite, the DB-touching reminder
  scan/idempotency/delivery paths, `next build`) was verified only by
  manual line-by-line cross-checking against real function signatures,
  not by execution — reported as **NOT VERIFIED (execution)**, per the
  instruction not to fabricate validation. One real bug was caught and
  fixed this way before it could ship: relying on `queue_email`'s
  return value alone to mean "a new email was queued" is wrong (it
  returns the *existing* row on a duplicate `dedupe_key`, not `None`)
  — `digest.py` now pre-checks instead.
- Deadline reminders cover `Application.deadline` only, not
  `Job.deadline` for a saved-but-not-yet-applied-to private-sector job
  (V19.4's `ReminderRule` already covers this for government jobs).
- The reminder scan's deadline/task queries are global (all users per
  tick), matching the existing precedent in `app.job_alerts.execution`
  and `app.services.reminder_engine` — acceptable for a background job
  per spec section 27, but would benefit from batching/pagination at a
  much larger scale than this build was tested against (no real
  dataset size was available to benchmark in this sandbox either).
- The in-app `notify_interview`/`notify_deadline` gating in
  `_in_app_enabled` duplicates a documented pre-existing V23.1 gap
  (`create_notification` itself doesn't enforce these) rather than
  fixing that gap at its source — fixing it was out of scope for this
  version and risks changing behavior for every other V23.1 caller.

## Testing

`backend/tests/test_v23_4_communication_center.py` — 20 tests written,
covering: zero-state and populated summary counts, action-required
generation and priority ordering, ownership isolation, the upcoming
timeline's date bucketing, interview-reminder idempotency across two
`run_due_reminders` calls, no-reminder-for-cancelled-interview,
deadline-due-today reminders, quiet-hours boundary logic (unit-level)
and end-to-end (via `monkeypatch`, to stay deterministic regardless of
wall-clock time), digest opt-out / no-content / once-per-day, the
admin-gated manual reminder run, and the extended preferences
endpoint's timezone validation. See "Known limitations" above — these
were not executed in this sandbox; report status is **NOT VERIFIED**.

## Regression

Not independently re-run in this sandbox for the same reason (no
dependencies installable). Every change to shared/pre-existing files
in this version was additive: new columns with safe defaults, new
indexes, new dict entries, new router registration, new scheduler jobs
appended after the existing one. No existing function signature,
column, or route was removed or renamed. The one accidental regression
introduced mid-implementation (a stray edit briefly dropped the
pre-existing `ix_applications_user_applied_on` index) was caught during
this same session's review and restored — see the `Application`
model's `__table_args__`.
