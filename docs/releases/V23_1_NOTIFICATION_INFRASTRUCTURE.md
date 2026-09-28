# V23.1 — Notification Infrastructure & Event System

Establishes a general-purpose, extensible in-app notification
foundation and wires it into three real V22 events (application
created, application status changed, interview scheduled/updated).
Email delivery, job alerts, deadline/task reminders, and richer AI
alerts are explicitly out of scope — this version is the foundation
those build on later.

## Why this extends the existing `Notification` table instead of creating a new one

CareerOS already had a notification system: V7's `Notification` model
(deadline/admit-card/result alerts) and V19.4's Government Automation
& Notification Engine (`app/api/notification_engine.py` —
subscriptions, preferences, a notification center with search/status
filters, read/read-all/archive/delete, admin queue/retry/stats). Per
every V-series guardrail in this project ("do not create a second/
duplicate system"), V23.1 **extends** that table and reuses that API
surface rather than building a parallel one:

- `Notification` gains 7 new nullable/safely-defaulted columns
  (`category`, `priority`, `read_at`, `action_url`, `metadata_json`,
  `updated_at`, `dedupe_key`) via a new, additive migration —
  `notification_type`/`job_id`/`read`/`archived` (V7/V19.4) are
  unchanged and keep meaning exactly what they meant before.
- `UserNotificationPreference` (V19.4) gains 7 new boolean columns
  (`notify_job` … `notify_system`), one per V23.1 category — distinct
  from its existing `category_preferences` free-text field, which is
  government-job subscription filtering, a different concept.
- `POST /notifications/{id}/read`, `POST /notifications/read-all`, and
  `DELETE /notifications/{id}` (all V19.4) are **not** redefined —
  they already do exactly what this spec asks for, at the exact path
  this spec asks for. Only what was actually missing was added:
  `GET /notifications`, `GET /notifications/unread-count`, and
  `POST /notifications/{id}/unread`.

## Architecture

```
app/notifications/
    service.py   — NotificationService: create / create_bulk / list /
                    get_unread_count / mark_read / mark_unread /
                    mark_all_read / delete. Every function takes
                    user_id explicitly; none trusts a caller-supplied
                    id for anything it doesn't re-check.
    events.py    — event-trigger functions: application_created,
                    application_status_changed, interview_scheduled,
                    interview_updated. Plain function calls, not a
                    message broker (see events.py's own docstring for
                    why) — deliberately the simplest thing that gives
                    business logic a named, extensible hook instead of
                    building a Notification row inline.

app/api/notifications.py   — the 3 new endpoints (see above)
app/api/notification_engine.py — unmodified except PreferencesIn
                                  gaining the 7 new optional fields
                                  (the existing handler already applies
                                  any field via `model_dump(exclude_unset=True)`,
                                  so no endpoint logic changed)
```

## Event system

Business logic never builds a `Notification` row directly — it calls
a named function in `app.notifications.events`:

```python
# app/applications/service.py — create_application, after commit:
notification_events.application_created(db, record)

# app/applications/service.py — change_status, after commit:
notification_events.application_status_changed(
    db, record, old_status=old_status, new_status=new_status, history_id=history.id
)

# app/applications/interviews.py — create_interview / update_interview, after commit:
notification_events.interview_scheduled(db, user_id=user_id, application=application, interview=record)
notification_events.interview_updated(db, user_id=user_id, application=application, interview=record)
```

Each event function is a small, named, single-purpose translator from
"this specific thing happened" to a `NotificationService.
create_notification()` call — title, message, category, priority,
action_url, and dedupe_key all live in one place per event, not
scattered across the business-logic call sites. Adding a future event
(`TaskDue`, `ApplicationDeadlineApproaching`, `AIRecommendationGenerated`,
`JobSaved`, ...) means adding one function here and one call site
where that event actually happens — nothing else in the system needs
to change, since `NotificationService`, the API layer, and the
frontend bell/center all already work generically off `Notification.
category`/`priority`.

**At-minimum scope** (spec section 16): only application-created,
application-status-changed, and interview-scheduled/updated are wired
up this version. The other example events in the spec (`JobSaved`,
`TaskDue`, `ApplicationDeadlineApproaching`, `AIRecommendationGenerated`)
are named as the extensibility target, not implemented yet — complex
automatic reminders are explicitly a later V23 phase.

## Notification model

| Field | Source | Notes |
|---|---|---|
| `id`, `user_id`, `created_at` | V7 | unchanged |
| `notification_type` | V7 | specific type string, e.g. `"application_status_changed"` |
| `title`, `message` | V7 | unchanged |
| `read`, `archived` | V7 / V19.4 | unchanged |
| `job_id` | V7 | nullable; only set for job-alert-style notifications |
| `category` | **V23.1** | one of `JOB/APPLICATION/INTERVIEW/DEADLINE/RECRUITER/AI/SYSTEM`, nullable (NULL for pre-V23.1 rows) |
| `priority` | **V23.1** | one of `LOW/NORMAL/HIGH/URGENT`, defaults `NORMAL` |
| `read_at` | **V23.1** | set when marked read, cleared when marked unread |
| `action_url` | **V23.1** | always server-built, always validated (see Security) |
| `metadata_json` | **V23.1** | small structured extra data, e.g. `{"old_status": ..., "new_status": ...}` |
| `updated_at` | **V23.1** | |
| `dedupe_key` | **V23.1** | idempotency — see below |

## Idempotency

`Notification` has a `UNIQUE(user_id, dedupe_key)` constraint.
`NotificationService.create_notification()` pre-checks for an
existing row with the same key (cheap common case), and the DB
constraint is the actual guarantee under a race — a caught
`IntegrityError` is treated identically to a pre-check hit (rollback,
return `None`, no error surfaced). Multiple `NULL` values are always
allowed under a SQL `UNIQUE` constraint in both PostgreSQL and SQLite,
so every pre-V23.1 row (`dedupe_key IS NULL`) never collides with
anything, including each other.

Dedupe keys are built from something that changes only on a genuinely
new event, never on a retry of the same one:

- `application_created:{application_id}` — one per application, ever.
- `application_status_changed:{status_history_id}` — one per actual
  transition (`ApplicationStatusHistory` already gets exactly one row
  per real change — V22.1), so a retried API call for the *same*
  change can't double-notify, while a genuinely new transition (a new
  history row, a new id) always does.
