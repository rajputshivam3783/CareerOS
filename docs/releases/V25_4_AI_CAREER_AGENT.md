# V25.4 — Advanced AI Career Agent & Automation

Adds a candidate-facing, user-controlled AI Career Agent on top of
every prior CareerOS system, without rewriting or duplicating any of
them. This document covers architecture, the tool system, permissions,
the confirmation model, AI safety, prompt-injection protection,
privacy, database changes, the API, proactive notifications, cost
controls, observability, and testing — the same structure the spec
itself (section 37) asks for.

See also: [`V25_4_TEST_REPORT.md`](../V25_4_TEST_REPORT.md) for the
honest verification status of this release.

## 1. What this is, and isn't

The Career Agent (`/career-agent`) helps a candidate with career
planning, job discovery, skill-gap analysis, application planning,
interview prep, resume improvement, follow-up planning, learning
recommendations, and progress summaries — by calling the *existing*
V20–V25.3 services, never by re-deriving their answers.

It is deliberately **not**:
- A second recommendation/matching/ranking/eligibility engine (V21's
  `app.recommendations` and V21.1's `app.search` remain the only ones).
- A way for the LLM to query the database. The LLM never sees a table
  or writes a query; it only ever picks a tool name and parameters
  from a fixed whitelist (see §3).
- An autonomous agent that acts without asking. Every WRITE or
  HIGH_RISK tool call stops and asks for explicit confirmation before
  anything happens, and every external action (submitting an
  application, sending a message) is honest that CareerOS has no
  integration to actually do that yet — it never claims one it didn't
  perform.
- V25.5, or a rewrite of anything in V20–V25.3.

It also coexists with, and does not replace, V20.3's Career Copilot
(`/career-copilot`) — the Copilot remains a pure grounded-chat
advisor with no tool execution; the Agent is the tool-executing,
confirmation-gated layer above it. A candidate who just wants
conversational advice can keep using either.

## 2. Architecture

```
User
 -> POST /career-agent/conversations/{id}/messages
 -> agent_service.handle_message()
     -> UNDERSTANDING: build grounded context (career_copilot.context_engine, reused)
     -> intent.detect(): fast-path keyword match, else one structured
        AI call that must name a whitelisted tool or ask to clarify
     -> PLANNING: tool_registry.validate_call() — whitelists params,
        rejects anything unknown, coerces type. Nothing reaches a
        service function that wasn't validated here.
     -> risk routing:
          READ       -> EXECUTING now -> tool runs -> COMPLETED/FAILED
          WRITE      -> WAITING_FOR_CONFIRMATION (nothing runs yet)
          HIGH_RISK  -> WAITING_FOR_CONFIRMATION (nothing runs yet)
 -> (separately, only on user confirmation) POST /career-agent/actions/{id}/confirm
     -> actions.confirm_action(): EXECUTING -> tool runs exactly once -> COMPLETED/FAILED
```

`app/career_agent/state_machine.py` encodes the legal transitions
above and raises `IllegalTransitionError` on anything else — e.g. a
WRITE tool cannot reach EXECUTING except via
WAITING_FOR_CONFIRMATION, in code, not just by convention.

This is the concrete form of the required "LLM -> validated
tool/action -> backend service -> database" pipeline: the model's
output is parsed as JSON exactly once (`intent.ai_detect`), and
everything downstream of that parse is validated data, never a raw
string the model produced.

## 3. Tool registry

`app/career_agent/tool_registry.py` is the whitelist. Sixteen tools,
matching the spec's suggested list, plus the two HIGH_RISK external
actions:

| Tool | Risk | Reuses |
|---|---|---|
| `search_jobs` | READ | V21.1 `app.search.service.run_search` |
| `get_job_details` | READ | `app.api.platform.get_public_job` |
| `get_job_recommendations` | READ | V21 `app.recommendations.service` |
| `analyze_skill_gap` | READ | V25.3 `app.skill_intelligence.gap` |
| `get_career_intelligence` | READ | V25.3 `app.intelligence.candidate.overview` |
| `get_application` / `list_applications` / `get_application_timeline` | READ | V22.1 `app.applications.service`/`timeline` |
| `create_application_task` / `schedule_follow_up` | WRITE | V22.3 `app.applications.tasks` |
| `prepare_interview` | READ | V20.4/V22.4 `app.applications.ai.interview_prep` |
| `analyze_resume` | READ | V20.2 `app.resume_ai` |
| `get_learning_recommendations` | READ | V25.3 `app.skill_intelligence.learning_path` |
| `get_saved_jobs` | READ | `SavedJob` (V4/V21) |
| `get_notifications` | READ | V23.1 `app.notifications.service` |
| `summarize_career_progress` | READ | composition of the above, no new scoring |
| `submit_application` | HIGH_RISK | `Job.apply_url` — never actually submits (see §11) |
| `draft_followup_message` | HIGH_RISK | V22.4 `app.applications.ai.followup` — never actually sends (see §11) |

`validate_call(tool_name, raw_params)` rejects an unknown tool name,
rejects any parameter not declared for that tool, checks required
parameters are present, and loosely coerces type — it never evaluates
or executes a parameter value. `intent.py`'s AI path and its
deterministic fast-path both converge on this one function before
anything runs.

## 4. Permissions

Every tool here is candidate-only by construction: there is no
recruiter or admin tool registered in `tool_registry.TOOLS`, and
`app.career_agent.permissions.FORBIDDEN_TOOL_KEYWORDS` is a second,
explicit guard (checked by a test) against ever registering one by
name. Every handler in `tools.py` takes the authenticated `User` and
only ever reads/writes rows scoped to `user.id`; ownership is enforced
a second time inside the existing V22.1 service functions those
handlers call (`_get_owned`), so a bug in the Agent layer alone can't
skip it.

## 5. Confirmation model

`app/career_agent/actions.py` is the action lifecycle:

- A READ tool is logged **already COMPLETED** — this gives a full
  audit trail of every tool call, not just of writes.
- A WRITE or HIGH_RISK tool is logged **PENDING_CONFIRMATION**, and
  its underlying service function is not called at all until
  `confirm_action` runs — the write literally cannot happen without a
  separate, explicit confirm request.
- Confirming an action that is already COMPLETED/REJECTED/FAILED is
  rejected (`ActionNotPendingError`, HTTP 409) rather than silently
  re-executed — this is the idempotency guarantee against replay and
  duplicate execution (spec section 34).
- Confirmation prompts shown to the candidate (`agent_service._confirmation_prompt`)
  are fixed templates, not AI-generated — so a candidate is never
  shown confirmation wording the model invented, and a vague reply
  ("ok", "sure") can never be misread as consent: only an explicit
  `POST .../actions/{id}/confirm` call executes anything.

## 6. AI safety & hallucination prevention

- Every AI-narrated reply is grounded in a `TOOL RESULT` block
  containing exactly the (already validated, already executed) tool
  output — the model is instructed to relay and explain it, never
  recompute or contradict it, and to say "I don't have enough
  information to verify that" rather than guess (see
  `system_prompt.RESPONSE_SYSTEM_PROMPT`).
