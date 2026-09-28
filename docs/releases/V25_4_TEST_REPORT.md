# V25.4 Test Report — Advanced AI Career Agent & Automation

## Status: NOT VERIFIED (no network access in the authoring sandbox)

This sandbox has no outbound network access, so `pip install -r
requirements.txt` could not run and none of FastAPI, SQLAlchemy,
Pydantic, pytest, etc. could be installed. **No test in this release
was actually executed**, and no claim below should be read as "passed"
— only as "written, and checked by hand against the real source."

This matches the precedent already set by V25.2 and V25.3 in this same
codebase (see their respective `V25_2_TEST_REPORT.md` /
`V25_3_TEST_REPORT.md`), which hit the same environment limitation.

## What was done instead

Every new function call this release makes into existing V20–V25.3
code was checked directly against that code's actual source before
being written — not assumed from the spec or from a plausible-looking
name. Concretely, before writing `app/career_agent/tools.py`, the
following were read in full and their exact signatures matched:

- `app.search.service.run_search`, `app.search.provider.SearchFilters`,
  `app.search.permissions.SearchActor`, `app.search.document.EntityType`
- `app.recommendations.service.get_recommendations` /
  `RankedRecommendation`
- `app.applications.service.get_application` / `list_applications` /
  `ApplicationFilters` / `get_dashboard` / `get_upcoming_deadlines` /
  `ApplicationNotFoundError`
- `app.applications.tasks.create_task` / `InvalidTaskError`
- `app.applications.timeline.get_timeline`
- `app.applications.ai.signals.compute_signals`,
  `app.applications.ai.context.build`,
  `app.applications.ai.interview_prep.generate`,
  `app.applications.ai.followup.generate`
- `app.resume_ai.pipeline.run_and_persist` / `build_profile`,
  `app.resume_ai.recommendations.generate`
- `app.skill_intelligence.gap.compute` / `UnifiedSkillGapResult` /
  `SkillGapItem`, `app.skill_intelligence.readiness.compute` /
  `ReadinessResult`, `app.skill_intelligence.learning_path.build` /
  `PathStep` / `LearningPathDraft`
- `app.intelligence.candidate.overview`
- `app.notifications.service.create_notification` / `list_notifications`
  / `CATEGORIES` / `PRIORITIES`
- `app.career_copilot.context_engine.build` / `to_prompt_text` /
  `CareerContext`, `app.career_copilot.system_prompt.wrap_untrusted`
- `app.ai.completion_service.generate` / `CompletionError`,
  `app.ai.provider_router.route_complete` / `RoutedResult`,
  `app.ai.providers.base.CompletionResult`
- `app.core.rate_limit.enforce_rate_limit`, `app.core.security.current_user`
- The `Job`, `Application`, `ApplicationInterview`, `Skill`,
  `LearningResource`, `Resume`, `ResumeAnalysis` model column names

One real fix this caught before it could become a bug: `Job.deadline`
and several dataclass fields (`RankedRecommendation.deadline`, the
V22.1 `get_upcoming_deadlines` dict) are plain strings/None in some
places and `date` objects in others — `app.career_agent.actions`'
`json.dumps(result, default=str)` (rather than a plain `json.dumps`)
was added specifically so a tool result containing a raw `datetime`
(e.g. `candidate_intel.overview`'s `generated_at`) never raises inside
the action-persistence path.

## Written test coverage

`backend/tests/test_v25_4_ai_career_agent.py`, ~30 tests, organized to
match the spec's own testing categories (section 36):

**Agent (no AI mocking — pure logic)**
- State machine: legal READ path, legal WRITE/confirm path, illegal
  transitions rejected (skip-confirmation, skip-planning, terminal
  states have no outgoing edge), risk-to-next-state mapping.
- Tool registry: unknown tool rejected, unexpected parameter rejected,
  missing required parameter rejected, valid call is type-coerced,
  a single value is accepted for a list parameter, every registered
  tool has a callable handler and a valid risk level.

**Security**
- No recruiter/admin tool name is present in the registry (iterates
  every registered tool through the denylist).
- The denylist itself actually rejects a forbidden name (a
  meta-test — catches a denylist that silently stopped matching).
- `require_candidate(None)` is rejected.
- Cross-user: user B gets 404 reading user A's conversation, 404
  confirming user A's action, and an empty list (never user A's
  conversations) from their own conversations list.
- The `/career-agent/tools` endpoint never lists a recruiter/admin
  tool.

**AI**
- Intent JSON parsing: valid JSON with a known tool validates
  correctly; malformed JSON degrades to a clarifying question rather
  than crashing; a tool name the model invents that isn't in the
  registry is never passed through (degrades to clarify); a tool
  call missing a required parameter degrades to clarify rather than
  guessing; the deterministic fast-path matches common phrasings with
  zero AI calls; unrecognized free text correctly falls through to
  the AI path (returns `None` from `fast_path`).
- All-providers-failing (`AllProvidersFailedError`) returns a plain
  "temporarily unavailable" message with HTTP 200, never a raw 500.

**Tools / confirmation flow (end-to-end via the API, `route_complete`
mocked per the `test_v20_3`/`test_v22_4` precedent)**
- A READ tool (`get_saved_jobs`, matched via the fast path) executes
  immediately, is logged COMPLETED, and makes exactly one AI call
  (narration only — confirms the fast path really skips the intent AI
  call).
- A general question with no matching tool makes exactly two AI calls
  (intent detection, then grounded narration) and returns COMPLETED
  with no action.
- A WRITE tool (`schedule_follow_up`) stops at
  WAITING_FOR_CONFIRMATION, does not execute anything before confirm,
  is listed under `/pending-actions`, executes exactly once on
  confirm (task title verified), and returns 409 on a second confirm
  of the same action (idempotency).
- Reject prevents execution; confirming a rejected action returns 409.
- A HIGH_RISK tool (`submit_application`) against a job id that
  doesn't exist fails cleanly (`FAILED`, not a fabricated success) —
  the never-claim-success behavior for an unsupported external action.
- Conversation history: rename, archive (drops out of the active
  list), delete, and a 404 after delete.
- Preferences: defaults, a valid update, an invalid `frequency` value
  rejected.
- Regression: the untouched V22.1 `/applications/{id}` endpoint still
  works after this release's changes.

Note on isolating NLU from the confirmation pipeline: the
WRITE/HIGH_RISK/cross-user tests monkeypatch
`app.career_agent.intent.detect` directly to a fixed tool/params
rather than relying on the AI (or even the deterministic fast-path) to
land on the exact tool under test — intent selection itself is
covered separately and exhaustively by the `TestIntentParsing` class.
This keeps the confirmation-pipeline tests deterministic and
non-flaky, and is a normal test-isolation technique, not a gap in
coverage.

## Explicitly NOT verified

- Backend test execution (`pytest`), frontend build/lint/type-check
  (`next build`, `tsc`), and OpenAPI schema validation — no network
  access to install dependencies.
- The actual SQL migration run against a real Postgres database (only
  reviewed against the SQLite-auto-create-tables path other CareerOS
  tests rely on, and against the syntax of the other `migrations/*.sql`
  files in this repo).
- A live LLM call through `app.ai.provider_router` (the intent-
  detection prompt's real-world JSON-compliance rate with an actual
  model, as opposed to the mocked/synthetic JSON used in tests).
- Wiring `app.career_agent.proactive.generate_proactive_notifications`
  into the existing APScheduler setup — the function is written,
  documented as scheduler-agnostic, and not itself registered as a
  job, by design (see the module docstring).
- Load/rate-limit behavior under real concurrent traffic.