- `interview_scheduled:{interview_id}` — one per interview.
- `interview_updated:{interview_id}:{updated_at.isoformat()}` — the
  record's own `updated_at`, set fresh by the ORM on every real write,
  naturally dedupes a retried identical PATCH while still notifying
  separately for each distinct edit.

This satisfies the spec's explicit "do not make the table globally
unique on message text" — the constraint is on a purpose-built key,
not on user-facing content.

## Failure handling

`app.notifications.events._safe_notify()` wraps every
`create_notification()` call in a bare `try/except Exception`, logs
the failure at `ERROR` with a stack trace (not silently swallowed —
see spec section 12's "do not silently swallow serious infrastructure
failures"), and never re-raises. Every call site in
`app/applications/service.py`/`interviews.py` is placed **after**
that function's own `db.commit()` — the business operation (create
application, change status, schedule/update interview) has already
succeeded and been persisted by the time the notification call even
starts, so a notification-layer exception can, by construction, never
roll back or fail the operation that triggered it. Verified by two
dedicated tests that monkeypatch `create_notification` to always
raise and assert the underlying application/status-change API call
still returns success (execution NOT VERIFIED — see Testing).

## API

```
GET  /api/v1/notifications                — NEW. ?unread_only, ?category, ?priority, ?limit, ?offset
GET  /api/v1/notifications/unread-count    — NEW. Single COUNT query.
POST /api/v1/notifications/{id}/read       — EXISTING (V19.4), unmodified
POST /api/v1/notifications/{id}/unread     — NEW.
POST /api/v1/notifications/read-all        — EXISTING (V19.4), unmodified
DELETE /api/v1/notifications/{id}          — EXISTING (V19.4), unmodified
GET  /api/v1/notifications/center          — EXISTING (V19.4), unmodified — a second, differently-
                                              filtered (search + notification_type + archived tab)
                                              read path over the same table, kept for the existing
                                              Notification Center page; both read through
                                              app.notifications.service-equivalent queries, no
                                              second data store.
GET/PUT /api/v1/notifications/preferences  — EXISTING (V19.4) endpoint, PATCHable body now also
                                              accepts the 7 new notify_* fields (additive only)
```

