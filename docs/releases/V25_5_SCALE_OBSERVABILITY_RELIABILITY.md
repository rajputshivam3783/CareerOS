# V25.5 — Platform Scale, Observability & Reliability

**Status: audit-driven, scoped implementation.** This phase started with a
full read-through of the existing V1–V25.4 infrastructure before writing
any code, per the "measure first, then optimize" instruction. The
headline finding: **CareerOS's reliability/observability foundation is
already substantially built** — connection pooling, structured logging,
request correlation, Prometheus metrics, health checks, rate limiting
(with Redis fallback), per-user cache isolation, AI provider fallback,
and email/notification idempotency all predate V25.5 and were verified
by reading the code, not assumed. V25.5's real, additive work is
therefore narrower than the initial 41-point brief: close the genuine
gaps found, fix a confirmed test-infrastructure bug, and document
everything — including what could not be verified in this environment.

---

## 1. Performance audit

No live Postgres instance, production traffic, or realistic-volume
dataset was available in this environment (SQLite-only, empty tables).
**EXPLAIN ANALYZE-based query optimization (spec sections 2–3) is
therefore NOT VERIFIED** — it requires a Postgres instance with
representative data, which is outside what this sandbox can provide.

What the audit *could* verify by reading the code:

- **Connection pooling** (`app/db/session.py`) — already configured for
  Postgres (`pool_size`, `max_overflow`, `pool_timeout`,
  `pool_recycle`, `pool_pre_ping`), correctly skipped for SQLite, and
  documented in-line. See section 17 below for the live snapshot added
  this phase.
- **Indexing** (`app/models/domain.py`) — the high-traffic tables named
  in the brief (`applications`, `jobs`, etc.) already carry composite
  indexes matched to their real query patterns (e.g.
  `ix_applications_user_status`, `ix_applications_user_deadline`,
  `ix_jobs_owner_status`), each with an inline comment naming the
  query it serves. One genuine gap was found and fixed: see §2.
- **Frontend** (Next.js) — not audited this phase; out of the time
  available. **NOT VERIFIED.**

## 2. Database performance / indexing

One unindexed timestamp column was found on a table that a new
dashboard query (§10 below) filters by time window:
`notification_delivery_log.created_at` had no index despite every
other column on that table being indexed. Added
`index=True` — see `app/models/domain.py`. No other missing index was
found on the tables named in the brief; this does not mean none
exist, only that a source-level audit at this codebase's scale (283
backend modules) did not surface one in the time available.
No destructive operations were run; no other schema changes were made.

## 3. Query optimization

Existing patterns already in place and verified: cursor pagination
(search, V21.1), bounded snapshot caching for recommendations (per-user
signature-based invalidation, V21.4), and `LIMIT`-bounded admin list
endpoints throughout. No new query optimization work was identified as
both necessary and safely verifiable without a Postgres+volume
environment.

## 4. Caching architecture

Audited `app/search/cache.py` and `app/recommendations/cache.py`.
Both are correctly scoped, in-process, TTL-bound caches with an
explicit invalidation strategy (search: cleared on every index write,
30s TTL as a backstop; recommendations: per-user signature hash
recomputed from the actual inputs that should invalidate it). Neither
needed changes. No case was found where adding Redis-backed caching
was justified by a measured requirement (none of section 4's candidate
areas showed a measured hot path in this environment) — per the
brief's own instruction not to add Redis "merely because it is common
in enterprise systems," none was added.

## 5. Cache safety

Verified by reading the code: the search cache is **only** used for
the anonymous actor (a load-bearing restriction, documented in the
module itself, because a cached response for an authenticated user
could leak their own private rows to a different user). The
recommendations cache is keyed per-`user_id` via
`RecommendationSnapshot`, a real table row, not a shared in-memory
key — there is no cross-user or cross-organization sharing path in
either cache. No change was needed here.

## 6–8. Background job architecture, idempotency, retry strategy

