# V22.4 — AI Application Intelligence & Follow-ups

Adds an AI-assisted intelligence layer on top of the application
workspace (V22.1 tracking, V22.3 timeline/notes/interviews/tasks/
documents): application health, priority, next-best-action, follow-up
timing, risk factors, an action plan, AI-drafted follow-up emails, and
AI interview preparation suggestions. Reuses the V20.1 AI Gateway
end-to-end — no second AI framework, no new provider integration.

## Architecture

```
app/models/domain.py
    ApplicationAIInsight   — NEW: content-hash cache of generated AI output

app/applications/ai/
    signals.py         — deterministic engine (health/priority/next-action/
                          follow-up-timing/risks/action-plan). NO LLM CALL.
    context.py          — bounded, privacy-safe context builder for AI calls
    cache.py             — content-hash cache (mirrors app.resume_ai.cache)
    schema.py             — shared "extract JSON from raw LLM text" helper
    narrative.py         — POST .../ai/analyze  (AI explanation)
    followup.py          — POST .../ai/follow-up (AI email draft)
    interview_prep.py    — POST .../ai/interview-prep (AI prep suggestions)

app/api/
    application_ai.py    — NEW: all V22.4 HTTP endpoints
```

Nothing in `app/applications/service.py`, `application_workspace.py`,
or their API layers was touched. Every V22.4 function resolves
ownership through the same `service.get_application()` every other
V22.x module already uses.

## Why the core signals are deterministic, not AI-generated

Per spec: *"Do not let an LLM arbitrarily generate the numeric
score."* `app/applications/ai/signals.py` contains **zero** LLM calls.
Health score, priority, next-best-action, follow-up timing, risk list,
and action plan are all plain functions of data already in the
database (status, days since last activity, deadline proximity,
upcoming interview, overdue tasks, missing contact info), using named
threshold constants so every `+`/`-` reason is traceable and the same
application state always produces the same output. AI
(`narrative.py`) is only ever asked to *explain* these numbers in
prose — its system prompt explicitly forbids stating a different
score, and the JSON schema it must return has no numeric field at all,
so there's no field for a hallucinated number to land in even if the
model tried.

`GET /overview` and `POST /action-plan` / `POST /risks` never call an
LLM. Only `POST /analyze`, `POST /follow-up`, and `POST
/interview-prep` do.

## AI context builder

`app/applications/ai/context.py` builds a `facts_block()` — a short,
plain-text KNOWN FACTS list — from exactly:

- the application's own fields (company, job title, status, deadline)
- the already-computed deterministic signals (health, priority, next
  action, follow-up timing, risks) — the model explains these, never
  recomputes them
- up to 5 of the candidate's own recent notes, each capped to 500
  characters, wrapped in `app.career_copilot.system_prompt.
  wrap_untrusted()` so note content can never be read as an
  instruction (same prompt-injection defense Career Copilot already
  uses for job descriptions)
- for interview prep only: the target interview's own fields, plus a
  resume/skills summary already computed by
  `app.career_copilot.context_engine.build()` — reused, not
  re-fetched or duplicated

**Never included**, by construction (nothing in this module has a
handle on these): passwords, password hashes, JWT/session tokens,
another user's data, another application's data, or internal ids
beyond `application_id` itself. `user_id` is used only to run
queries — it is never written into prompt text.

## AI provider integration

Every AI-calling module (`narrative.py`, `followup.py`,
`interview_prep.py`) goes through exactly one entry point:
`app.ai.completion_service.generate()` — the same V20.1 Gateway
`app.career_copilot`, `app.resume_ai`, and `app.interview_ai` already
use. None of the three imports a provider directly; provider
selection, fallback, retry, and cost estimation all stay inside
`app.ai.provider_router`/`completion_service`, unchanged.

Each of the three follows the exact three-part shape
`app.interview_ai.evaluation_engine` established: a JSON-only system
prompt → `_parse_and_validate()` that requires the real fields to be
present (an empty/missing required field is treated as a parse
failure, not silently accepted) → a deterministic degraded-fallback
dict returned on *any* failure (`CompletionError`, i.e. every
configured provider failed; or an unparseable/incomplete response).
**No AI-calling function in this codebase ever raises out to its API
endpoint** — the endpoint always gets back a normal 200 with either a
real result or a `"degraded": true` one. A provider outage, timeout,
or malformed response degrades only the AI section of the workspace;
health/priority/risks/action-plan/the rest of the application
workspace are entirely unaffected.

## Caching

`app/applications/ai/cache.py` mirrors `app.resume_ai.cache` exactly,
keyed by `application_id` instead of `user_id` (an application already
belongs to one user). `ApplicationSignals.fingerprint()` returns the
subset of computed signals that would actually change AI output
(status, days since last activity, deadline days left, upcoming
interview id/result, overdue task count, health score, priority, next
action, follow-up timing) — `cache.make_context_key()` hashes that
(plus tone, for follow-ups, or interview id, for prep) into a
`context_key`. Same key → cache hit → zero additional provider calls.
A status change, new/updated interview, task change, or deadline edit
changes the fingerprint, which changes the `context_key`, which
naturally stops matching the old cache row — there is no separate
"invalidate" step to get wrong, satisfying spec section 12 by
construction rather than by a TTL or explicit bust.

