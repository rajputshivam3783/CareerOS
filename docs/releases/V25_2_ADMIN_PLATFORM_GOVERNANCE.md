# V25.2 — Advanced Admin & Platform Governance

This version turns CareerOS's accumulated admin endpoints into a
production-grade platform governance layer: an explicit platform-admin
permission model, real user/organization/job lifecycle controls, an
append-only governance audit trail, honest system-health reporting,
typed platform settings, and a maintenance mode.

Everything here is additive. V1–V25.1 functionality is unchanged
except for three deliberate, documented adjustments listed under
[Backward compatibility](#backward-compatibility).

---

## 1. Platform-admin architecture

```
PLATFORM
  ├── Platform administrators        ← User.role      (this document)
  ├── Organizations                  ← organizations
  │     ├── OWNER                    ← organization_members  (V25.1)
  │     ├── ADMIN                    ← organization_members  (V25.1)
  │     └── RECRUITER                ← organization_members  (V25.1)
  ├── Candidates
  ├── Jobs
  └── Applications
```

**The invariant this version exists to guarantee:**

> Organization authority and platform authority are two separate
> systems. Being OWNER or ADMIN of an organization grants nothing at
> the platform level, and no organization role can be escalated into
> one.

That is structural, not a check someone could forget to write:

| | Platform authority | Organization authority |
|---|---|---|
| Source of truth | `users.role` | `organization_members.role` |
| Module | `app/core/platform_admin.py` | `app/core/organizations.py` |
| Values | `admin`, `super_admin`, `system_admin`, `support_admin` | `OWNER`, `ADMIN`, `RECRUITER` |
| Reads the other's table? | **No** | **No** |

`platform_permissions_for_role()` has no wildcard branch: an unknown
role — including every organization role name — returns the empty set.
There is no code path in which promoting someone to OWNER changes what
`require_platform_permission` returns.

### Relationship to the existing RBAC layer

`app/core/rbac.py` (V16/V17.3) is untouched and still owns the
**endpoint-action** permission catalog (`jobs.publish`,
`sessions.revoke`, …). V25.2 adds a **capability-domain** layer above
it, because every route in the governance API has to answer one
question — "can this account administer the platform at all, in this
area?" — and expressing that as a union of thirty endpoint-level
strings at every call site would be unreadable and easy to get wrong.

Both layers key off the same `users.role` column. Neither file reads
the other's contents.

---

## 2. Roles and permissions

### Permission domains

| Permission | Grants |
|---|---|
| `USER_MANAGEMENT` | View, search, suspend, reactivate accounts |
| `ORGANIZATION_MANAGEMENT` | View, search, suspend, reactivate organizations |
| `JOB_MODERATION` | Review, approve, reject, suspend, restore listings |
| `CONTENT_MODERATION` | Platform announcements and content moderation |
| `AUDIT_ACCESS` | Read the audit trail and security events |
| `PLATFORM_ANALYTICS` | View aggregate analytics and the dashboard |
| `SYSTEM_CONFIGURATION` | System health and platform settings |

### Role grants

| Role | Permissions |
|---|---|
| `super_admin` | All seven |
| `admin` | All seven |
| `system_admin` | All except `SYSTEM_CONFIGURATION` |
| `support_admin` | `USER_MANAGEMENT`, `AUDIT_ACCESS` |
| everything else | *(none)* |

`system_admin` and `support_admin` already existed (V17.3). They are
mapped here to the domains matching the endpoint grants they already
held, so **this version gives no role a capability it did not already
have.**

### Sensitive actions (second gate)

A small set of actions requires `admin`/`super_admin` specifically,
not merely the relevant domain permission:

- suspending or deactivating an organization
- deactivating a user account
- suspending another platform administrator
- changing any setting flagged `sensitive` (including maintenance mode)
- sending a platform announcement

Rationale: a `support_admin` holding `USER_MANAGEMENT` must not be
able to disable the accounts that could reverse their own actions.

### Authentication

Dual-mode, unchanged from how the admin surface has worked since V16:

1. `Authorization: Bearer <jwt>` — the same token `/auth/login`
   issues, verified with the same secret. A suspended account fails
   here exactly as it does everywhere else, because `User.active` is
   checked identically.
2. `X-Admin-Key` — the shared break-glass credential. Rate-limited
   (bucket `admin-key`). A full bypass, consistent with how it is
   treated throughout this codebase.

No second authentication system was created (spec section 25).

**A denied JWT request is recorded as a `privilege_escalation_attempt`
security event** before the 403, so a recruiter or organization owner
probing `/admin` leaves an investigable trail. The event records role
and requested permission only — never a token or credential.

---

## 3. Admin dashboard — `/admin`

`GET /api/v1/admin/dashboard`. Every figure is a live `COUNT`.

Users (total/active/suspended/verified/candidates/recruiters/pending
recruiter approvals/platform admins/new in 30d), organizations
(total/active/suspended/verified/pending verification/pending
invitations/new in 30d), jobs
(total/published/pending review/rejected/suspended/closed/past
deadline/new in 30d), applications (total/active/new in 30d/hired),
and the last ten platform-admin actions.

**Omitted metrics are declared, not silently dropped.** The response
carries an `omitted_metrics` map explaining each:

| Metric | Why it is not reported |
|---|---|
| `active_users` | CareerOS records session creation, not per-request activity. "Users with a session in the period" is reported instead, under that honest name. |
| `expired_jobs` | Expiry is not a stored status; a past-deadline listing keeps `status='published'`. Reported as `published_past_deadline`, computed from the deadline column. |
| `demographics` | Not implemented by design. No protected characteristics are stored and none are inferred. |

---

## 4. User management — `/admin/users`

`GET /admin/users` supports search (email/name), and filters by role,
account status, email-verified and organization membership, with
pagination capped at 100 per page.

### Never returned

Password hashes, OTPs, verification codes, access/refresh tokens,
resume content, uploaded documents, private application notes, or any
candidate material. The serializer (`_user_summary`) is an explicit
allow-list of account-administration facts.

`GET /admin/users/{id}` adds organization memberships (each labelled
`organization_role` and `membership_status`, clearly distinct from
`platform_account_status`) and activity **counts** — how many
applications exist, never what is in them.

---

## 5. User account lifecycle

`ACTIVE` → `SUSPENDED` → `ACTIVE`, and `ACTIVE` → `DEACTIVATED` →
`ACTIVE`. Both end-states are reversible; nothing is destroyed to
disable access.

`users.account_status` is the explicit, queryable label.
`users.active` remains the single flag every authentication path
checks. `app/core/platform_lifecycle.py` keeps them in lockstep — if
they ever disagreed, the flag that governs access is still the old,
well-tested one, so the failure mode is a wrong label in the UI rather
than a security hole. For rows written before this column existed, the
status is *derived* from `active` + `suspended_at` rather than
backfilled by guesswork.

### Exact suspension behaviour

**A suspended user:**
- cannot authenticate — existing access tokens stop working on the next request, refresh fails, login fails;
- has their live sessions revoked (best-effort; `active=False` is the actual guarantee);
- keeps every application, status history entry, notification, document and audit record, untouched;
- keeps every organization membership, untouched. Removing someone from an organization is a separate, organization-level workflow with its own authorization;
- is never told the moderation reason — it is internal.

**On reactivation:** `active=True`, status `ACTIVE`, suspension fields
cleared, `failed_login_count` reset. `lock_count` is deliberately
**not** reset — it is the escalation counter for automatic lockout
durations, and clearing it would reward an attacker for having got an
account suspended.

**Self-suspension is refused outright.** Suspending another platform
administrator requires a full platform-admin role.

---

## 6–7. Organization management and suspension

`GET /admin/organizations` — search by name/slug, filter by status and
verification status, paginated; each row carries member, job and
application counts.

`GET /admin/organizations/{id}` adds the member list, each member
showing their organization role *and* their platform account status as
two separate, separately-labelled facts.

### Exact suspension behaviour

| Aspect | Behaviour |
|---|---|
| Organization record | `is_active=False`, `status=SUSPENDED` (or `DEACTIVATED`), reason recorded. **Nothing is deleted.** |
| Member access | Every `/organizations/{id}/…` route fails closed with **404**, identical to a nonexistent organization — the V25.1 dependency already checked `is_active`, so suspension takes effect through one existing check rather than a new one added to every route. |
| Jobs | Every **published** job owned by an active member moves to `suspended`, tagged `moderation_reason='organization_suspended'`, with its prior status recorded. Jobs in review/rejected/closed are left alone. |
| Applications | **Untouched and still accessible.** A candidate's own history must not disappear because a company was suspended. |
| Member accounts | **Untouched.** Being in a suspended organization is not misconduct by the individual. |
| Notifications | None are sent. No candidate or member is told the reason. |
| Error messages | Carry no moderation detail — a suspension must not leak information (verified by test). |

**On reactivation:** `is_active=True`, status `ACTIVE`, and every job
suspended *by that suspension* is restored to the exact status it held
beforehand. A job an administrator suspended individually, for its own
policy violation, **stays suspended** — reactivating the company must
not silently undo an unrelated moderation decision.

*Job ownership note:* a `Job` has no organization FK
(`Job.organization_id` points at `government_organizations`, a
different table). "This organization's jobs" runs through
`Job.owner_user_id` ∈ active member ids — the same relationship
`app/core/team_access.py` already uses, so there is one definition of
it, not two.

---

## 8–9. Job moderation

One publication system, not two. The V9 review workflow is unchanged
in shape; V25.2 moved the *bodies* of the transitions into
`app/services/job_moderation.py`, and `app/api/admin.py`'s original
`publish`/`reject` routes now call it.

```
review ──approve──▶ published ──suspend──▶ suspended ──restore──▶ published
  │                                            ▲
  └──reject──▶ rejected ──restore──▶ review    │
                                  (organization suspension also lands
                                   jobs here, tagged for exact restore)
```

`suspended` is a new **value** of the existing `jobs.status` column,
not a new column — the same pattern V14/V16 used for new role and
update_type values. Consequence: every existing query filtering
`status == 'published'` (search indexing, public job lists, candidate
views) excludes suspended jobs automatically, with no code change and
no risk of one being missed.

### Moderation reasons

`policy_violation`, `incomplete_information`, `misleading_information`,
`duplicate_listing`, `prohibited_content`, `suspicious_activity`,
`spam`, `expired`, `other`.

| Field | Recruiter sees it? |
|---|---|
| `moderation_reason` (structured code) | **Yes** — a recruiter is entitled to know why |
| `moderation_note` (admin free text) | **No** — platform-admin surface only |
| `moderated_by_user_id` | **No** |

`GET /admin/moderation/reasons` serves the vocabularies to the UI, so
the dropdowns are generated from the backend's validation list rather
than a hardcoded copy that could drift.

**Restore never auto-publishes.** A job with no recorded prior status
(e.g. rejected before V25.2) returns to `review` — back into the queue
for a human decision, the safe direction.

**Double-suspension is refused (409)** because it would overwrite the
restore point and leave the job unrestorable.

---

## 10–12. Audit logging

### Why a separate table

`platform_audit_logs` sits alongside, not instead of, the V16
`audit_logs` table. Both are written for every admin action.

`audit_logs` is a high-volume application-wide trail whose rows carry
one free-text `detail`. A governance record must answer a fixed set of
investigative questions — which administrator, which target, which
organization, what structured reason, what outcome — and be filterable
on each **independently**. Encoding those into `detail` as free text
would make every filter a substring scan.

### Recorded

actor (user id + type + label) · action · target type · target id ·
organization id · timestamp · structured reason · internal note ·
sanitized metadata · result (`success`/`failure`/`partial`) ·
request id · IP.

### Append-only

`record_platform_action` is the **only** writer anywhere in the
codebase. No route, service or script issues an `UPDATE` or `DELETE`
against the table. The guarantee holds because no code capable of
violating it exists — not because of a permission check that could be
misconfigured.

**Optional database-level hardening:** grant the application's DB role
`INSERT, SELECT` only on `platform_audit_logs`. CareerOS does not
require this, and does not do it automatically, because the same role
runs migrations.

**Retention:** no deletion mechanism is provided. A deployment with a
legal retention obligation should implement it as a separate,
operator-run, separately-credentialed job — deliberately outside the
application, so "the admin UI can delete audit history" never becomes
true by accident.

### Metadata sanitization

`_safe_metadata` drops keys containing `password`, `token`, `secret`,
`otp`, `api_key`, `hash`, `credential`, `resume`, `document`,
`session`, `cookie`, `authorization`; truncates long strings; caps key
count; and summarizes long lists as `{count, sample}` so a 5,000-item
bulk operation writes a count, not 5,000 ids. An audit trail that
becomes a copy of the data it audits is a liability.

### Per-resource history (section 12)

`GET /admin/users/{id}/history`, `/organizations/{id}/history`,
`/jobs/{id}/history` are **filtered reads of the same table** — no
duplicate per-resource history tables.

---

## 13. Platform search

`GET /admin/search?q=…&entities=users,organizations,jobs,applications`

Separate scoped ORM queries per entity, parameterized via SQLAlchemy —
never string-concatenated SQL, and **never a unified raw-SQL
endpoint**. Each entity block re-checks the caller's permission for
that domain, so a `support_admin` gets user hits and no organization
hits rather than a blanket 403.

Applications are searchable **only by the job they belong to**. There
is no way to search application content or candidate material from the
admin surface.

---

## 14–15. Analytics and privacy

`GET /admin/analytics?days=N` (capped at 365; default 30).

Users (registrations over time, by role, by status, verified,
sessions-in-period) · organizations (created over time, by
verification, with active hiring) · jobs (created/published over time,
by status, by moderation reason, past deadline) · applications (over
time, by status, by pipeline stage, by job status, highest-volume
listings).

Time series are **dense** — every day in range, zero-filled — so the
frontend never has to guess whether a missing day means zero or
missing data.

### Privacy rules

- Aggregates only. No function returns a candidate's identity, resume,
  application content, notes, documents or contact details.
- Top-N lists are keyed by **organization** or **job**, never by
  person.
- **No demographic analytics.** CareerOS stores no protected
  characteristics, and this version introduces no proxy for one — no
  name analysis, no location-based inference, no age derivation.
- The only individuals named anywhere are **administrators** in the
  audit feed, acting in an official capacity. That is the point of an
  audit trail.

---

## 16–18. System health

`GET /admin/system/health` · `/system/background-jobs` ·
`/system/ingestion`

### Four states, and `unknown` is first-class

| State | Meaning |
|---|---|
| `ok` | Checked, and it worked |
| `degraded` | Checked, partly working or behind |
| `error` | Checked, and it failed |
| `unknown` | **Not checked** — this deployment has no way to check it |

A deployment with no AI provider configured is not unhealthy; it has
no AI provider. Reporting `ok` would be a fabricated green light;
reporting `error` would page someone about a feature they chose not to
enable. `unknown` indicators **do not degrade the overall status**.

### Indicators

`api` · `database` (connectivity + latency + driver family) ·
`migrations` · `scheduler` · `email` · `ai_provider` ·
`notifications` · `ingestion`

**Migration status:** CareerOS uses plain SQL files plus
`scripts/run_migrations.py` — there is no Alembic version table. So
"migration status" is answered the only honest way available: compare
the tables the ORM declares against the tables present, and report any
missing. That is exactly the failure worth catching — code deployed
ahead of its migration.

### No secrets, no outbound calls

No API key, SMTP password, database password or JWT secret appears in
any response. The database indicator reports the **driver family**
(`sqlite`/`postgresql`), never the DSN, which carries credentials in
production. No health check makes an outbound network request —
fanning out to every third-party provider on every dashboard load is
an outage amplifier, and a credential-verifying call is precisely the
risk section 16 warns about. Provider status comes from configuration
plus the durable delivery records the app already writes
(`EmailMessage`, `AIUsageLog`), which is better evidence than a
synthetic ping.

### Background jobs

CareerOS has **no Celery/RQ broker**, so there is no "running jobs"
count and none is invented. What exists and is reported:

- the V23.2 **email queue** — queued/sent/failed/retrying, max
  attempts, last success, last failure;
- **scheduler jobs** — last-run state from `app.scheduler.job_health`,
  with the honest caveat that this map is process-local: on a
  multi-replica deployment only one replica runs the scheduler, so
  another replica reports `unknown`, never "no jobs have run".

The **only** queue action is re-queueing specific `FAILED` email rows
by id. There is no "retry everything" switch and no way to execute an
arbitrary job. It is safe because the sender is idempotent per row
(QUEUED → SENT once) and `dedupe_key` already prevents duplicates.

### Ingestion

Per-source: registry status, schedule, last success/failure, error and
consecutive-failure counts, circuit-breaker state, availability,
latency, runs, jobs imported, records skipped, unresolved dead
letters.

**`currently_collecting` is the honest combined answer** — a source
marked "active" in the registry while `INGESTION_ENABLED=false` is
reported as *not collecting*, because it isn't. No government job data
is synthesized: `jobs_imported` sums `IngestionRun.created`, written
only by real runs. `records_skipped` keeps its real name rather than
being relabelled "duplicates", which would assert more than the data
supports.

---

## 19. Platform settings

Typed and validated, **not** an untyped JSON blob. The catalog —
keys, types, defaults, bounds, sensitivity, help text — lives in code
(`SETTING_DEFINITIONS`). The `platform_settings` table stores only
overrides.

| Key | Type | Default | Sensitive |
|---|---|---|---|
| `registration_enabled` | bool | `true` | yes |
| `recruiter_registration_enabled` | bool | `true` | yes |
| `maintenance_mode` | bool | `false` | yes |
| `maintenance_message` | str | *(default text)* | no |
| `job_moderation_required` | bool | `true` | yes |
| `announcement_email_enabled` | bool | **`false`** | yes |
| `announcement_max_recipients` | int | `5000` | no |
| `resume_max_upload_mb` | int | `0` (use env) | no |
| `ai_features_enabled` | bool | `true` | no |
| `notifications_enabled` | bool | `true` | no |

- An unknown key **cannot be written** (404) and is ignored on read.
  A stray or injected row can never introduce an unknown setting.
- Types are enforced on write **and re-validated on read**, so a
  hand-edited nonsense value degrades to the declared default rather
  than reaching a caller.
- The audit record is written in the **same transaction** as the
  change — a setting cannot be altered without a corresponding entry.
  A change also raises a `platform_setting_changed` security event so
  it appears in the security timeline alongside the authentication
  events an investigator is correlating against.
- Reads are cached in-process for 5s (`maintenance_mode` is consulted
  on nearly every request). Nothing cached here is an authorization
  decision — those are never cached.

---

## 20. Maintenance mode

When on, ordinary API traffic gets `503` with the configured message
and `Retry-After`.

**Never blocked:**

| Exempt | Why |
|---|---|
| `/health`, `/live`, `/ready`, `/metrics` | Orchestrators must distinguish a maintaining process from a dead one — blocking readiness gets the pod killed in a restart loop |
| `/auth/login`, `/auth/refresh`, `/auth/me`, `/auth/logout` | An administrator must be able to *obtain* a token to prove they are one. Blocking login makes the admin exemption unreachable — exactly the lockout section 20 names |
| `/api/v1/admin/**` | These carry their own platform-admin authorization; delegating to the gate that is actually qualified beats duplicating role logic in middleware |
| `OPTIONS` preflight | Carries no credentials; failing it surfaces as an opaque CORS error, not the maintenance message |

**Fails open.** If the setting can't be read, the request proceeds.
Maintenance mode is an operational convenience, not a security
control — no authorization decision depends on it — so the right
failure mode is "serve the request", not "take the platform down
because a flag lookup failed". Every *actual* authorization check in
CareerOS fails closed.

The middleware decides admin status from the **JWT role claim alone**,
without a DB round-trip, because it runs on every request. That is
sound here: the token is one this server signed, and the consequence
of being wrong is only that a request is allowed through during
maintenance — never that it bypasses an authorization check, since
every endpoint still performs its own full, database-backed one.

---

## 21. Platform announcements

Reuses V23.1 in-app notifications and the V23.2 email queue. **No new
notification infrastructure.**

Guards against accidental mass sending, in order:

1. **Creation delivers nothing.** An announcement is created in
   `DRAFT`; sending is a separate, separately-audited request. No
   single call can mass-mail the platform.
2. **Only a `DRAFT` can be sent** — re-POSTing an already-`SENT`
   announcement is refused (409), so a double-click or retried request
   can't send twice.
3. **Recipient cap** via `announcement_max_recipients`.
4. **Email requires an explicit opt-in** —
   `announcement_email_enabled` defaults to **off**. With it off, an
   `EMAIL`/`BOTH` announcement delivers in-app only *and says so in
   the response* rather than silently doing nothing.
5. **Sending requires a full platform-admin role.**
6. Each recipient's notification carries a per-announcement
   `dedupe_key`, so a partially-completed send that is retried won't
   double-post.

Audiences: `ALL`, `CANDIDATES`, `RECRUITERS`, `ORGANIZATION_ADMINS`,
`PLATFORM_ADMINS`.

---

## 22–23. Security events and abuse visibility

**No `security_events` table was created.** Security events reuse the
V17.2 `app/core/security_events.py` taxonomy, which writes to
`audit_logs`. A second store would be the duplicate audit system
section 28 warns against, and would leave an investigator querying two
places.

New event types this version adds:
`privilege_escalation_attempt` · `cross_tenant_access_attempt` ·
`invalid_invitation_attempt` · `suspended_account_access_attempt` ·
`platform_setting_changed`.

`GET /admin/security/events` filters `audit_logs` to
`SECURITY_INCIDENT_ACTIONS` — deliberately *not* "every audit action":
a successful login is an audit event, not an incident, and listing
millions of them would bury the handful that matter.

`GET /admin/security/abuse-signals` returns **aggregates only**:
event counts grouped by action and by source IP, plus currently-locked
account count. Not a per-user behavioural profile. Section 22 asks for
meaningful abuse visibility and rules out invasive surveillance — "which
event types spiked, from which addresses" answers the investigative
question without building a dossier.

**No password, token, OTP or session identifier is ever logged**, by
any call site.

Rate-limiter internals are **not** exposed: `app/core/rate_limit.py`
keeps counters in memory (or Redis) with no durable history, so no
rate-limit metric is invented.

---

## 24. Admin authorization

Every route in `app/api/admin_platform.py` carries an explicit
`Depends(require_platform_permission(...))`. There is no route in that
file without one.

Verified by test — each of these receives **403** on every admin
endpoint, read and write:

- candidate
- recruiter
- organization RECRUITER
- organization ADMIN
- **organization OWNER**

Unauthenticated and wrong-key requests receive **401**.

Frontend route guards are a convenience only. Nothing in
`frontend/src/app/admin` is trusted by the backend; editing the
permissions in the browser grants nothing.

---

## 25–26. Session security and sensitive actions

Reuses the existing authentication system — no second one. Short-lived
access tokens (15 min), refresh rotation, reuse detection, idle and
absolute session timeouts, account lockout, progressive login delay,
and `admin-key` rate limiting all apply unchanged.

Suspension **revokes the user's live sessions**, so a suspension takes
effect immediately rather than at the next token expiry.

Sensitive actions require a full platform-admin role (see §2) and are
confirmed in the UI. **Reversibility is preferred everywhere**: every
user, organization and job transition in this version is a state
change that can be undone. There is no destructive admin action and no
bulk deletion.

---

## 27. Bulk actions

`POST /admin/bulk/jobs/moderate` — one action across up to **50** jobs.

- **Bounded.** There is no "moderate everything matching this filter"
  form, which would make a mis-clicked filter catastrophic.
- **No bulk deletion exists** — only the four reversible transitions.
- **Per-item auditing**: every successful item gets its own audit
  record *plus* a batch summary, so an individual job's trail is
  complete whether it was moderated alone or in a batch.
- **Partial failure is reported, not hidden**: one invalid item does
  not abort the batch, and the response names which items failed and
  why (`result: partial`).
- **Transaction safety**: one commit at the end — the batch and all its
  audit records land together or not at all.

---

## 28. Database changes

### New tables

| Table | Purpose |
|---|---|
| `platform_audit_logs` | Append-only governance trail |
| `platform_settings` | Typed setting overrides |
| `platform_announcements` | Announcement intent + delivery state |

### New columns

| Table | Columns |
|---|---|
| `users` | `account_status` |
| `organizations` | `status`, `suspended_at`, `suspension_reason` |
| `jobs` | `moderation_reason`, `moderation_note`, `moderated_at`, `moderated_by_user_id`, `pre_moderation_status` |

### Deliberately not created

`security_events` (reuses `audit_logs`) · per-resource history tables
(filtered reads) · any ingestion or background-job table (existing
durable rows suffice).

### Migration

`backend/migrations/v25_2_admin_platform_governance.sql`

Additive only. Every new column is nullable or defaulted, so every
V1–V25.1 row stays valid with **no backfill**. Idempotent
(`IF NOT EXISTS` throughout) and applied via
`python -m scripts.run_migrations`. On SQLite,
`Base.metadata.create_all()` handles it at startup as usual.

New indexes: one per audit filter the investigation UI exposes, plus
`jobs (status, created_at DESC)` for the moderation queue's hot path
and `audit_logs (action, created_at)` for the security screen.

---

## 29. API endpoints

All under `/api/v1/admin`.

| Method | Path | Permission |
|---|---|---|
| GET | `/me/platform-permissions` | AUDIT_ACCESS |
| GET | `/dashboard` | PLATFORM_ANALYTICS |
| GET | `/users` | USER_MANAGEMENT |
| GET | `/users/{id}` | USER_MANAGEMENT |
| POST | `/users/{id}/suspend` | USER_MANAGEMENT |
| POST | `/users/{id}/deactivate` | USER_MANAGEMENT + sensitive |
| POST | `/users/{id}/reactivate` | USER_MANAGEMENT |
| GET | `/users/{id}/history` | AUDIT_ACCESS |
| GET | `/organizations` | ORGANIZATION_MANAGEMENT |
| GET | `/organizations/{id}` | ORGANIZATION_MANAGEMENT |
| POST | `/organizations/{id}/suspend` | ORGANIZATION_MANAGEMENT + sensitive |
| POST | `/organizations/{id}/reactivate` | ORGANIZATION_MANAGEMENT + sensitive |
| GET | `/organizations/{id}/history` | AUDIT_ACCESS |
| GET | `/jobs` | JOB_MODERATION |
| POST | `/jobs/{id}/approve` | JOB_MODERATION |
| POST | `/jobs/{id}/suspend` | JOB_MODERATION |
| POST | `/jobs/{id}/restore` | JOB_MODERATION |
| GET | `/jobs/{id}/history` | AUDIT_ACCESS |
| GET | `/moderation/reasons` | JOB_MODERATION |
| GET | `/audit` | AUDIT_ACCESS |
| GET | `/audit/actions` | AUDIT_ACCESS |
| GET | `/security/events` | AUDIT_ACCESS |
| GET | `/security/abuse-signals` | AUDIT_ACCESS |
| GET | `/search` | AUDIT_ACCESS (+ per-entity) |
| GET | `/analytics` | PLATFORM_ANALYTICS |
| GET | `/system/health` | SYSTEM_CONFIGURATION |
| GET | `/system/background-jobs` | SYSTEM_CONFIGURATION |
| POST | `/system/background-jobs/email/retry` | SYSTEM_CONFIGURATION |
| GET | `/system/ingestion` | SYSTEM_CONFIGURATION |
| GET | `/settings` | SYSTEM_CONFIGURATION |
| PUT | `/settings/{key}` | SYSTEM_CONFIGURATION (+ sensitive) |
| GET | `/announcements` | CONTENT_MODERATION |
| POST | `/announcements` | CONTENT_MODERATION |
| POST | `/announcements/{id}/send` | CONTENT_MODERATION + sensitive |
| POST | `/bulk/jobs/moderate` | JOB_MODERATION |

**Job rejection** stays on the existing `POST /admin/jobs/{id}/reject`
(V9), extended with an **optional** structured-reason body — not
duplicated on a new path.

---

## 30. Frontend

| Route | Screen |
|---|---|
| `/admin` | Dashboard |
| `/admin/users` | User management |
| `/admin/organizations` | Organization management |
| `/admin/jobs` | Job moderation + recruiter approvals |
| `/admin/analytics` | Platform analytics |
| `/admin/audit` | Audit log |
| `/admin/system` | System health |
| `/admin/settings` | Settings + announcements |

Shared shell: `frontend/src/components/admin/AdminShell.tsx` —
permission-aware navigation (filtered by the permissions the backend
reports), plus `AsyncState`, `Pager` and `ConfirmDialog`.

Every screen has distinct loading, error and empty states; server-side
search, filters and pagination; `<caption>`/`<th scope>`/`aria-label`
on tables and controls; and confirmation dialogs on every mutating
action. No screen loads an unbounded dataset — the API caps every page
at 100.

The job review queue and recruiter approvals moved from `/admin` to
`/admin/jobs`, so all moderation lives together.

---

## 31. Security review

Tested explicitly:

| Test | Result |
|---|---|
| Candidate → `/admin/*` | 403 |
| Recruiter → `/admin/*` | 403 |
| Organization OWNER → `/admin/*` | 403 |
| Unauthenticated / bad key | 401 |
| Org owner suspending a user / org / changing settings | 403 |
| Privilege-escalation attempt logged, no credential in the event | ✔ |
| IDOR on user/org/job ids | 404, no existence leak |
| Cross-tenant access → 404 + security event | ✔ |
| SQL-injection-shaped search input | Parameterized; harmless |
| Sensitive fields in user list/detail | Absent |
| Internal moderation note on public job endpoint | Absent |
| Secrets in health response | Absent |
| Audit row edit/delete via API | 404/405; row intact |
| Bulk size cap / bulk delete route | 422 / does not exist |
| Mass-assignment | Pydantic models are explicit allow-lists |

---

## Backward compatibility

Three deliberate changes, all documented:

1. **`GET /admin/users`** moved from `app/api/admin.py` to the
   governance router. Same path — **not** duplicated (§29 forbids a
   second route). It gained search, filters, pagination and explicit
   platform-admin authorization. Every field the V9 version returned
   (`id`, `email`, `full_name`, `role`, `active`) is still present on
   each result, now inside the standard
   `{total, limit, offset, results}` envelope. No test or frontend
   code consumed the old shape.

2. **`POST /admin/jobs/{id}/reject`** gained an **optional** body. A
   caller sending no body at all works exactly as before and gets
   `reason: "other"` recorded.

3. **`POST /admin/jobs/{id}/publish`** delegates to
   `job_moderation.approve_job`. Identical path, identical response
   body, identical `published_at` semantics.

---

## Deployment

1. Apply the migration: `python -m scripts.run_migrations` (Postgres).
   SQLite needs nothing.
2. No new environment variables. Everything configurable in this
   version is a platform setting, changed through the audited API.
3. Create at least one platform administrator via
   `POST /admin/create-admin-user` before relying on JWT auth; keep
   `ADMIN_API_KEY` as the break-glass credential.
4. Consider restricting the application's DB role to `INSERT, SELECT`
   on `platform_audit_logs` (see §10).
5. Keep `announcement_email_enabled` off until outbound email is
   verified in the target environment.
6. Multi-replica: scheduler health is process-local — expect
   `unknown` from replicas with `SCHEDULER_ENABLED=false`.

---

## Verification status

See `V25_2_TEST_REPORT.md` for what was and was not executed. In
short: the implementation is complete and a full test suite is
included, but **the build environment had no network access**, so
backend dependencies could not be installed and `node_modules` could
not be fetched. Backend tests, frontend build, lint and type-check are
therefore reported as **NOT VERIFIED** — not as passing.
