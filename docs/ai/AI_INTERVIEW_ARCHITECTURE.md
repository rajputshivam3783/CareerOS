# AI_INTERVIEW_ARCHITECTURE.md â€” V20.4

## What this is

`app/interview_ai/` (the engine) + `app/api/interview_ai.py` (the API)
+ 7 new `MockInterview*` tables (additive â€” see `app/models/domain.py`).
Built entirely on top of the V20.1 AI Gateway, V20.2 Resume
Intelligence, and V20.3 Career Copilot â€” none of those three modules
were modified.

## Reuse, not duplication

| Need | Reused from | Not built again |
|---|---|---|
| Calling an LLM, provider fallback, cost tracking | `app.ai.completion_service.generate` | No second provider router |
| Prompt-injection defense (delimiting untrusted text) | `app.career_copilot.system_prompt.wrap_untrusted` | No second wrapping scheme |
| Resume parsing/normalization | `app.resume_ai.pipeline.build_profile` | No second resume parser |
| Skill gap vs. a job | `app.resume_ai.skill_gap.analyze` | No second gap analyzer |
| Resume-vs-job match score | `app.resume_ai.job_match.match` | No second matcher |
| Content moderation | `app.ai.moderation_service.moderate_text` | No second moderation layer |
| Career narrative/explanation | `app.career_copilot.system_prompt.SYSTEM_PROMPT` (reused as the base prompt for report explanations) | No second recommendation engine â€” see `copilot_bridge.py`'s docstring |
| Public job lookup | `app.api.platform.get_public_job` | No second "does this job exist and is it published" check |
| Admin auth, rate limiting, current-user auth | `app.api.admin.guard`, `app.core.rate_limit.enforce_rate_limit`, `app.core.security.current_user` | Authentication/Security untouched |

## Module map

```
app/interview_ai/
  state_machine.py      deterministic status transitions (draft->ready->in_progress<->paused->completed/cancelled)
  sandbox.py             coding-execution abstraction â€” one honest "unavailable" implementation
  question_bank.py       curated fallback questions/problems per category â€” no AI dependency
  context_builder.py     composes job/resume/skill-gap facts (read-only, reuses V20.2)
  question_engine.py     deterministic category/difficulty selection + AI-assisted phrasing
  evaluation_engine.py   AI-assisted scoring with strict JSON validation + deterministic fallback
  followup_engine.py     deterministic follow-up trigger + AI-phrased clarification question
  report_engine.py       deterministic score aggregation + AI narrative (grounded in the aggregates)
  copilot_bridge.py      lets the existing Copilot explain a report (not a second engine)
app/api/interview_ai.py  the API surface â€” session lifecycle, questions/answers, coding, reports, history, admin
```

## Where AI is (and isn't) in the loop

Every engine module is split the same way, on purpose:

- **Deterministic logic in Python** â€” which category/difficulty comes
  next, whether to ask a follow-up, whether to increase/decrease
  difficulty, the numeric scores in the final report. Fully unit-
  tested with no mocking (`tests/test_v20_4_ai_interview.py`'s first
  three sections).
- **AI only for the parts that genuinely need natural language** â€”
  phrasing a question, scoring an answer's actual content, phrasing a
  follow-up, writing the report's narrative summary. Every one of
  these has a real, non-AI fallback (`question_bank.py`'s curated
  questions; a deterministic "could not evaluate" result; a template
  follow-up; a deterministic narrative built from the same aggregate
  numbers) â€” a provider outage degrades the experience, it never
  breaks it. See `TEST_REPORT_V20_4.md` for confirmation every one of
  these fallback paths was actually exercised (no AI provider is
  configured in the test/sandbox environment, so every AI-assisted
  call in the test suite genuinely takes its fallback path).

## Skill Gap Integration

When a session has `job_id` set and the candidate has a resume on
file, `context_builder.build` calls `app.resume_ai.skill_gap.analyze`
once per session and both (a) grounds job-specific questions in real
job skills, and (b) feeds `missing_skills`/`weak_skills` into the final
report's `technical_gaps` alongside per-answer weaknesses on technical
questions (`report_engine.collect_technical_gaps`).

## Career Copilot Integration

`POST /interview/sessions/{id}/report/explain` â€” see
`copilot_bridge.py`. Deliberately not a second recommendation engine:
it reuses the Copilot's own `SYSTEM_PROMPT` and answers exactly one
question (explain this already-computed report) from data this module
computed itself.

## Privacy

See `AI_INTERVIEW_PRIVACY.md`.