Only generated *output* is cached (`content_json`) — never the prompt
sent to the model, and `app.ai.observability` (used automatically by
`completion_service.generate()`) already logs only token counts, cost
estimate, latency, and success/failure — never prompt or response
text.

## Schemas / response validation

`app/applications/ai/schema.py`'s `extract_json()` strips an optional
` ```json ` fence and parses; each feature module's
`_parse_and_validate()` then checks the specific required fields exist
and are non-empty, truncates every string/list to a bounded length
(cost + UI-safety), and returns `None` on anything else — which its
caller treats as a parse failure and returns the degraded fallback.
Nothing from a raw LLM response reaches the HTTP response unvalidated.

## Privacy & security

- Every endpoint requires `current_user` (existing JWT dependency) and
  re-resolves `application_id` ownership via `service.get_application`
  — a mismatched or foreign id is always a 404, matching the V22.3
  convention, before any AI or DB work happens.
- `moderate_text()` (existing V20.1 moderation service) screens
  candidate-authored free text (notes, interview notes) before it's
  sent in a prompt; a flagged result short-circuits to the degraded
  fallback rather than being sent to a provider.
- No endpoint here can change `Application.status`, delete anything,
  create an external account, or send an email — the follow-up
  endpoint only ever returns a subject/body pair for the candidate to
  copy themselves (spec section 15/section 5's "Do NOT send emails
  automatically" — there is no email-sending import or call anywhere
  in this feature).

## Cost control

- `enforce_rate_limit()` (existing V17.2 infrastructure, already used
  by `app.api.career_copilot`/`app.api.interview_ai`) caps every
  AI-calling endpoint (`analyze`/`follow-up`/`interview-prep`) at 20
  requests/60s per client IP under the shared `application-ai-generate`
  bucket.
- The cache above means a page reload or duplicate click doesn't cost
  a second provider call.
- `completion_service.generate()` already bounds context size via
  `settings.ai_max_context_tokens` and `max_tokens` is capped per call
  (500–700 depending on feature) here.
- The two purely-deterministic endpoints (`action-plan`, `risks`) and
  `GET /overview`'s deterministic fields never touch the LLM at all,
  so browsing the application workspace never has an AI cost.

## API

```
GET  /applications/{id}/ai/overview         — deterministic signals + last-cached narrative (no LLM call)
POST /applications/{id}/ai/analyze          — {force?} -> (re)generate the AI narrative
POST /applications/{id}/ai/follow-up        — {tone, force?} -> AI-drafted subject/body
POST /applications/{id}/ai/interview-prep   — {interview_id?, force?} -> AI prep suggestions
POST /applications/{id}/ai/action-plan      — deterministic, no LLM
POST /applications/{id}/ai/risks            — deterministic, no LLM
```

`tone` ∈ `{PROFESSIONAL, CONCISE, FRIENDLY}` (invalid values fall back
to `PROFESSIONAL`). `interview_id` defaults to the application's next
upcoming interview, then its most recently created interview, if
omitted; if the application has no interview at all, returns 400.

## Testing

`backend/tests/test_v22_4_ai_application_intelligence.py`:

- Deterministic engine, **no provider mocking**: new SAVED
  application → Low priority / "Apply now"; overdue task → shows in
  signals + risks + health reasons; upcoming interview → raises
  priority and next-action; deadline-soon → risk; ACCEPTED →
  Healthy/no-action; `action-plan`/`risks` endpoints proven to return
  cleanly with no provider mocked at all (would hang/fail if they
  tried a real network call)
- AI narrative: generation + caching (`from_cache` true on repeat, one
  provider call total), cache invalidation on status change, graceful
  degrade on provider failure (`AllProvidersFailedError`) and on
  malformed/non-JSON response — every case still returns HTTP 200
- Follow-up: subject/body generation, invalid tone falls back to
  PROFESSIONAL, confirms no send-related field ever appears in the
  response
- Interview prep: 400 with no interview on the application, generation
  with a real interview, 404 for a foreign `interview_id`
- Ownership isolation (IDOR) across all six endpoints
- Rate limiting: sustained calls eventually hit 429

All provider-touching tests monkeypatch
`app.ai.completion_service.route_complete` — the exact seam
`test_v20_3_ai_career_copilot.py` already established — so this suite
makes **zero real, paid LLM calls**.

**Execution status: NOT VERIFIED.** Same sandbox constraint as V22.3
— no network egress (`pip install`/`npm install` both re-confirmed
403 in this session). Every new/changed Python file passed `python -m
py_compile` and `ast.parse`; every new import, model field, function
signature (`CompletionResult`, `RoutedResult`, `AllProvidersFailedError`,
`completion_service.generate`, `moderate_text`, `context_engine.build`,
`wrap_untrusted`, `enforce_rate_limit`, `Application`/
`ApplicationInterview`/`ApplicationTask` fields) was manually
cross-checked against the actual existing code it calls into. Please
run `pytest backend/tests/test_v22_4_ai_application_intelligence.py`
and the full existing suite, plus `npm run build`, in an environment
with package-registry access before deploying.
