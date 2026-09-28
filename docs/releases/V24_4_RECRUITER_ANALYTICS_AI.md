# V24.4 — Recruiter Analytics & AI Hiring Intelligence

## Architecture

Two clean layers, one direction of dependency:

- **`app/recruiter_analytics/service.py`** — deterministic. Every
  number is a real SQL aggregate or a derived calculation over
  `applicants`, `recruiter_pipeline_history` (V24.3), `interviews`,
  `offer_letters`, and `jobs`. Zero LLM calls anywhere in this file.
  This is the source of truth.
- **`app/recruiter_analytics/ai.py`** — a thin explanation layer on
  top of `service.py`'s own output. It never recomputes a count, rate,
  or score; its only inputs are small, already-structured facts dicts
  built by `app/api/recruiter_analytics.py` from `service.py`'s return
  values. See "AI architecture" below.
- **`app/recruiter_analytics/cache.py`** — content-hash cache for the
  AI layer's output only (same design as V22.4's
  `application_ai_insights`).
- **`app/api/recruiter_analytics.py`** — the ten endpoints. Every one
  re-derives ownership from `team_owner_ids`/`_owned_job_or_404` — the
  exact functions V24.1–V24.3 already use, never a new or looser
  check.

Nothing in V16–V24.3 was modified except two lines: the `Job`/`Profile`
models gained no new columns (only `RecruiterAIInsight` is new), and
the pre-existing `/recruiter/analytics/page.tsx` was rewritten (see
"Frontend" below) since it *is* the location this spec asks the new
dashboard to live at.

## Analytics data sources

| Metric | Source | Notes |
|---|---|---|
| Job/application counts, stage counts | `jobs`, `applicants` | Direct aggregates |
| Conversion funnel | `recruiter_pipeline.service.conversion_metrics` (V24.3, reused unmodified) | Cumulative reach counts, zero-safe |
| Time-in-current-stage | `recruiter_pipeline.service.pipeline_stats` (V24.3, reused unmodified) | "How long has today's occupant been in this stage" |
| Point-to-point durations (first-review, app→interview, interview→offer, offer→hired, time-to-hire) | `recruiter_pipeline_history.new_stage`/`changed_at` (V24.3) | New in V24.4 — see "Time & bottleneck formulas" below |
| Stale candidates | `recruiter_pipeline.service.stale_candidates` (V24.3, reused unmodified) | Same one definition of "stale" everywhere |
| Candidate match distribution / comparison | `app.recommendations.matching`/`candidate_features`/`job_features` (V21.3/21.4) via `app.api.recruiter_candidates`'s own scoring helpers (V24.2, reused unmodified) | No second matching algorithm |
| Interviews / offers / hires / rejections / withdrawals | `interviews`, `offer_letters`, `applicants.pipeline_stage` | Direct counts |
| Job views, apply clicks, application-conversion-from-view, source/referral | **Not tracked anywhere in this schema** | Always reported as `None` under a fixed key set (`UNTRACKED_METRICS`), never fabricated — see "Untracked metrics" below |

### Untracked metrics — reported honestly, not invented

