# V23.3 — Smart Job Alerts & Personalized Job Notifications

Builds saved job alerts (INSTANT/DAILY/WEEKLY), a matching engine, and
a delivery pipeline (in-app + email) entirely on top of existing
infrastructure: V21.1 Search, V21.3/V21.4 Recommendations, V23.1
Notification Infrastructure, and V23.2 Email. No new ranking engine,
no new SMTP client, no new notification table, no LLM dependency.

## Why this is a new table, not a rename of the existing `Alert`

CareerOS already had a simple saved-search alert (V7, extended V19.4):
`Alert` / `alerts` table, `alert_type='job'`, one free-text `query`
column, checked by `app.services.notifications._check_saved_search_alerts`
on a schedule. **That system is untouched by V23.3** — same table,
same columns, same scheduled job, same behavior.

`JobAlert` / `job_alerts` is a deliberately separate, materially
richer concept: structured criteria across 14 fields (not one text
query), INSTANT/DAILY/WEEKLY frequency, an optional minimum relevance
threshold, an optional "use my profile" personalization toggle, and
its own durable run/delivery history. Overloading the existing
`Alert.query` string to carry all of that would have meant parsing a
mini-language out of free text, or adding 14 nullable columns to a
table whose whole design is "one text field" — a new table was the
smaller, safer change, and it's why every table/model name in this
feature is explicitly `JobAlert*`, never bare `Alert*`.

## Architecture

```
app/job_alerts/
    schemas.py     — pydantic request/response shapes
    service.py      — CRUD, ownership enforcement, preview/matches read paths
    matching.py     — the matching engine (see below)
    execution.py     — the delivery pipeline (see below)
app/api/job_alerts.py   — REST endpoints, mounted at /api/v1/job-alerts
migrations/v23_3_smart_job_alerts.sql — job_alerts, job_alert_runs,
    job_alert_deliveries (additive only; no existing table touched)
```

### Matching engine (`app.job_alerts.matching`)

Two stages, neither of which is a new ranking model:

1. **Structural candidate filtering.** A `JobAlert`'s criteria
   (keywords, title, skills, location, employment type, experience,
   salary, category, company, government/private, remote preference)
   become an `app.search.provider.SearchFilters` and run through the
   exact same `DatabaseSearchProvider` the interactive Search page
   uses (`SearchActor.anonymous()` — alerts only ever surface publicly
   visible/published jobs). `source` isn't an indexed `SearchFilters`
   field, so it's applied as a cheap in-memory filter over the
   already-bounded candidate set rather than widening that shared
   V21.1 dataclass for one V23.3-specific field.

   **New job detection** happens here too: candidates are filtered to
   `SearchIndexDocument.created_at > since` — the moment a job was
   *first indexed*. That timestamp does not move on a routine metadata
   edit (only `indexed_at` does), so a job that already matched once
   is never re-surfaced just because it was updated — this is what
   spec section 10 ("avoid alert storms caused by routine ingestion
   updates") actually needed, and it comes for free from a column the
   real-time indexing hooks (`app.search.hooks`) already maintain.

   `since` is `None` (no restriction) for two read-only paths that
   aren't delivery runs: the create-form's live preview and
   `GET .../matches`. It's `alert.last_run_at` for real delivery runs —
   and specifically **`None` on an alert's first run**, not
   `alert.created_at`: a freshly created alert should surface every
   currently-matching job, including ones that existed before the
   alert did. They're genuinely new *to this alert* (spec section 10's
   actual test), and the delivery-dedup table (below), not this
   filter, is what actually prevents re-notification later.

2. **Relevance scoring** — only over the (already small) structural
   candidate set:
   - `use_profile_personalization=True` (opt-in): calls
     `app.recommendations.service.get_single_recommendation` — the
     same per-job, per-user scoring V21.3/V21.4 already built —
     giving a 0-100 `overall_score` plus real skill/location
     explanations, at zero extra model-building cost.
   - Default (off): `app.search.ranking.score_document`, the same
     deterministic, non-AI ranking Search itself uses. Its raw
     `total_score` is explicitly documented as relative, not a
     percentage — this module owns the one normalization step
     (`round(total_score * 100)`) that turns it into the 0-100 display
     scale `min_relevance_score` is compared against, rather than
     exposing the internal number directly (spec section 7).

   Neither path calls an LLM (spec section 16) — both are
   deterministic, which is what makes deduplication sound: a rerun
   against the same data reaches the same verdict.

