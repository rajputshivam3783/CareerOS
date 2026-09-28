# AI_INTERVIEW_PRIVACY.md — V20.4

## Ownership

Interview data belongs to the candidate. Every endpoint in
`app/api/interview_ai.py` that reads or writes session data goes
through `_owned_session`, which 404s — not 403 — on any session id
that isn't both found *and* owned by the calling user. 404 rather than
403 is deliberate: a 403 confirms the session exists (just isn't
yours); 404 doesn't even confirm that much.
`test_cross_user_access_is_404_not_403` in
`tests/test_v20_4_ai_interview.py` checks this across all six of the
endpoints most likely to leak ownership (report, current-question,
questions, start, pause, cancel).

There is no endpoint anywhere in this module that accepts another
user's id as a parameter, and no recruiter-facing route into this data
at all — unlike the V16 ATS `Interview` table (recruiter-scheduled real
interviews, a different concept this version doesn't touch),
`MockInterview*` data is never joined to a recruiter's job/applicant
view.

## No recruiter exposure

Per the spec: *"Do not expose private interview answers to recruiters
unless an explicitly authorized feature exists."* No such feature
exists in this version — there is no recruiter-role endpoint, no
admin-visible answer text, anywhere in `app/api/interview_ai.py`. The
one admin endpoint that exists, `GET /interview/usage`, exposes only
aggregate AI cost/latency telemetry (provider, model, success,
latency, operation name) via `app.ai.observability` — never a
question, an answer, or a score.

## Minimal logging of raw answers

Per: *"Do not log raw interview answers unnecessarily."* Candidate
answer text is only ever: (1) stored once in `MockInterviewAnswer.
answer_text` (overwritten on resubmission, not accumulated), and (2)
sent to the AI provider for evaluation, wrapped as untrusted content
(see below). It is never separately logged, and
`app.ai.observability`'s `AIUsageLog` — the only place AI call
metadata is recorded — stores provider/model/token counts/latency,
never prompt or response content (see V20.1's own
`AI_INFRASTRUCTURE.md` for that table's schema/intent).

## Audio

Per the VOICE_SUPPORT section (*"Do not store audio unnecessarily"*):
this version implements no audio storage or transcription pipeline at
all (see the "not implemented" note in `RELEASE_NOTES_V20_4.md`) — the
strongest form of "don't store it unnecessarily" is not building the
storage path in the first place until real Speech-to-Text/Text-to-
Speech infrastructure exists to design around.

## Prompt injection protection

Resume content, job descriptions, and candidate answers are all
treated as untrusted data, never instructions — the same posture V20.3
Career Copilot already established, reused via `app.career_copilot.
system_prompt.wrap_untrusted` rather than a second scheme:

- `evaluation_engine.py` wraps the candidate's answer (and the
  job/resume facts block) before sending to the model, and the system
  prompt explicitly instructs the model never to follow instructions
  embedded inside it.
- `question_engine.py` wraps the facts block the same way when
  phrasing a question.
- `followup_engine.py` wraps the candidate's prior answer the same way
  when phrasing a clarification.
- `report_engine.py` wraps the computed aggregates (trusted, since
  this module computed them itself) with an explicit "these are facts,
  do not contradict them" instruction — a different but related
  defense: preventing the narrative step from silently overriding the
  deterministic scores.

**Verified two ways** in `tests/test_v20_4_ai_interview.py`:

1. `test_evaluation_wraps_candidate_answer_as_untrusted` — monkeypatches
   the provider call to capture the exact prompt sent and asserts an
   injection-attempt string sits between
   `wrap_untrusted`'s header/footer markers (structural proof the
   delimiting actually happens, not just documentation of intent).
2. `test_injected_answer_never_actually_scores_100_when_ai_is_unavailable`
   — an end-to-end HTTP-level check that an answer textually demanding
   a perfect score gets the same honest, deterministic degraded
   evaluation as any other answer, never special-cased.

## AI safety

Never fabricates: job requirements (every job-specific question is
grounded in the real `Job.skills`/`qualification` fields, via
`get_public_job`, which 404s on any job that doesn't exist or isn't
published — see `context_builder.py`); resume content (project names
in resume-based questions are taken verbatim from
`NormalizedProfile.project_entries`, never invented — if no project
entries were extracted, the engine falls back to a generic prompt
rather than inventing one); interview results (no endpoint anywhere
promises or implies a real hiring outcome). No AI safety rule in the
V20.4 spec required a change to Authentication, Security, or RBAC —
none were touched.