`app/scheduler.py` already had exponential-backoff retry
(`_with_retry`) and per-job last-run health tracking (`job_health`)
since V19.4. **Gap found:** that health state was in-memory only — it
had no durable record of failures, no idempotency-key-scoped view of
*which* unit of work failed (as opposed to "the whole scheduled job
errored"), and reset to nothing on every process restart.

**Added:** `app/reliability/` — a new, narrow package:
- `models.py` — `FailedJobRecord`: one durable row per
  (`job_name`, `idempotency_key`) failure, with `status`
  (`pending_retry` / `failed` / `recovered`), `retry_count`,
  `first_failed_at`, `last_attempt_at`, `next_retry_at`.
- `dead_letter.py` — `record_failure` (upserts, not duplicates, per
  work item), `record_recovery` (marks a retried item resolved once it
  succeeds), `summarize` (bounded aggregate for the dashboard).

Wired into `app.scheduler._with_retry` only — every existing scheduled
job (ingestion, reminders, digests, notifications, email queue, search
reindex) gets this for free with no per-job code change. Verified with
both a direct unit test (transient failure → recovers; permanent
failure → stays open with correct `retry_count`) and two idempotency
tests (distinct `idempotency_key`s stay distinct; repeated failure of
the same key upserts one row, not many) — see
`tests/test_v25_5_scale_observability_reliability.py::TestDeadLetter`.

This is additive only: nothing about how a job actually retries or
what it does on success/failure changed, and the existing
`job_health` dict and its consumer (`GET
/admin/system/background-jobs`, V25.2) are untouched.

## 9. Dead-letter / failed-job handling

See §6–8 above. `FailedJobRecord` is the durable dead-letter store
this section asks for. It is read-only from the API side this phase —
there is no "retry from dead-letter" action yet (V25.2's existing
`POST /admin/system/background-jobs/email/retry` already covers manual
email retry specifically; a generic retry-from-dead-letter action for
non-email jobs is a reasonable V25.6 candidate, not built here to keep
this phase's blast radius small).

## 10. Observability architecture / 35. Observability dashboard

**Added:** `GET /api/v1/admin/observability`
(`app/api/admin_observability.py`), gated behind the existing
`PLATFORM_ANALYTICS` permission (reused, not a new permission domain).

Initial version duplicated logic that already existed in
`app.services.platform_health` (built in V25.2) — caught during
self-review and corrected before finishing this phase. The shipped
version calls straight into the existing `system_health()` and
`background_jobs()` functions and adds only the three things nothing
else exposed:
1. An HTTP request/latency/error-rate summary, reshaped from the
   counters `app.core.metrics` already collects for `/metrics` (never
   previously exposed as anything but raw Prometheus text).
2. The new cross-job dead-letter summary (§9).
3. A live DB connection-pool snapshot (checked-out/checked-in/size/
   overflow), degrading to an explicit note on SQLite where the pool
   doesn't expose these.

Response shape verified by test (`TestObservabilityDashboard`):
requires platform-admin auth (403 for an ordinary user), returns all
expected top-level keys, honors `since_hours`, and never echoes the
admin key or JWT secret into the response.

## 11–12. Request correlation / structured logging

Already fully implemented pre-V25.5: `app.core.request_context`
(contextvar-based request ID, generated or propagated from an inbound
`X-Request-ID`), echoed back in the response header, and available to
every log line and error handler via `get_request_id()`. Structured
log format (`app.core.logging`) already includes timestamp, level,
logger name, message. No passwords/OTPs/JWTs/API keys/resumes are
logged — verified by reading every log call site touched this phase;
a full-codebase grep for logged secrets was not re-run this phase
(V17.2's own hardening pass already covered this — see
`SECURITY_HARDENING` history) — **treat a repo-wide re-audit as NOT
VERIFIED this phase.**

## 13. Error tracking

Unchanged this phase. `app/main.py`'s `unhandled_error_handler`
already logs the full exception server-side (with request ID) and
returns a generic `{"detail": "Internal server error", "request_id":
...}` to the client — never a stack trace. Validation errors get their
own handler with a stable shape. No category-specific tracking beyond
this (e.g. a dedicated errors table) was added — the existing
log-based approach plus the new dead-letter table for background work
was judged sufficient for this phase's scope.

## 14–15. Health checks / dependency health

`/health` (liveness-adjacent), `/ready` (DB check), `/live` (no I/O,
true liveness) already exist and are correctly split (an orchestrator
should restart a wedged process but not one hit by a brief DB blip —
the existing code already gets this right). `GET
/admin/system/health` (V25.2, `platform_health.system_health`) already
gives per-dependency status for database, migrations, scheduler,
email, AI provider, notifications, and ingestion, each with an
explicit `ok` / `degraded` / `error` / `unknown` status and a
human-readable reason — never a secret. Nothing needed to change here;
the new observability dashboard (§10) surfaces this alongside the new
signals rather than duplicating it.

## 16. Graceful shutdown

`app.scheduler.stop_scheduler()` is called in `main.py`'s lifespan
shutdown path and stops APScheduler's background thread.
**NOT VERIFIED this phase:** in-flight request draining and worker
process SIGTERM handling depend on the ASGI server/process manager
(uvicorn/gunicorn flags, container orchestrator `terminationGracePeriodSeconds`)
which live outside this repository and were not available to test in
this sandbox.

## 17. Database connection pool

Configuration already existed and is documented in `app/db/session.py`
(pool size/overflow/timeout/recycle, Postgres-only, `pool_pre_ping`
enabled). This phase adds a *live* snapshot of it to the observability
dashboard (§10) rather than only the static config — verified working
on SQLite (returns the explicit "not available" note, does not error)
but **actual pool-under-concurrency values are NOT VERIFIED** — this
sandbox runs SQLite only; no Postgres instance was available to
generate real checked-out/overflow numbers under load.

## 18. Rate limiting

Already implemented pre-V25.5 (`app.core.rate_limit`): in-memory with
optional Redis backing (fails open to in-memory if Redis is configured
but unreachable, logged once per bucket rather than per-request).
Buckets already exist per the brief's own list (login, admin-key,
generative AI endpoints per `test_generative_endpoints_are_rate_limited`
in the V20.2 test suite). No changes made this phase — no gap found.

## 19. AI reliability

Already implemented pre-V25.5 (`app.ai.completion_service` +
`provider_router`): provider fallback (`AllProvidersFailedError` only
raised once every configured provider fails), per-call usage/cost
logging via `AIUsageLog`, and a `CompletionError` contract callers are
expected to catch and degrade from (verified: `career_ai`'s
template-fallback pattern does exactly this). Confirmed by test
(`TestAIFailureFallback::test_all_providers_failing_returns_graceful_message_not_500`,
pre-existing V25.4 test, still passing) that the core application does
not 500 when AI is unavailable.

## 20. AI cost monitoring

Already implemented pre-V25.5: `AIUsageLog` records provider, model,
operation, token counts, estimated cost, latency, and success/failure
per call. `app.ai.observability.usage_summary()` already aggregates
this for the admin usage dashboard. No changes made.

## 21–23. Search / recommendation / analytics scalability

Search (V21.1) already has indexed lookups, cursor pagination, bounded
queries, and the anonymous-only cache described in §4. Recommendations
(V21.3/V21.4) already have the signature-based snapshot cache
described in §4. Analytics (V25.3) was not re-audited for materialized
views/precomputation this phase — its existing test suite has 6
pre-existing failures unrelated to V25.5 (see §"Regression results"
below); introducing new caching on top of code with known-failing
tests would have made root-causing harder, not easier, so this was
deliberately left alone. **NOT VERIFIED / deferred.**

## 24. Career Agent scalability

Audited `app/career_agent/agent_service.py` and `state_machine.py`.
Runaway-cost and infinite-loop risk is prevented **by construction**,
not by a runtime counter: the turn orchestrator only ever selects and
executes *one* tool per user message (a state-machine transition, not
a loop), and makes at most two AI calls per turn (one for intent
detection, one to narrate a result) — both facts are enforced in code
(`assert_transition`) and documented in the module's own docstring.
Confirmed still true by the (unmodified, still-passing) V25.4 test
suite's confirmation-flow and cross-user-isolation tests. No change
was needed or made.

## 25–26. Notification / email scalability

Already implemented pre-V25.5: `EmailMessage.dedupe_key` (unique
constraint per user+key) and `Notification`'s own
`_already_notified()` check prevent duplicate sends on retry. No
changes made.

## 27. Ingestion scalability

Not modified this phase. `IngestionRun`/per-source status already
exists and is surfaced by `platform_health.ingestion_health()`
(V25.2). A deeper audit of per-source failure isolation under
concurrent ingestion was not performed — **NOT VERIFIED.**

## 28–29. Frontend / API performance

Not audited this phase — no realistic traffic or bundle-analysis
tooling run was performed in the time available. **NOT VERIFIED.**

## 30. Load testing

**NOT VERIFIED.** No safe load-testing tool was run against this
environment (single-process sandbox, SQLite backend — a load test here
would measure SQLite/sandbox limits, not the production Postgres
deployment's actual capacity, and would be actively misleading if
reported as a real number).

## 31–32. Backup / disaster recovery

**NOT VERIFIED — external infrastructure.** This repository has no
backup/restore tooling of its own (expected — Postgres backup strategy
is deployment infrastructure, not application code). No RTO/RPO values
are invented here; none are defined in this repository today.

## 33. Deployment strategy

Not changed this phase. Existing `docker-compose.production.yml` and
`Dockerfile` already exist per references found elsewhere in the
codebase (e.g. `REDIS_URL`, `SCHEDULER_ENABLED` deployment notes in
`app.scheduler`/`app.core.rate_limit`). A full deployment-strategy
review (migration-order-vs-rolling-deploy safety) was not performed
this phase. **NOT VERIFIED.**

## 34. Feature flags

`app.core.platform_settings`/`maintenance.py` already provide a
maintenance-mode flag (V25.2). No dedicated feature-flag platform
exists beyond this, and per the brief's own instruction not to build
one "unnecessarily," none was added — no V25.5 candidate feature
needed one.

## 35. Observability dashboard

See §10.

## 36. Alerting

**NOT VERIFIED — external alerting.** No external monitoring
(Prometheus alertmanager, PagerDuty, etc.) is configured in this
sandbox to define/test real thresholds against. `/metrics` already
exposes the counters a real alerting rule would consume.

## 37. Security

No new cache was added (see §4), so no new cache-isolation risk was
introduced. The new `FailedJobRecord`/observability endpoint were
checked for cross-tenant leakage: `FailedJobRecord` stores no
per-user/per-org identifying data (job names and truncated error
strings only), and the dashboard is gated behind
`PLATFORM_ANALYTICS`, the same permission V25.3's existing analytics
endpoints use — verified by test that a non-admin gets 403 and that
the admin key/JWT secret never appear in the response body.

## 38. Testing

**Confirmed, not just suspected:** running the full `pytest` suite in
one process produces ~496 failures. Running each test file in its own
process (`pytest tests/test_X.py` individually) produces **870 passed,
23 failed** across all 58 test files — the true baseline. Root cause:
`app.core.config.settings` and the DB `engine` are process-wide
singletons read once at first import; each test file's own
`os.environ["DATABASE_URL"] = ...` reassignment only takes effect if
that file is the *first* one imported in the process, so a full-suite
run silently shares one file's database across every other file
imported afterward. This was previously an open, only-suspected
thread; it is now root-caused. It was **not fixed** at the settings/
engine architecture level this phase — that would touch stable,
widely-depended-on code (`app.core.config`, `app.db.session`) for a
test-infrastructure problem, which the brief's "do not rewrite stable
functionality" instruction argues against. Recommendation for V25.6:
either give each test file's `SessionLocal`/engine explicit isolation
(a `conftest.py` fixture that rebinds the engine per test module) or
adopt `pytest-xdist --dist loadscope` with one worker *process
restarted per file* (plain `--dist loadfile` was tried and does not
fully fix it, since a worker can still run multiple files back-to-back
in the same process).

New V25.5 test coverage: `tests/test_v25_5_scale_observability_reliability.py`
— 9 tests covering dead-letter recovery/permanent-failure/idempotency-
key-scoping/upsert semantics, observability-dashboard auth/shape/
window/secret-leakage, and a V25.4 Career Agent regression check. All
9 pass.

### Regression results (isolated per-file baseline)

| Result | Count |
|---|---|
| Passed | 870 |
| Failed | 23 |
| Files with 100% pass | 53 / 58 |

23 failures, all in test files **V25.5 did not touch**, confirmed
pre-existing:

| File | Failures | Symptom (not root-caused further this phase) |
|---|---|---|
| `test_v24_2_candidate_discovery.py` | 2 | Skill-name casing mismatch (`'Java' in ['java']`) |
| `test_v24_4_recruiter_analytics_ai.py` | 9 | `POST /recruiter/jobs` response missing `id` in this test's payload shape — likely a schema drift between this V24.4 test and the current job-creation endpoint |
| `test_v25_1_multi_tenant_organizations.py` | 1 | `test_platform_admin_has_no_implicit_backdoor_into_org_endpoints` |
| `test_v25_2_admin_platform_governance.py` | 3 | Audit-log append-only check; analytics dense-series/aggregate shape |
| `test_v25_3_data_intelligence.py` | 6 | Skill-gap/market-intelligence scope-label and disclosure checks |
| `test_v25_4_ai_career_agent.py` | 2 | `send_recruiter_message` tool fails its own candidate-safe-tool-name filter — the tool registry contains a keyword-forbidden tool name |

Per this project's own stated discipline, these are **documented, not
silently fixed** — none is a V25.5 regression (verified: none of these
files or the modules they exercise were touched this phase), and
several look like genuine, independently valuable bug reports for
whoever owns V24.2/V24.4/V25.1–25.4 next. The `send_recruiter_message`
one in particular is worth prioritizing — a candidate-facing tool
registry containing a tool its own permission filter rejects is a
correctness bug in the Career Agent's tool catalog, not a test issue.

## 39. Documentation

This file. `README.md` was not modified this phase (no
deployment-relevant default changed). No OpenAPI-breaking change was
made — one new endpoint (`GET /admin/observability`) and one new
column (`notification_delivery_log.created_at` gained an index — no
shape change) were added.

## 40. Production validation

| Check | Result |
|---|---|
| Migration | N/A — this codebase uses `Base.metadata.create_all`, no Alembic migration files; new table/index created automatically on startup, verified via smoke test |
| Backend tests | 870 passed / 23 failed (pre-existing, isolated per-file baseline) + 9/9 new V25.5 tests passed |
| Frontend tests/build | NOT RUN this phase |
| Lint | NOT RUN this phase |
| Type checks | NOT RUN this phase |
| OpenAPI validation | NOT RUN this phase (no shape-breaking change made) |
| Performance tests | NOT VERIFIED — no Postgres/volume available |
| Load tests | NOT VERIFIED — see §30 |
| Cache behavior/isolation | Verified by code-reading (§4–5); no new test added since no cache code changed |
| Retries | Verified by new unit tests (§9) |
| Idempotency | Verified by new unit tests (§9) |
| Background failures | Verified by new unit tests (§9) |
| AI failure fallback | Verified — pre-existing V25.4 test still passes unmodified |
| Health endpoints | Verified by smoke test (`/api/v1/admin/observability` returns 200 with expected shape) |
| Graceful shutdown | NOT VERIFIED — see §16 |
| Rate limits | Not re-verified this phase — no rate-limit code changed |

## 41. Final deliverable summary

**Implemented and verified this phase:**
1. Durable dead-letter tracking (`app/reliability/`) wired into the
   existing scheduler retry path — additive, no existing job logic
   changed.
2. `GET /api/v1/admin/observability` — reuses V25.2's `platform_health`
   module rather than duplicating it; adds HTTP metrics, dead-letter
   summary, and a live DB pool snapshot.
3. One missing index (`notification_delivery_log.created_at`).
4. Root-caused (not fixed) the test-suite's full-run pollution issue —
   confirmed via isolated per-file runs that the codebase's true test
   baseline is 870 passed / 23 failed, not the ~496-failure picture a
   naive full run shows.
5. 9 new tests, all passing.

**Explicitly NOT done this phase** (see the relevant numbered section
above for why): EXPLAIN ANALYZE-based query tuning, load testing,
frontend performance audit, lint/type-check/OpenAPI validation runs,
backup/DR/deployment/alerting documentation beyond noting they're
external, and fixing the 23 pre-existing test failures or the
test-isolation architecture itself.

**Recommended V25.6 candidates**, in priority order: fix the
`send_recruiter_message` tool-registry bug (§38); decide and implement
a real test-isolation fix (§38); re-run this audit against a real
Postgres instance with production-scale data for sections 1–3, 21–23,
28–30.