### Delivery pipeline (`app.job_alerts.execution`)

```
Job ingestion -> [real-time search indexing, already exists]
   -> Alert matching -> Relevance filtering -> Deduplication
   -> Notification event -> In-app notification / Email queue
```

- **In-app**: one `Notification` per matched job, for every frequency
  (dedupe_key `job_alert_match:{alert_id}:{job_id}`), gated on the
  user's `notify_job` preference.
- **Email**: INSTANT queues one email per matched job
  (`JOB_ALERT_INSTANT`, dedupe_key `job_alert_instant:{alert_id}:{job_id}`).
  DAILY/WEEKLY aggregate every newly-matched, not-yet-emailed job into
  **one** digest email (`JOB_ALERT_DAILY`/`JOB_ALERT_WEEKLY`,
  dedupe_key `job_alert_digest:{alert_id}:{run_id}`) — never one email
  per job. Both are gated on `email_job`.
- Both channels go through the existing `app.notifications.service`
  and `app.email.service` — this pipeline never touches SMTP directly.

### Deduplication & concurrency (spec sections 8, 22)

`job_alert_deliveries` — `UNIQUE(job_alert_id, job_id, channel)` — is
the single source of truth for "already delivered." It's written in
the same transaction as the delivery it records, so a concurrent or
retried worker loses the insert race at the database layer rather than
double-delivering (verified in tests by simulating two sessions racing
to insert the same row — see `test_concurrent_delivery_insert_does_not_duplicate`).
`Notification.dedupe_key`/`EmailMessage.dedupe_key` (V23.1/V23.2's own
idempotency keys) sit underneath as defense in depth.

No `SELECT ... FOR UPDATE` row lock is taken on `JobAlert` itself —
with the UNIQUE constraint already making a duplicate *delivery*
structurally impossible, a lock would only prevent two processes from
doing redundant (but harmless) matching work concurrently, an
efficiency question rather than a correctness one. Given this
codebase's Postgres/SQLite dual support, a portable advisory-lock
story wasn't judged worth the added complexity yet — see "Known
limitations" below.

### Scheduling (spec section 3)

`due_alerts()`: INSTANT alerts are due on every scheduler tick
(`job_alerts_interval_minutes`, default 5) — cheap and idempotent
since a tick with nothing new to alert on does no writes at all.
DAILY/WEEKLY are due once `now - last_run_at >= window`. Adding a new
frequency is one entry in `_FREQUENCY_WINDOW`, no redesign.

### Digest email template design note

`app/email/templates.py`'s engine deliberately has no
loop/conditional syntax and escapes every substituted value (a
security property, not an oversight — job titles/company names
ultimately come from scraped/recruiter-submitted data). A digest
therefore can't embed an arbitrary-length, pre-rendered job list as
one variable without either bypassing that escaping or adding loop
syntax the engine intentionally doesn't have. `JOB_ALERT_DAILY`/
`JOB_ALERT_WEEKLY` instead use a fixed block of `DIGEST_TOP_N` (5)
numbered placeholders (`job_1_title` … `job_5_reason`), each
independently escaped like any other variable, plus a plain
`more_count_text` for the rest — the "top relevant jobs" scope spec
section 11 asks for, with zero new injection surface. **Known
limitation**: if fewer than 5 jobs match, the unused slots render as
empty rows in the HTML layout (the engine has no way to conditionally
omit them) — cosmetic, not functional.

## API (spec section 18)

All under `/api/v1`, all requiring auth, all ownership-scoped:

```
POST   /job-alerts                    create
GET    /job-alerts                    list (own alerts only)
GET    /job-alerts/{id}               read
PATCH  /job-alerts/{id}                partial update
DELETE /job-alerts/{id}                delete
POST   /job-alerts/{id}/enable
POST   /job-alerts/{id}/disable
GET    /job-alerts/{id}/matches       current matches (no delivery)
GET    /job-alerts/{id}/history        JobAlertRun audit trail
GET    /job-alerts/{id}/preview        same as matches, for a saved alert
POST   /job-alerts/preview             preview an unsaved create-form payload
POST   /job-alerts/{id}/run-now        manual run — delivers for real
```

## Security (spec section 25)

Every service function re-checks `alert.user_id == caller.id` before
returning or mutating anything (`app.job_alerts.service._get_owned`) —
verified in tests: a second user gets 404 (not 403 — existence isn't
leaked) on every read/write/enable/disable/run-now/matches/history
call against another user's alert. Alert matching only ever queries
publicly visible (published) jobs via `SearchActor.anonymous()`, so an
alert can never surface a recruiter's unpublished draft.

## Known limitations / pre-existing issues found

- **Pre-existing bug, not introduced by V23.3, not fixed here**:
  `app/api/platform.py` defines its own V7 `GET /notifications` (and
  `POST .../read`) that is registered in `app.api.routes` **before**
  `app.api.notifications`' richer V23.1 versions of the same paths, so
  the V7 route silently wins — V23.1's `category` query-param
  filtering on `GET /notifications` is currently unreachable. This
  predates V23.3 (reproduced identically against the untouched V23.2
  baseline) and touches shared router registration order, so fixing it
  is out of scope for this alerts feature; V23.3's own tests query the
  `Notification` table directly rather than depend on that endpoint.
- **Pre-existing gap, not introduced by V23.3, not fixed here**:
  `app.notifications.service.create_notification` doesn't itself gate
  on `UserNotificationPreference` for *any* category — the
  `notify_job`/`notify_application`/etc. columns are stored and
  settable via the API but not read anywhere in V23.1. Changing that
  shared function would affect every existing notification event, well
  outside this feature's scope. `app.job_alerts.execution` checks
  `notify_job` itself before creating its own notifications, so job
  alerts at least honor their own spec requirement (section 13).
- DAILY/WEEKLY digest emails show up to 5 jobs by name; matches beyond
  that are summarized as "and N more" rather than listed individually
  (see template design note above).
- No portable cross-database advisory lock on `JobAlert` during
  execution (see Concurrency above) — correctness is guaranteed by the
  `job_alert_deliveries` UNIQUE constraint regardless; this only means
  two overlapping runs of the same alert can do some redundant
  (harmless) matching work.
- `remote_preference`/`govt_private_preference` are matched via the
  existing search index's `work_mode`/`job_type`-derived `entity_type`
  columns; jobs whose location text doesn't clearly indicate remote
  work rely on `Job.work_mode` being set correctly at ingestion,
  same as it already does for the interactive Search page.

## Testing

`backend/tests/test_v23_3_smart_job_alerts.py` — 35 tests, all run via
actual `pytest` invocations against a real (SQLite) database and a
real `TestClient`, no fabricated results:

CRUD, all-fields-optional creation, ownership isolation (IDOR) across
every endpoint, validation (frequency/blank name/salary range),
matching (positive and negative), preview, relevance threshold,
personalized matching (asserts a real recommendation-engine score and
skill-based explanation), instant delivery (notification + email),
run idempotency, delivery-table dedup, run history, daily digest,
weekly digest (exactly one email for N jobs), email-preference
gating, in-app-preference gating, both-disabled-but-still-matched,
disabled-alert exclusion from scheduling, DAILY/WEEKLY due-window
gating, failure handling (deactivated owner — FAILED status, safe
error summary, no stack trace, batch isolation), concurrent-delivery
race simulation, and a handful of regression checks against V7 saved
searches, V21.1 search, V21.3 recommendations, V23.1 notifications,
and V23.2 email queue processing.

Full-suite regression run: **646 passed** with V23.3 present vs **611
passed** on the untouched V23.2 baseline — exactly +35 (this feature's
test count), with the *same* 33 pre-existing failures / 13 pre-existing
errors in both runs (confirmed by running the identical `pytest tests/`
invocation against a separately-extracted, unmodified copy of the
V23.2 zip). Zero regressions attributable to V23.3.
