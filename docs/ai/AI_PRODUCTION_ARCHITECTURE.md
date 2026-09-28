# AI Production Architecture â€” V20.6

## Scope

V20.6 is a **stabilization release**: no new AI features, no
architecture redesign. This document describes the V20.1 AI
platform as it stands after the V20.6 audit, and marks what changed.

## The five AI modules, one gateway

Every AI-generating module (V20.2 resume_ai, V20.3 career_copilot,
V20.4 interview_ai, V20.5 skill_intelligence) calls through
`app.ai.completion_service.generate()` â€” the single entry point into
the V20.1 AI Gateway. None calls a provider SDK directly.

```
Business logic (resume_ai / career_copilot / interview_ai)
        â”‚
        â–¼
completion_service.generate()  â”€â”€â”€ moderation (optional)
        â”‚                      â”€â”€â”€ observability.record_event() (always, success or failure)
        â–¼
provider_router.complete()     â”€â”€â”€ retry (ai_max_retries) on the primary
        â”‚                      â”€â”€â”€ one fallback hop (ai_fallback_provider) â€” never a cascade
        â–¼
LLMProvider (anthropic / openai / gemini / openrouter)
```

**V20.5 skill_intelligence is the one module that does NOT call the
AI Gateway at all** â€” every computation there (normalization, graph
traversal, gap ranking, path building, assessment scoring, readiness
scoring) is deterministic. This was true before V20.6 and is confirmed
unchanged; see `AI_LEARNING_ARCHITECTURE.md`.

## No duplication (verified this release)

| Concern | Single implementation | Confirmed |
|---|---|---|
| Provider calls | `app.ai.provider_router` | Every module imports this; no direct SDK import outside `app/ai/providers/` |
| Resume analysis | `app.resume_ai.pipeline` | skill_intelligence.gap calls this, doesn't reimplement it |
| Skill gap | `app.resume_ai.skill_gap` + `app.skill_intelligence.gap` (V20.5, composes V20.2/20.3/20.4, doesn't replace) | Documented in `AI_LEARNING_ARCHITECTURE.md` since V20.5 |
| Career recommendations | `app.career_copilot` | skill_intelligence extends `CareerContext`, doesn't fork a second copilot |
| Interview evaluation | `app.interview_ai.evaluation_engine` | Numeric scores are pure deterministic aggregation (`report_engine.aggregate_scores`); only narrative text is AI-generated |

## What changed in V20.6

1. **Error-message sanitization** â€” `api/ai.py`, `api/career_copilot.py`
   no longer leak raw provider/SDK exception text to the client; full
   detail remains in `AIUsageLog` via the existing
   `observability.record_event` call.
2. **Prompt-injection wrapping extended to resume_ai** â€”
   `bullet_improver`, `project_improver`, `summary_generator` now wrap
   candidate-supplied text with the same `wrap_untrusted` delimiter
   `career_copilot`/`interview_ai` already used.
3. **AI data retention gap closed** â€” `DELETE /resume` now cascades to
   `ResumeAnalysis`/`ResumeAISuggestion`; `DELETE /ai/conversations/{id}`
   added (was missing on the generic surface, existed on
   career_copilot's equivalent surface).
4. **Missing V20.4 production migration written** â€” six Interview
   tables existed only as SQLAlchemy models with no `.sql` migration;
   see `V20_ARCHITECTURE.md` and `CHANGELOG_V20_6.md`.
5. **Performance**: `/skills` search pushed from Python into SQL;
   `/skills`, `/admin/skills`, `/admin/resources` bounded with `limit`.

No provider, prompt template, scoring formula, or business rule was
rewritten. See `CHANGELOG_V20_6.md` for the complete file list.

## Grounding architecture (unchanged, re-verified)

Every AI-generated narrative is grounded in facts fetched from the
database and handed to the model explicitly â€” the model narrates
those facts, it does not decide them:

- Resume summaries: built only from the candidate's own extracted
  `NormalizedProfile` fields.
- Career Copilot: `CareerContext` (profile, preferences, resume
  summary, saved jobs, applications, skill intelligence) â€” every field
  either has a real value or is named in `unknown_fields`, never
  silently omitted.
- Interview reports: numeric scores are aggregated from
  already-computed per-answer evaluations; only narrative text is
  AI-generated, and the prompt hands it the aggregates directly with
  an explicit "do not introduce a new score" instruction.
- Government eligibility: the copilot is instructed to relay a
  pre-computed eligibility result, never compute or state one itself.

## Known architectural notes (not fixed â€” out of scope for a
stabilization release, or working as designed)

- `resume_job_matches` isn't cascade-deleted when a resume is deleted
  (kept intentionally â€” see `AI_PRIVACY_GUIDE.md`).
- Coding-interview submissions are never executed in a sandbox
  (`sandbox_status` is honestly always `"unavailable"` â€” this was true
  before V20.6 and is a documented, not hidden, limitation).

