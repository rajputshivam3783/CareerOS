# CareerOS â€” Career Copilot Architecture

## What this is

V20.3 adds `backend/app/career_copilot/` â€” a personalized career
assistant built entirely on existing CareerOS infrastructure: the
V20.1 AI Gateway, V20.2 Resume Intelligence, the V6 job-matching
engine, and the V5 government eligibility engine. It does not
introduce a second matching engine, a second eligibility engine, or a
second conversation store â€” see "Reuse, not rewrite" below for exactly
what's reused from where.

## The one rule everything else follows

**Deterministic logic decides, AI only narrates** â€” the same boundary
`app.resume_ai` established in V20.2, now applied to career guidance:

- Job recommendations (`job_recommendations.py`), the career roadmap
  (`roadmap.py`), the action plan (`action_plan.py`), and government
  eligibility guidance (`government_guidance.py`) are all composed by
  plain Python from already-computed, already-authorized data. A
  model is never asked "is this candidate eligible" or "what jobs
  should this person get" â€” those questions are answered by
  `app.services.eligibility.eligibility()` and
  `app.services.career.match_score()` respectively, both existing,
  both unchanged.
- The only genuinely generative surface is the chat itself
  (`assistant.py`) â€” and every chat turn is grounded in a context
  block that explicitly separates known, inferred, recommended, and
  unknown information (see CAREER_CONTEXT_ENGINE.md), with an explicit
  instruction never to invent beyond it (see AI_SAFETY.md).

This means every non-chat endpoint in this package (`/context`,
`/recommendations`, `/roadmap`, `/action-plan`, `/government-guidance`)
makes **zero AI calls** â€” cheap, instant, and impossible to
hallucinate in, by construction. Only `POST .../messages` costs a
token.

## Reuse, not rewrite

| Reused as-is | From |
|---|---|
| Conversation/message storage, provider routing, retry/fallback, usage logging | `app.ai.*` |
| Resume-grounded skill gap (when a resume exists) | `app.resume_ai.skill_gap` |
| Job-vs-profile matching, skill gap fallback (no resume) | `app.services.career.match_score` / `skill_gap` |
| Government eligibility verdicts | `app.services.eligibility.eligibility` |
| `current_user`, admin auth | `app.core.security`, `app.api.admin.guard` |
| Rate limiting | `app.core.rate_limit.enforce_rate_limit` |
| Public job lookup | `app.api.platform.get_public_job` |

Four small, additive functions were appended to the end of
`app.ai.conversation_manager` (`list_conversations`, `rename_
conversation`, `delete_conversation`, `clear_conversation`) â€” nothing
existing in that file was changed. This is what lets the Copilot's
"Conversation History / New / Rename / Delete / Clear" requirements
reuse the exact tables `/ai/conversations/*` already uses,
distinguished only by `context_type="career_copilot"` â€” no second
conversation store.

## Layout

```
backend/app/career_copilot/
- context_engine.py       Assembles one user's authorized data into
                           a CareerContext - known/unknown split.
                           Read by every other module and the chat prompt.
- career_preferences.py   CRUD for the candidate-defined career profile.
- job_recommendations.py  Thin wrapper on app.services.career.match_score.
- roadmap.py              Deterministic roadmap composition.
- action_plan.py          Deterministic, persisted action items.
- government_guidance.py  Thin wrapper on app.services.eligibility.
- system_prompt.py        Grounding rules + prompt-injection defense.
- assistant.py            The one module that calls the AI Gateway.
```

## Chat request flow

```
POST /career-copilot/conversations/{id}/messages
  -> conversation_manager.add_message(role="user", ...)     [V20.1, reused]
  -> assistant.send_message(db, conversation, message, ...)
       -> context_engine.build(db, user_id)                    known/unknown facts
       -> context_engine.to_prompt_text(context)                rendered block
       -> [if job_id given] system_prompt.wrap_untrusted(...)   job description, delimited
       -> conversation_manager.get_history + history_as_chat_messages   [V20.1, reused]
       -> app.ai.completion_service.generate(...)                [V20.1 Gateway - never a provider directly]
  -> conversation_manager.add_message(role="assistant", ...)  [V20.1, reused]
```

If every configured provider fails, `completion_service.generate`
raises `CompletionError`; `assistant.py` re-raises it as
`CopilotError`; the API layer turns that into a `503` with a clear
message (not a raw 500) â€” so the frontend's "Error recovery" state has
something specific to show and retry.

## Database

Two new, purely additive tables (`backend/migrations/
v20_3_ai_career_copilot.sql`; SQLite dev/test gets them for free via
`create_all()`):

| Table | Purpose |
|---|---|
| `career_preferences` | The candidate-defined career profile (target role, industry, work mode, etc.) â€” one row per user, all fields optional and self-reported. |
| `career_action_items` | Persisted action-plan tasks, upserted by a stable dedupe key so a candidate's done/dismissed status survives the plan being regenerated. |

Deliberately **not** persisted: job recommendations, the roadmap, and
government guidance. All three are cheap, deterministic, and
recomputed fresh on every request â€” storing them would mean either
serving stale advice or re-deriving the freshness check anyway, with
no benefit. See CAREER_CONTEXT_ENGINE.md for the reasoning on why
"context metadata" also isn't a separate stored table.

## What's intentionally not here

AI Interview System, AI Learning Platform, AI Mock Interviews, and
Advanced Career Assessment are V20.4+ (see `ROADMAP.md`) â€” this pass
stops at the Career Copilot, per the original brief's stop condition.

See also `CAREER_CONTEXT_ENGINE.md`, `CAREER_COPILOT_GUIDE.md`, and
`AI_SAFETY.md` for the detail this file doesn't cover.