- No tool re-implements scoring/matching/eligibility logic — every
  number the Agent can show a candidate was computed by an existing,
  already-tested V20–V25.3 module.
- AI cost control (spec section 25): at most one AI call for intent
  detection (skipped entirely when the deterministic fast-path
  matches) and at most one more to narrate a result/answer a general
  question — a turn selects at most one tool, so there is no
  multi-step agentic loop to runaway-cap in the first place.
- A provider failure (`CompletionError`) degrades to a plain
  "temporarily unavailable" message — never a raw 500, never a
  fabricated answer.

## 7. Prompt injection protection

- The intent-detection prompt (`system_prompt.INTENT_SYSTEM_PROMPT`)
  receives only the candidate's own message and the tool catalog —
  never a resume, job description, or other untrusted document text —
  so there is nothing in that call for an injected instruction to hide
  inside.
- A tool result that echoes untrusted content (e.g. a job description
  inside `get_job_details`'s output) is delimited with the same
  `UNTRUSTED_CONTENT_HEADER`/`FOOTER` wrapper V20.3's Career Copilot
  already established (`system_prompt.wrap_tool_result` /
  `career_copilot.system_prompt.wrap_untrusted`), and the response
  system prompt explicitly instructs the model to treat it as data,
  never as instructions overriding this system prompt.

## 8. Privacy & data minimization

- `CareerAgentAction.payload_json` stores only the small, whitelisted
  tool parameters (job/application ids, a task title, a due date) —
  never a full resume or document body, never a secret.
- `CareerAgentPreference` is agent *behavior* configuration (proactive
  on/off, frequency, quiet hours, channels) and is never included in
  AI grounding context — it has nothing to do with career data.
- The Agent draws career-relevant grounding only from
  `career_copilot.context_engine` (profile, resume summary, saved
  jobs, applications, skill intelligence) — the same fields V20.3
  already uses, never protected attributes (health, religion, caste,
  political affiliation, sexual orientation).

## 9. Database

Four additive tables — see the migration
(`backend/migrations/v25_4_ai_career_agent.sql`) and the model
docstrings in `app/models/domain.py` for why these are new tables
rather than a reuse of `ai_conversations`/`ai_messages`:
`career_agent_conversations`, `career_agent_messages`,
`career_agent_actions`, `career_agent_preferences`. No historical
migration or table is modified.

## 10. API

Mounted at `/career-agent` (`app/api/career_agent.py`), registered in
`app/api/routes.py` alongside (not instead of) `/career-copilot`:

```
GET    /career-agent/tools
GET    /career-agent/conversations
POST   /career-agent/conversations
GET    /career-agent/conversations/{id}
PATCH  /career-agent/conversations/{id}
DELETE /career-agent/conversations/{id}
POST   /career-agent/conversations/{id}/archive
POST   /career-agent/conversations/{id}/messages
GET    /career-agent/pending-actions
POST   /career-agent/actions/{id}/confirm
POST   /career-agent/actions/{id}/reject
GET    /career-agent/preferences
PATCH  /career-agent/preferences
GET    /career-agent/brief
```

Every endpoint resolves the acting user from `current_user` (the
verified JWT) and passes only `user.id` into `app.career_agent` — no
endpoint accepts or trusts a caller-supplied user id.

## 11. High-risk external actions — the honest limits

CareerOS currently has no integration that actually submits an
application or sends a message to a recruiter on a candidate's
behalf. Both HIGH_RISK tools are built around that fact rather than
around a fiction:

- `submit_application` never sets `submitted: true`. It surfaces the
  job's `apply_url` (or explains there isn't one) and states plainly
  that CareerOS does not submit on the candidate's behalf.
