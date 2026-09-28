# V23 — Production Audit

Full audit of V23.1–V23.4 as one architecture, performed for the
V23.5 stabilization release. Every claim below was checked by reading
the actual code and/or running actual tests — see
`docs/V23_BUG_REPORT.md` for the 5 confirmed defects this audit found
and fixed, and `docs/V23_RELEASE_CHECKLIST.md` for the itemized
PASS/FAIL/NOT VERIFIED status of every audit area below.

## 1. One architecture — audit result

| Concern | Finding |
|---|---|
| One notification system | **Mostly true, one gap closed.** `Notification` (the table) and `app.notifications.service` are the single notification store/API. BUG-2 (see bug report) was a routing bug that made 4 of its own endpoints unreachable — fixed. `app.services.notification_channels.InAppChannel` (V19.4) writes to the *same* `Notification` table through the same model, so it's a second **caller**, not a second **store** — no duplicate table. |
| One email system | **Two code paths, documented.** `app/email/service.py` (V23.2, queued/templated/retried) is used by everything V23.1+ built. `app/services/email_service.py` (V16, direct `smtplib`) still has two live callers: `app/api/recruiter.py` (given failure isolation in BUG-3) and `app/services/notification_channels.py` (V19.4 government-job automation). Auth's OTP flow was already migrated onto V23.2. See Known Limitations. |
| One preference system | **True.** `UserNotificationPreference` is the only preference table. All 7 categories (JOB/APPLICATION/INTERVIEW/DEADLINE/RECRUITER/AI/SYSTEM) x 2 channels (in-app/email) live there, plus V23.4's `timezone`, `quiet_hours_start/end`, `digest_enabled`. No duplicate preference table exists anywhere in the codebase. |
| One job-alert system | **True.** `JobAlert`/`job_alerts` (V23.3) is deliberately distinct from the pre-existing `Alert`/`alerts` (V7/V19.4 simple saved-search) — see `docs/V23_3_SMART_JOB_ALERTS.md` for why that's a legitimate two-concept split, not a duplicate. |
| One reminder system | **Two systems, non-overlapping, documented.** See Known Limitations item 2 in the bug report. `app.services.reminder_engine` (V19.4, government job dates) and `app.communication.reminders` (V23.4, application/interview/task) operate on disjoint source data — confirmed no double-notification for the same event. |
| One event architecture | **True for V23.1+.** `app.notifications.events` is the single event-to-notification integration point for application/interview/job-alert/deadline events introduced from V22 onward. |

## 2. Database audit

- **Migration ordering:** `scripts/run_migrations.py` applies
  `migrations/*.sql` in filename-sorted order (`v16_*` through
  `v23_4_*`); each file uses `CREATE ... IF NOT EXISTS` /
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, so re-running the full
  set against an already-migrated database is a safe no-op. No
  historical migration was modified in this release.
- **Clean migration from an empty database:** verified — a fresh
  SQLite database created via `Base.metadata.create_all()` (the dev/
  test path) now succeeds cleanly after BUG-1's fix; the equivalent
  Postgres `.sql` migrations were confirmed to parse into valid,
  discrete statements via the project's own `_split_statements` helper
  (actual execution against a live Postgres instance is NOT VERIFIED —
  no Postgres server available in this environment; see Release
  Checklist).
- **Foreign keys / cascade behavior:** `NotificationReminder.user_id`
  -> `users.id` (`CASCADE`), `.notification_id` -> `notifications.id`
  (`SET NULL`), `.email_message_id` -> `email_messages.id`
  (`SET NULL`) — a reminder row survives its linked notification/email
  being deleted (orphan-safe), but is itself deleted if its owning user
  is deleted. Consistent with `JobAlertDelivery`'s existing pattern.