There is no page-view table, click-tracking table, or application-
source column anywhere in CareerOS. Spec section 3 is explicit that
these must not be fabricated if untracked, so
`GET /recruiter/analytics/jobs/{id}` always includes
`job_views: null, apply_clicks: null, application_conversion_pct: null,
source_breakdown: null` — a stable, documented "not tracked" contract
the frontend renders as literal text ("not tracked by this platform
yet"), never as a silent `0`.

### Time & bottleneck formulas

`average_time_to_first_review_days` etc. are computed from each
applicant's **first** arrival at each of five stages
(`new`/`reviewing`/`interview`/`offer`/`hired`), read from
`RecruiterPipelineHistory`. For a given pair (e.g. `new`→`interview`),
an applicant contributes a data point **only if they have reached
both** stages — an applicant still sitting in `reviewing` contributes
nothing to "time to interview," not a zero, not an estimate, not an
extrapolation. `sample_sizes` in the response tells the recruiter
exactly how many applicants each average is based on, so a `null`
average (zero applicants have reached both stages yet) is
distinguishable from "this pipeline is fast." This is the direct,
literal implementation of spec section 2's "do not treat incomplete
data as zero."

The **bottleneck observation** is deterministic: the stage with the
highest average time-in-*current*-stage, restricted to stages that
have at least one candidate sitting in them *right now* (a stage no
one currently occupies can't be today's bottleneck, even if it has a
historical average). When no stage qualifies, the response says so
plainly instead of naming a stage on stale data.

## API endpoints

All under `/api/v1/recruiter`, all `require_recruiter` + team-owned:

| Method | Path | Spec section |
|---|---|---|
| GET | `/analytics/overview` | 1.A |
| GET | `/analytics/pipeline` | 1.C, 2 (funnel + time/bottleneck together) |
| GET | `/analytics/applications-over-time?days=&job_id=` | 1.B |
| GET | `/analytics/time-in-stage?job_id=` | 2 |
| GET | `/analytics/jobs/{job_id}` | 3 |
| GET | `/analytics/jobs/{job_id}/candidates` | 4 |
| GET | `/analytics/stale-candidates?threshold_days=` | 6 |
| POST | `/analytics/ai/pipeline-summary` | 7 |
| POST | `/analytics/ai/candidate-comparison` | 8 |
| POST | `/analytics/ai/job-insights/{job_id}` | 9 |

`/analytics/pipeline` intentionally answers both the spec's separately
-listed `/analytics/pipeline` (funnel) and part of `/analytics/time-
in-stage` in one call (it returns both), because a recruiter viewing
the funnel almost always wants the bottleneck observation in the same
glance; `/analytics/time-in-stage` still exists standalone too for a
job-scoped, funnel-free read. This is the same "fold rather than
duplicate" reasoning V24.1/V24.2 used elsewhere in this project.

`job-insights` takes `job_id` as a path parameter (not a body field
like the spec's illustrative `POST /analytics/ai/job-insights`) to
match this codebase's existing convention of path-scoping a specific
owned resource (see every `/jobs/{job_id}/...` route already in
`recruiter.py`/`recruiter_candidates.py`/`recruiter_pipeline.py`)
rather than trusting a body-supplied id.

## Authorization model

Identical posture to V24.1–V24.3, extended to every new endpoint:

- `require_recruiter` — approved recruiter role, checked first.
- `team_owner_ids(db, recruiter)` — every cross-job endpoint
  (`overview`, `pipeline`, `applications-over-time`,
  `stale-candidates`) is scoped to exactly this recruiter's team's job
  ids; never all jobs.
- `_owned_job_or_404` — every job-scoped endpoint 404s (not 403s) for
  another team's job, so a recruiter can never distinguish "not yours"
  from "doesn't exist."
- `_authorized_candidate_ids` (V24.2, reused) — candidate comparison
  re-validates every candidate id in the request against this
  recruiter's authorized discovery pool (applied to this job/team, or
  opted in) before scoring or sending anything to the AI layer. A
  candidate id that fails this check is rejected with 404, not
  silently dropped or silently scored.
- The AI layer receives **only** whatever the API layer already built
  from an authorization-checked read — it has no database access of
  its own and cannot expand its own context.

## AI architecture

Three capabilities, one shared pipeline (`ai._generate_grounded`):
build facts → check cache → call `app.ai.completion_service.generate`
(V20's own provider-fallback router, reused unmodified — its own
timeout/retry/fallback-across-providers logic is not reimplemented
here) → parse strict JSON → run the fairness/no-decision guard → cache
→ return. Every step degrades gracefully; nothing here can crash the
dashboard (see "AI failure fallback").

### Grounding (no hallucination)

- The system prompt for every capability states: every fact must come
  from the JSON facts block, unavailable facts must be stated as
  unavailable, and numbers in prose must match the given numbers
  exactly.
- The facts block itself contains only outputs already computed by
  `service.py` — pre-aggregated counts, rates, and match-component
  scores. No raw resume text, no application notes, no interview
  transcripts are ever included. For the pipeline summary, stale
  candidates are identified only by `applicant_id`/`job_id`/stage/
  days-inactive — deliberately not by name, to minimize what a
  third-party provider ever sees.
- The model has no field in its output schema for a number — its JSON
  is `{"summary": str, "points": [str, ...]}` only. Every count/rate
  the recruiter sees on screen still comes from `service.py`'s
  response, displayed next to (not generated by) the AI block.

### Untrusted input handling (prompt-injection resistance)

Job descriptions, `job.skills`, and any other recruiter- or candidate-
authored free text are **never interpolated into a prompt**. The facts
dicts only ever carry short structured values (a skill's canonical
name, a stage name, a count, a boolean like
`job_has_skills_listed`) — there is no code path from a job
description's or a resume's raw text into anything the model could
read as an instruction. The job-insights system prompt additionally
states explicitly that any job text is data, not instructions, as
defense in depth even though no raw job text is actually passed today.

### Fairness & responsible AI (spec section 10, required)

Three layers:

1. **Prompting** — every one of the three system prompts states the
   full list of protected/sensitive characteristics and instructs the
   model never to use, infer, or mention any of them, and never to
   make a hiring decision, declare a "best" candidate, or rank by
   anything but the given numeric match signals.
2. **Schema** — there is no output field for a decision or a ranking;
   `points` are free-text observations, not a sorted "recommendation"
   list, and candidates are always presented sorted by the
   *deterministic* `match_score` from `service.py`, never by anything
   the AI proposes.
3. **Post-hoc keyword guard** (`ai._guard_text`) — a deterministic,
   final check of the model's own free-text output for protected-
   attribute language (race, ethnicity, caste, religion, gender,
   sexual orientation, disability, marital status, pregnancy,
   political affiliation, nationality/immigration) or hiring-decision
   phrasing ("should hire," "best candidate," "reject this
   candidate," etc.). A match replaces that text with a neutral
   placeholder and sets `"flagged": true` on the response so the
   recruiter always sees a visible signal, never a silently-edited
   answer. **This is explicitly a coarse safety net, not a bias-
   detection system** — it catches the model literally writing a
   disallowed word or phrase; it cannot catch subtler bias in how the
   model chose to phrase an otherwise-compliant sentence. Layers 1-2
   are the primary safeguard; layer 3 is what stops a rare prompt
   failure from ever reaching the recruiter's screen unfiltered.

None of the three AI features can move a candidate, reject an
applicant, or change any stored data — every one of them is read-only
with respect to hiring state.

### AI failure fallback (spec section 14)

`_generate_grounded` catches `CompletionError` (raised after V20's own
router has already tried every configured provider) and returns a
`degraded: true` response — `{"summary": "AI analysis is currently
unavailable (...). The figures above were computed directly and are
still accurate.", "points": [], "degraded": true}` — with HTTP 200,
never a 5xx. The deterministic sections of the dashboard are entirely
unaffected, since they never call into `ai.py` at all. The same
degraded shape is used for an unparseable AI response.

### Caching / invalidation (spec section 13)

`RecruiterAIInsight` mirrors V22.4's `ApplicationAIInsight`
content-hash design (see that model's docstring for the original
rationale): `context_key = sha256(kind + json(facts))[:32]`. There is
no separate "invalidate on pipeline change" step to get wrong — any
change to the underlying facts (a stage move, a new application, a job
edit) changes the facts dict, which changes the hash, which is a
cache miss by construction. A repeat request with unchanged facts is
always served from cache with zero additional provider calls (cost
control). `force: true` in any AI request body bypasses the cache for
that one call and re-generates (and re-caches under the same key,
since the facts haven't changed) — useful if the recruiter wants a
fresh phrasing rather than fresher data (fresher data always
invalidates automatically).

## Performance

- Every cross-job endpoint loads this recruiter's own jobs/applicants
  once (`_my_jobs`/`_applicants_for_jobs`) and does all further
  computation in Python over that already-bounded set — no N+1 query
  loop per applicant.
- `_first_reached_at` is a single `WHERE applicant_id IN (...) AND
  new_stage IN (...)` query, not one query per applicant per stage.
- Candidate match scoring (`candidate_match_analytics`/
  `compare_candidates`) is bounded to this job's actual applicants (or,
  for comparison, the specific requested ids — max 8 per request), not
  the platform-wide candidate pool.
- AI calls are cached (see above) and rate-limited
  (`enforce_rate_limit`, 20/minute per IP per the shared
  `"recruiter-analytics-ai"` bucket — the same mechanism V22.4's AI
  endpoints already use).
- No LLM call happens on any deterministic endpoint — confirmed by
  `service.py` having zero imports from `app.ai`.

## Frontend

`frontend/src/app/recruiter/analytics/page.tsx` was rewritten (not
added elsewhere — this is the exact route the spec asks for and the
one the app already linked to from the recruiter dashboard/jobs
pages). Sections: KPI cards, application trend (day-by-day bar chart,
selectable 7/30/90-day range), hiring funnel with per-step conversion,
time-in-stage + bottleneck observation, AI pipeline summary, job
performance (job selector), candidate match distribution with a
candidate-comparison picker, AI job insights, AI candidate comparison,
and a configurable-threshold stale-candidates list. Loading/empty/
error states are handled at both the page level and per-section
(e.g., "No applications in this range yet," "No stale candidates at
this threshold").

**Incidental fix:** the pre-existing analytics page's `STAGE_LABEL` map
still used V18.2-era stage names (`applied`, `screening`,
`technical_round`, `hr_round`, `accepted`) that V24.3 had already
replaced (`new`, `reviewing`, `shortlisted`, `assessment`, `interview`,
`offer`, `hired`). Since this page is being rewritten anyway, the new
`STAGE_LABEL` map uses the current V24.3 stage vocabulary throughout.

## Configuration

No new environment variables. AI capabilities reuse whichever provider
keys `app.ai.provider_router` is already configured with; if none are
configured, every AI endpoint returns the degraded shape (see above)
rather than erroring.

## Security review performed (manual/static)

- **Authorization / object-level / company isolation** — see
  "Authorization model" above; every endpoint reuses V24.1–V24.3's own
  ownership functions.
- **AI context authorization** — the AI layer never queries the
  database itself; it only receives facts the API layer already built
  from an authorization-checked read.
- **Prompt injection** — no raw candidate/job free text is ever placed
  in a prompt (see "Untrusted input handling" above); the job-insights
  prompt states explicitly that any job text is data, not instructions,
  as defense in depth.
- **Sensitive data leakage** — pipeline-summary facts identify stale
  candidates by id, not name; no endpoint returns password/auth
  fields; resume text is never included in any analytics facts block.
- **Mass assignment** — every AI request body is an explicit Pydantic
  allow-list (`AIRequestIn`, `CandidateComparisonIn`, `JobInsightsIn`);
  `candidate_ids` is bounded to 2-8 entries and every id is
  re-validated server-side against the authorized pool regardless of
  what the client sends.
- **Parameter validation** — `threshold_days` and `days` are bounded
  (`ge=`/`le=`) `Query` parameters, not raw strings.
- **Rate limiting** — all three AI POST endpoints share a
  `"recruiter-analytics-ai"` bucket (20/min/IP), the same
  `enforce_rate_limit` mechanism already used for every other AI
  endpoint in this codebase.
- **Audit logging** — each AI call logs `recruiter_ai_pipeline_summary`
  / `recruiter_ai_candidate_comparison` / `recruiter_ai_job_insights`
  via the existing `app.core.audit.log_audit` (no second audit
  system), recording that the action happened, never the generated
  content.

This was a manual code review, not an automated SAST scan or live
penetration test.

## Testing

`backend/tests/test_v24_4_recruiter_analytics_ai.py` — 13 new tests.
Deterministic-endpoint tests run with **no AI provider mocking at
all** (to prove those endpoints never touch the LLM layer); AI-endpoint
tests mock `app.ai.completion_service.route_complete` at the same seam
`test_v22_4_ai_application_intelligence.py` already established, so no
real, paid LLM call happens in this suite. Covers: overview on an
empty recruiter and a populated one, funnel zero-denominator handling,
time-in-stage correctly excluding an applicant who hasn't reached a
stage (never treating it as zero), configurable stale-candidate
threshold, job analytics + match distribution, cross-recruiter
isolation (list and per-job endpoints), AI pipeline-summary
generation + cache hit on a second identical call, AI graceful
degradation when every provider fails, the fairness guard actually
withholding protected-attribute/hiring-decision language, candidate-
comparison rejecting an unauthorized candidate id (IDOR), job-insights
never fabricating an untracked metric, and a role check (a candidate
account cannot call recruiter analytics AI).

## PASS / FAIL / NOT VERIFIED

| Check | Result |
|---|---|
| `python -m py_compile` / `ast.parse` on every changed/added Python file | **PASS** — ran in this sandbox |
| Isolated `tsc` structural check on the rewritten analytics page | **PASS** — no syntax errors; only "missing type declarations"/"no JSX.IntrinsicElements" noise expected from having no `node_modules` in this sandbox |
| New backend tests (13) | **NOT VERIFIED** — this sandbox has no outbound network access, so `pip install` for `fastapi`/etc. fails and the suite cannot be executed here. Written to the exact `pytest`/`TestClient`/`monkeypatch` pattern this repo already uses (`test_v22_4_ai_application_intelligence.py`, `test_v24_3_candidate_pipeline.py`); needs a real environment to run. |
| Full existing backend suite (V20-V24.3 regression) | **NOT VERIFIED** — same reason. Every change in this version is additive (new package, new API file, one new model/table, a rewritten frontend page) — no existing function's signature or behavior was altered, so no regression is *expected*, but that is not the same as a passing run. |
| Frontend build / type-check / lint | **NOT VERIFIED** — same sandbox limitation (no `npm install`). |
| Manual security review | **PASS** (manual/static) — see "Security review performed" above. |
| Migration validity | **PASS** (manual review) — one new `CREATE TABLE IF NOT EXISTS` + indexes, same pattern as every prior additive migration in this repo; SQLite dev path re-derives the same schema from the model automatically. |
| OpenAPI validation | **NOT VERIFIED** — requires running the app, which requires the dependencies this sandbox cannot install. |

## Known limitations

- **Job views / apply clicks / application source are not tracked** —
  explicitly reported as `null`, not estimated. Adding real tracking
  is out of scope for this version (would need new event tables,
  which the spec explicitly says not to add without genuine need).
- **Point-to-point time metrics use first-arrival timestamps only** —
  if an applicant moves backward and forward through a stage multiple
  times, only their first arrival at each stage counts toward these
  averages (consistent with "time to reach X the first time," not
  "total cumulative time"). `average_time_in_stage_days` (current-
  occupant time) is a separate, complementary number for exactly this
  reason.
- **The fairness guard is a coarse keyword/phrase filter**, not a bias
  -detection system — see "Fairness & responsible AI" above for
  exactly what it can and cannot catch.
- **AI candidate comparison is capped at 8 candidates per request** —
  a deliberate bound on prompt size/cost, not a data limitation.
- **Tests were not executed** (see table above) — code-review-complete,
  not deployment-verified, until run in a real environment.
- The pre-existing bare `GET /recruiter/analytics` endpoint (V9) is
  left completely unchanged for backward compatibility, even though
  its stage-name assumptions and the new `/analytics/overview`
  endpoint now overlap in purpose — no caller of the old endpoint was
  broken by this version.

## Files changed

- `backend/app/models/domain.py` — `RecruiterAIInsight` (new).
- `backend/migrations/v24_4_recruiter_analytics_ai.sql` — new.
- `backend/app/recruiter_analytics/__init__.py`, `service.py`,
  `ai.py`, `cache.py` — new package.
- `backend/app/api/recruiter_analytics.py` — new (all 10 endpoints).
- `backend/app/api/routes.py` — router registration.
- `backend/tests/test_v24_4_recruiter_analytics_ai.py` — new.
- `frontend/src/app/recruiter/analytics/page.tsx` — rewritten.
- `CHANGELOG.md`, `README.md` — version entries.
