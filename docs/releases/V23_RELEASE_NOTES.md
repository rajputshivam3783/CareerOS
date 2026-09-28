# V23.5 — Notification & Communication Production Stabilization

**This is the final V23 release.** V23.5 adds no new features — it is
a full audit, bug-fix, and hardening pass across V23.1 (Notification
Infrastructure), V23.2 (Email), V23.3 (Smart Job Alerts), and V23.4
(Communication Center), performed as one architecture.

## What changed

### Fixed — Critical

- **App failed to start on any fresh database.** A duplicate index
  declaration on `NotificationReminder.scheduled_for` (V23.4) crashed
  `Base.metadata.create_all()`. See `docs/V23_BUG_REPORT.md` BUG-1.

### Fixed — Severe (production-impacting)

- **Four core notification endpoints were silently serving the wrong
  response shape** since V23.1 shipped: an old V7 router
  (`app/api/platform.py`) was registered ahead of, and shadowed,
  `GET /notifications`, `GET /notifications/unread-count`, and
  `POST /notifications/{id}/read` — endpoints the frontend was always
  built against the *correct* (newer) shape of. Removed the duplicate
  routes. See BUG-2.

### Fixed — Real reliability/security gaps

- Recruiter-facing candidate emails (status change, interview
  scheduling, offer letters) had no failure isolation — a transient
  SMTP failure turned an already-successful recruiter action into a
  500 response. Added isolation. See BUG-3.
- The AI insight cache crashed on a same-key race (e.g. a double-
  click or rapid retry) instead of returning the existing cached
  result. Fixed. See BUG-4.
- Three job-alert endpoints (`run-now`, both `preview` variants) had
  no rate limiting despite triggering real matching/recommendation
  work. Added rate limiting, consistent with the rest of the
  codebase's existing convention. See BUG-5.
- Widened the notification `action_url` allowlist to include
  `/job-alerts` and `/communication` — both real, current routes with
  no prior entry (a forward-completeness fix, not a live
  vulnerability — no current code path was blocked by the gap).
- Documented (previously undocumented) V23.3/V23.4 scheduler interval
  settings in `.env.example`.

### Fixed — test suite

- Root-caused and documented a test-harness limitation (not a
  production bug): the SQLAlchemy engine in `app/db/session.py` is a
  module-level singleton, so running the full test suite as one
  `pytest tests/` process only honors the first test file's
  `DATABASE_URL`. Established running each test file in its own
  process as the correct, reliable methodology, and validated the
  entire suite (49 files, 711 tests) that way.
- Fixed 6 tests that were either asserting against the now-corrected
  (previously buggy) route shapes, sensitive to UTC-day-boundary wall-
  clock timing, missing a required fixture dependency, or sensitive to
  other tests' data in a shared test database. None were production
  bugs — each is explained in `docs/V23_BUG_REPORT.md`.

### Confirmed safe (audited, no defect found)

Email header injection, email recipient sourcing, action-URL open-
redirect/SSRF protection, template/HTML injection, and IDOR across the
entire Communication Center and Job Alerts APIs were all directly,
empirically tested and confirmed already correct. See
`docs/V23_BUG_REPORT.md`'s "Confirmed-safe findings."

## Known limitations (see `docs/V23_BUG_REPORT.md` for full detail)

1. Two email-sending code paths coexist (V16 direct-SMTP, still used
   by the recruiter ATS and the older government-job automation
   engine; V23.2's queued/templated system, used by everything else).
   Not consolidated in this release.
2. Two non-overlapping reminder subsystems coexist (V19.4 government-
   job dates; V23.4 application/interview/task dates). Confirmed no
   double-notification for the same event; a user who both saves and
   applies to the same government job could receive one reminder from
   each system.
3. `UserNotificationPreference.digest_mode` (V19.4) is stored but
   never read; V23.4 added its own `digest_enabled` boolean instead.
4. The backend test suite requires per-file process isolation to run
   reliably (see above) — this is a test-harness characteristic, not
   a production issue.

None of these block release; each is a documented architectural
observation, not a correctness defect.

## Not verified (no fabricated validation)

- Migration execution against a live Postgres instance
- Docker image build/run
- Real multi-process/multi-machine worker concurrency
- Frontend linting (no lint config exists in this project)
- Frontend automated/unit tests (no test framework exists in this
  project)
- Browser console errors, accessibility, keyboard navigation,
  responsive/mobile behavior (no browser available in this
  environment)

See `docs/V23_RELEASE_CHECKLIST.md` for the complete, itemized
PASS/FAIL/NOT VERIFIED status of every audited area.

## Release status

**READY WITH LIMITATIONS.** All backend and frontend validation that
could be performed in this environment passed, including 711/711
backend tests and a clean production frontend build, after fixing 5
confirmed defects (1 critical, 1 severe, 3 real) found during this
audit. The remaining NOT VERIFIED items above are all external-
environment dependencies (a real Postgres server, a Docker daemon, a
real browser, multi-machine workers) that this environment cannot
provide — none represent a known or suspected defect, and the
architecture underneath each (unique-constraint-based idempotency,
migration-file correctness, documented worker/scheduler constraints)
was verified as thoroughly as static/single-process testing allows.
A team with access to a staging environment matching production
(real Postgres, real SMTP or a sandboxed provider, multiple worker
processes, a browser) should run through the NOT VERIFIED list once
before a production cutover; nothing found during this audit suggests
that pass would surface a new defect, but it has not been performed.