- **Uniqueness/idempotency constraints:** `JobAlertDelivery`
  `UNIQUE(job_alert_id, job_id, channel)` and `NotificationReminder`
  `UNIQUE(user_id, source_type, source_id, reminder_type)` — both
  verified under simulated concurrent-insert races (two separate
  sessions racing to insert the same row; loser gets `IntegrityError`,
  rolls back, returns the winner's row).
- **Nullable fields:** every `JobAlert` criteria field and every
  `NotificationReminder.notification_id`/`.email_message_id` is
  correctly nullable (optional criteria; a reminder whose in-app or
  email leg was skipped by preference still has a valid row).
- **Indexes:** `(status, scheduled_for)` composite index on
  `notification_reminders` backs the delivery pass's core query
  (due, pending reminders); `(enabled, frequency)` on `job_alerts`
  backs the scheduler's due-alert query. BUG-1 (duplicate index) was
  the only index-related defect found.
- **Orphan prevention:** all V23.3/V23.4 tables reference `users.id`
  with `ON DELETE CASCADE` — deleting a user cannot leave orphaned
  alerts, deliveries, runs, or reminders.

## 3. Notification audit

Creation, retrieval, unread count, mark read/unread, mark-all-read,
pagination, filtering (category), and priority were all exercised by
`tests/test_v23_1_notification_infrastructure.py` (14/14 passing after
BUG-2's fix) and directly, live, via `TestClient` during this audit.
Deletion: `DELETE /api/v1/notifications/{id}` exists in
`app.api.notification_engine`, ownership-scoped. Deep links: covered
by `_validate_action_url`'s allowlist (see bug report's confirmed-safe
findings). **IDOR:** explicitly tested — a second user's JWT against
another user's notification-related endpoints returns 401/403/404 as
appropriate, never another user's data.

## 4. Event system audit

Every event integration point (`app.notifications.events`) follows one
documented pattern: the business operation's `db.commit()` happens
first, notification/email side effects are attempted after and are
individually wrapped so one failing side effect doesn't affect
another or roll back the original operation. BUG-3 was exactly one
place (`app.api.recruiter`, a V16 module outside `app.notifications.events`'s
scope) that didn't yet have this isolation — fixed. Retry safety and
event idempotency: `dedupe_key` (Notification, EmailMessage) and the
`JobAlertDelivery`/`NotificationReminder` unique constraints are the
two idempotency mechanisms in use; both were exercised under
simulated retries/concurrent workers in this audit and in the
V23.3/V23.4 test suites.

## 5-6. Email system audit & delivery reliability

Provider abstraction (`app.email.provider`), template rendering
(`app.email.templates`, variable substitution + HTML escaping +
required-variable validation), queue (`EmailMessage`, states QUEUED ->
PROCESSING -> SENT/FAILED), and retry (`app.email.service._deliver`,
exponential backoff, `max_attempts` cap — no infinite retry) were all
re-verified as part of this audit (`test_v23_2_email_system.py`,
14/14 — 2 were fixed test-fixture-ordering issues, not production
bugs, see bug report). Confirmed: `_deliver` catches broad `Exception`
around the entire render+send path, so a template error, a provider
error, or a malformed header value is recorded as a failed attempt
with retry, never crashes the queue worker or leaks past
`process_queue`. Duplicate-email prevention: `dedupe_key`'s unique
constraint, confirmed via job-alert and reminder idempotency tests —
a re-run never re-queues an email for the same identity.

## 7-8. Email & auth email security

See `docs/V23_BUG_REPORT.md`'s "Confirmed-safe findings" section for
the full header-injection, recipient-source, action-URL, and
template-escaping review — all confirmed safe by direct testing, not
assumption. Auth email: `app.api.auth` uses
`app.email.service.send_transactional_email` (bypasses ordinary
category preferences, per spec — security-critical mail is never
user-disable-able); OTP tokens are not logged. Token expiration/
single-use behavior: unchanged from the pre-existing auth
implementation — **not redesigned**, per this release's explicit
guardrail.

## 9-10. Job alert audit & scale

Full CRUD/matching/dedup/history functionality re-verified
(`test_v23_3_smart_job_alerts.py`, 37/37 — 35 original + 2 new rate-
limit tests from this release, see BUG-5). Matching engine reuses V21
search (`DatabaseSearchProvider`, capped candidate retrieval, never a
full table scan) and V21.3 recommendations (only over the already-
bounded candidate set, never every-user-times-every-job) — see
`docs/V23_3_SMART_JOB_ALERTS.md`'s architecture section for the full
two-stage design. New-job detection uses `SearchIndexDocument.created_at`,
which does not move on a routine metadata update, so unchanged jobs
never re-trigger a match. BUG-5 (no rate limit on the 3
expensive-work endpoints) was the one confirmed scale/abuse gap;
fixed.

## 11. Reminder engine audit

Interview/deadline/task/digest scheduling and delivery all re-verified
live and via `test_v23_4_communication_center.py` (17/17, stress-run
3x to rule out flakiness, plus 2x in combination with the full V23
group). Cancelled/completed/failed interviews are confirmed excluded
by construction (`_scan_interviews` only considers `result in
{"SCHEDULED", "RESCHEDULED"}`). Idempotency: `NotificationReminder`'s
unique constraint + get-or-update-in-place semantics (a rescheduled
interview updates the existing PENDING row's `scheduled_for` rather
than creating a duplicate). Retries: reminder creation/delivery are
both safe to re-run (confirmed: a second `run_due_reminders()` call
against the same data creates and sends nothing new).

## 12. Timezone audit

`app.communication.reminders` stores and reasons about all reminder
timestamps in UTC; `UserNotificationPreference.timezone` (IANA name,
default `"UTC"`) is consulted for exactly one purpose — deciding
whether "now" falls inside a user's configured quiet hours — via
Python's standard `zoneinfo` (DST-aware by construction, since
`zoneinfo` resolves offsets from the IANA tz database rather than a
fixed UTC offset). This is a deliberate, narrower scope than "every
timestamp is timezone-converted for display," and is documented as
such in `app.communication.reminders`' own module docstring. One
related test (`test_upcoming_buckets_items_by_date`) was found to be
flaky around UTC-day boundaries — a test bug, not a scheduling bug
(the Upcoming view's TODAY/TOMORROW bucketing is itself UTC-date-based
by the same documented convention) — fixed to assert against whichever
bucket is actually correct for the moment it runs, rather than a
hardcoded one.