Every endpoint requires `current_user`; ownership is always
`Notification.user_id == current_user.id`, checked before any read/
write, mismatched or foreign ids return 404 (not 403), matching every
other V22 API's convention.

## Security

- **Ownership / IDOR**: every function in `NotificationService`
  re-checks `user_id` before touching a row; the API layer always
  derives `user_id` from the verified JWT, never a request parameter.
- **Deep links**: `action_url` is always built server-side inside
  `app.notifications.events` (never accepted from a client) and is
  additionally validated by `_validate_action_url()` before storage —
  must start with `/`, must not contain `://` or start with `//`, and
  must start with one of a small allowlist of known-safe internal
  route prefixes (`/applications/`, `/jobs/`, `/notifications`,
  `/interview/`, `/recruiter/`). This is defense in depth (the value
  is never client-controlled in the first place) rather than the
  primary defense.
- **No sensitive data leakage**: notification `title`/`message` are
  built from data the user already owns (their own application/
  interview); `metadata_json` only ever carries small, already-public-
  to-that-user fields (e.g. `old_status`/`new_status`, an
  `interview_id` that's already theirs) — never a token, password, or
  another user's data. Grepped `events.py` to confirm no such field is
  ever referenced.

## Performance

- `GET /notifications/unread-count` is a single `SELECT COUNT(*)`
  against `ix_notifications_user_id_read` — never loads notification
  rows to compute a count.
- `GET /notifications` is paginated (`limit`/`offset`, capped at 100)
  and indexed (`ix_notifications_user_id_created_at` for the default
  ordering, `ix_notifications_category`/`ix_notifications_priority`
  for the filters).
- `mark_all_read()` issues one `SELECT` + one `UPDATE`-per-row within
  a single transaction/commit, not N separate round trips.

## Testing

`backend/tests/test_v23_1_notification_infrastructure.py` covers:
event-triggered notification creation (application created/status-
changed, interview scheduled/updated) and that a status change never
double-fires both `application_created`-style and `application_status_
changed` notifications for the same creation-time history row;
listing with unread/category/priority filters and pagination;
`unread-count` matching the list endpoint's own count; the new
mark-unread endpoint plus the reused-unmodified read/read-all/delete
endpoints; ownership isolation (IDOR) across all of them; idempotency
(same `dedupe_key` twice → one row, no error); and — the two most
important tests in the file — that application creation and status
change both still return success even when `create_notification` is
monkeypatched to always raise.

**Execution status: NOT VERIFIED.** Same sandbox constraint as every
V22.x release note — no network egress (`pip install`/`npm install`
both 403, reconfirmed this session), so `pytest` could not actually
run. Every new/changed Python file passed `python -m py_compile`; the
import graph was manually traced for cycles (`app.notifications.*`
never imports from `app.applications.*`, only the reverse) and none
were found; every new frontend file was brace-balance-checked. Please
run `pytest backend/tests/test_v23_1_notification_infrastructure.py`
and the full existing suite, plus `npm run build`, in an environment
with registry access before deploying.