- `draft_followup_message` never sets `sent: true`. It generates a
  draft (reusing V22.4's `app.applications.ai.followup`) and states
  plainly that CareerOS has no connected channel to send it — the
  candidate sends it themselves.

If a real submission/send integration is added in a future version,
these two tools are the place to wire it in — the confirmation model
around them does not change, only what happens after confirmation.

## 12. Proactive notifications & Career Brief

`app/career_agent/proactive.py` generates deterministic notifications
(new deadline within 3 days, new job matches) through the existing
V23.1 `create_notification` — reusing its `dedupe_key` idempotency
guarantee rather than building a second one — and respects
`CareerAgentPreference` (disabled entirely / quiet hours / frequency)
before creating anything. It is exposed as a plain function for a
scheduler to call; this pass does not register a new APScheduler job
(see the test report's NOT VERIFIED list).

`app/career_agent/brief.py` composes a "Career Brief" purely from
already-computed data (recommendations, upcoming deadlines, pending
tasks, unread notifications, skill progress) — no AI call — and says
"Nothing new to report today" rather than manufacturing content when
there's genuinely nothing new.

## 13. Observability

Every tool call already produces a `CareerAgentAction` row (tool
name, risk, status, timestamps) — this is the safe telemetry the spec
asks for, and it deliberately excludes secrets, full resume/document
text, and full conversation content beyond what a candidate typed.
`completion_service.generate`'s existing `AIUsageLog` recording
(provider, model, tokens, latency, success/failure) covers the two AI
calls a turn can make, unchanged.

## 14. Rate limiting

`POST .../messages` and `POST .../actions/{id}/confirm` go through the
existing `app.core.rate_limit.enforce_rate_limit`, each in its own
bucket (`career-agent-message`, `career-agent-action-confirm`) so they
don't share a budget with unrelated endpoints. A turn selects at most
one tool, so there is no "repeatedly calling the same tool" loop to
separately guard against.

## 15. Frontend

`/career-agent` (`frontend/src/app/career-agent/page.tsx`): a chat
tab with suggested prompts and inline confirm/cancel for a pending
action, a Pending Actions tab (the spec's "Action Center" — nothing
is hidden inside chat), a History tab, a Career Brief tab, and a
Preferences tab. Built with the same `api()` helper and
card/chip/btn/field styling every other candidate page already uses.

## 16. Testing

See [`V25_4_TEST_REPORT.md`](../V25_4_TEST_REPORT.md). Summary: 30+
tests written in `backend/tests/test_v25_4_ai_career_agent.py`
covering state-machine legality, tool-registry validation, the
recruiter/admin denylist, intent JSON-parsing safety, the READ/WRITE/
HIGH_RISK confirmation flows end-to-end (including idempotent
confirm/reject and cross-user isolation), AI-failure fallback,
preferences, and one regression check against the untouched V22
applications API — **not executed** in the authoring sandbox (no
network access to install dependencies); every service function
signature and model field referenced was instead checked directly
against source.