## 13. Quiet hours audit

`app.services.automation._quiet_hours_active` (pre-existing V19.4
helper, reused rather than reimplemented) is consulted by
`app.communication.reminders` before sending a non-urgent reminder
email: during quiet hours, the reminder is left `PENDING` (not marked
sent, not deleted) so the next scheduler tick after quiet hours end
retries it — nothing is silently dropped. In-app notifications are
created regardless of quiet hours (a passive inbox entry, not an
interruption — same precedent V19.4's own delivery logic already
established: only the email channel is quiet-hours-gated).
URGENT-priority reminders bypass the delay entirely, per spec.

## 14. Daily digest audit

`app.communication.digest` builds content from real
interview/deadline/task/application data, sends nothing when there is
no meaningful content (an explicit early-return before
`queue_email(...)` is ever called), is gated on
`UserNotificationPreference.digest_enabled` (via
`email_preferences.should_send_email(..., "DIGEST")`), and uses a
per-day `dedupe_key` so a second scheduler tick on the same day never
double-sends. Template `DAILY_CAREER_DIGEST` reused, with a plain-text
fallback confirmed present in `app.email.templates`.

## 15. Communication Center audit

`/communication` and its 4 backing endpoints
(`/summary`, `/actions`, `/upcoming`, `/reminders`) were live-tested
for IDOR and confirmed to read exclusively from existing tables
(`Notification`, `Application`, `ApplicationInterview`,
`ApplicationTask`, `JobAlert`/`JobAlertDelivery`) with no parallel
storage.

`POST /communication/reminders/run` was confirmed to already require
the admin key (`Depends(guard)`), not an ordinary candidate JWT —
live-tested: a candidate's own JWT gets `403`, no auth gets `401`, the
admin key gets `200`. This is a correctly-scoped manual-trigger
endpoint, matching spec section 20's "only expose ... if safely
restricted."

## 16. Preferences audit

One table (`UserNotificationPreference`), 7 categories x 2 channels,
plus V23.4's timezone/quiet-hours/digest additions — all confirmed via
direct schema read. Update: `PUT /notifications/preferences`,
ownership-scoped by the JWT's own user id (never trusts a client-
supplied user id). Security-critical exception: email verification and
password reset always go through `send_transactional_email`, which
does not consult `should_send_email` at all.

## 17. Security audit

See `docs/V23_BUG_REPORT.md` in full — this is where every finding
(confirmed and confirmed-safe) is recorded, including the live IDOR
test against the entire Communication Center API, the header-injection
empirical test, the action-URL allowlist review, and BUG-5's rate-
limiting fix. No SQL injection surface was found in any V23.1-V23.4
query (all use SQLAlchemy's parameterized query builder — no raw
string-interpolated SQL exists in any of the four subsystems audited).
No mass-assignment issue: every write endpoint uses an explicit
pydantic schema, never applying a raw request body directly onto a
model.

## 18. API audit

