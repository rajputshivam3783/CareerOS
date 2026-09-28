# SCHEDULER â€” V19.2

## Scope: framework, not a running service

`app/ingestion/scheduler.py` is a pure, testable *decision function* â€”
it does not start a background process, register a cron job, or spawn
any threads. This mirrors V19.1's own stated scope boundary
(`SOURCE_REGISTRY.md`: "V19.1 only builds the registry, not a
scheduler for it") â€” V19.2 builds the scheduler's *logic*, and leaves
wiring it to an actual clock as a deployment choice, documented below.

## Cadence model

`SourceRegistry.schedule` is a free-text string, interpreted by
`is_due()`:

| `schedule` value | Behavior |
|---|---|
| `"hourly"` | Due once `last_run_at` is more than 1 hour old (or never run) |
| `"daily"` | Due once `last_run_at` is more than 24 hours old (or never run) |
| `"manual"` / blank / anything else | Never auto-selected â€” only runs via an explicit `POST /government/sources/{id}/run` |

A source is only ever considered due if its `status` is `"active"`
*and* its circuit breaker isn't currently open (see below) â€” a
`"paused"`/`"disabled"` source, or one that just failed repeatedly,
is skipped by the scheduler even if its cadence says it's due.

## Priority queue

`due_sources(db)` returns every currently-due source sorted by
`SourceRegistry.priority` (lower value = higher priority, default
`100`), then by how long it's been since its last run. This is the
"Priority Queue" requirement â€” an operator can, for example, set
`priority=10` on a small number of high-value sources (say, UPSC/SSC)
so they're always run before the long tail of PSU sources when a
scheduler pass has limited time/capacity (`run_due_sources(db, limit=N)`).

## Error handling

Retry, backoff, and the circuit breaker itself live in
`app/ingestion/services/errors.py`, used by the orchestrator
(`SOURCE_ADAPTER_ARCHITECTURE.md`), not the scheduler â€” the scheduler
only needs to know whether a circuit is currently open
(`circuit_is_open()`) to decide whether to include a source in this
pass. A source's circuit opens after 3 consecutive failed runs and
stays open for a 30-minute cooldown before the next scheduled attempt
is allowed through as a trial run.

## Running it for real

Nothing in this version starts a clock. The framework supports either
of these, unchanged:

- **Simplest â€” external cron**: point any scheduler (a system cron
  entry, a platform's scheduled-job feature) at
  `POST /government/scheduler/run-due` on whatever cadence you want
  the *scheduler pass itself* to run (e.g. every 15 minutes is plenty
  â€” individual sources still only actually run when their own
  `hourly`/`daily` cadence says they're due).
- **Future â€” distributed workers**: the unit of work is exactly
  `app.ingestion.orchestrator.run_source_by_id(db, source_id)` â€” a
  single source id, safe to hand to any task queue (Celery, RQ, etc.)
  as a job payload. `run_due_sources()` is presently just a sequential,
  in-process caller of that same function; swapping it for "enqueue
  one job per due source id" changes nothing about the due-selection
  logic in `due_sources()`/`is_due()`.

## Manual override

Regardless of cadence or due-status, `POST /government/sources/{id}/run`
always runs a source immediately (subject to the same circuit-breaker
check) â€” this is the "Manual" scheduling mode and also what the admin
Source dashboard's "Run now" button calls.