Every V23.1-V23.4 endpoint uses pydantic request models (validation),
ownership-scoped queries (never a client-supplied user id), and
correct HTTP status codes (404 for not-found/not-owned — never 403,
which would leak existence; 401 for unauthenticated; 429 for rate-
limited, added in BUG-5; 422 for validation errors — all confirmed via
live requests during this audit). OpenAPI: `GET /openapi.json`
confirmed valid JSON with every `/job-alerts*` and `/communication*`
path present.

## 19. Performance audit

Reviewed for N+1 queries and unbounded scans: `app.job_alerts.matching`
bounds candidate retrieval via `DatabaseSearchProvider`'s existing cap
(never a full job-table scan); `app.communication.aggregator`'s
summary/upcoming/actions queries are scoped by `user_id` with
appropriate date-range filters; `app.communication.reminders`' scan
functions filter by `result`/`status` and a due-date window before
touching any row, rather than iterating every interview/task/
application in the database. No new N+1 pattern was found in V23.3/
V23.4 code during this review. No unnecessary LLM calls: both job-
alert matching and communication priority scoring are explicitly
deterministic-first (LLM only for optional, non-blocking explanation
text).

## 20. Worker / concurrency audit

Simulated concurrent-insert races against both `JobAlertDelivery` and
the reminder pipeline's delivery bookkeeping — in both cases the
losing session's `IntegrityError` is caught, rolled back, and treated
as "already delivered by the other worker," never a duplicate
notification/email. `app/scheduler.py`'s own Dockerfile-documented
constraint (`WEB_CONCURRENCY=1` unless `SCHEDULER_ENABLED=false` on
every worker but one) prevents the simpler failure mode of two
in-process schedulers running the same job concurrently in the first
place. Full end-to-end worker-restart simulation against a live
multi-process Postgres deployment is **NOT VERIFIED** — no such
environment available here; the unique-constraint-level protection is
verified and is what actually guarantees correctness regardless of
process topology.

## 21. Frontend audit

`tsc --noEmit`: clean. `next build`: succeeds, all 57 routes compiled
including `/communication`, `/job-alerts`, `/job-alerts/[id]`,
`/notifications`, `/notifications/preferences`. Loading/error/empty
states: present in `/communication`'s page component (every one of
its 4 data-fetching sections has its own loading/error/empty branch).
Linting: **NOT VERIFIED** — no lint script or config exists anywhere
in this frontend project. Browser console errors: **NOT VERIFIED** —
no real browser is available in this environment; a clean production
build (which fails on React errors that would otherwise surface at
runtime) is the closest available signal. Accessibility/keyboard
navigation: **NOT VERIFIED** — would require manual or automated
(axe/Lighthouse) browser testing, neither available here.

## 22. Email template audit

All 13 templates named in the spec exist in `app.email.templates`'s
`SEED_TEMPLATES` and were confirmed present via a live
`get_or_seed_template()` call for each key. Variable substitution,
escaping, and required-variable validation are shared across every
template (one rendering function — not reimplemented per-template),
so the header-injection and HTML-escaping checks in the bug report's
confirmed-safe section cover all 13, not just the ones directly
tested. Malformed template data cannot crash delivery: `_deliver`'s
broad exception handling catches a `TemplateError` (missing/invalid
variable) the same as any other rendering failure.

## 23. Database performance (indexes)

Verified via direct schema/model read (not `EXPLAIN`, since this audit
ran against SQLite where actual query plans differ from production
Postgres — see Release Checklist): notifications indexed on `user_id`,
`read`, `created_at`; `job_alerts` indexed on `user_id`, `enabled`,
`frequency`, and the composite `(enabled, frequency)`;
`job_alert_deliveries` indexed on `job_alert_id`, `job_id`, `user_id`;
`notification_reminders` indexed on `user_id`, `source_type`,
`source_id`, `reminder_type`, `scheduled_for`, `status`, and the
composite `(status, scheduled_for)`; `email_messages` indexed on
status and scheduled-send fields (pre-existing V23.2 work, confirmed
still present); `user_notification_preferences` is keyed directly by
`user_id` (primary key — no separate index needed). No blind/
unnecessary index was added in this release beyond what BUG-1 already
required removing a duplicate of.

## Summary

This audit found and fixed 5 confirmed defects (1 critical, 1 severe,
3 real) and closed 1 minor completeness gap (action-URL allowlist), on
top of confirming a substantial list of security/architecture
properties were already correctly implemented. See
`docs/V23_BUG_REPORT.md` for full detail on each, and
`docs/V23_RELEASE_CHECKLIST.md` for the itemized validation status of
every area listed above.
