# INTERVIEW_ENGINE.md â€” V20.4

## State machine

`app/interview_ai/state_machine.py` â€” the only place
`MockInterviewSession.status` changes. A plain lookup table, no
branching logic:

```
draft --mark_ready--> ready --start--> in_progress
in_progress --pause--> paused --resume--> in_progress
in_progress --complete--> completed
{draft, ready, in_progress, paused} --cancel--> cancelled
```

Anything not in that table raises `IllegalTransitionError` (surfaced
as HTTP 409 by `app/api/interview_ai.py`) â€” e.g. you cannot resume a
completed session, or answer a question while paused. Every one of
these transitions and every illegal one is covered by
`tests/test_v20_4_ai_interview.py`'s `test_state_machine_*` tests
(12 parametrized illegal-transition cases alone), with no DB, HTTP, or
AI involved â€” pure function in, pure assertion out.

**Restart** is not a transition on the session itself â€” `POST
/interview/sessions/{id}/restart` creates a brand-new `draft`->`ready`
session with the same configuration (`state_machine.restart_config`)
and leaves the original (and its history/report, if completed)
untouched.

## The interview flow

```
Setup (POST /interview/sessions)
  -> Ready
Start (POST .../start)
  -> first Question generated
Candidate answers (POST .../answer)
  -> Evaluation
  -> weak answer (score < 50, not already a follow-up)?
       yes -> Follow-up Question -> back to "Candidate answers"
       no  -> reached planned_question_count?
                yes -> Final Evaluation aggregated -> Interview Report -> session completed
                no  -> Next Question generated -> back to "Candidate answers"
```

This is exactly the state machine the spec's flow diagram describes,
implemented as the branching in `app/api/interview_ai.py`'s
`submit_answer` (deterministic branching â€” no AI decides the *control
flow*, only the question phrasing/evaluation content within each step).

## Adaptive interviewing

`app/interview_ai/question_engine.py::next_difficulty` â€” a 3-rung
ladder (`easy` -> `medium` -> `hard`), moved by exactly one rung per
answer:

- Overall score **>= 80** -> difficulty increases one rung (capped at `hard`).
- Overall score **< 40** -> difficulty decreases one rung (floored at `easy`).
- Otherwise -> difficulty holds.

Weak answers get a **follow-up on the same question**, not a
difficulty change, first (`followup_engine.should_follow_up`: score <
50 and this isn't already a follow-up itself â€” capped at one follow-up
per top-level question, so a struggling candidate is never trapped in
a loop). Only if the *next* top-level question also opens with a weak
score does the difficulty ladder actually move down â€” this matches the
spec's distinction between "ask a clarification" (weak answer) and
"adjust difficulty" (candidate genuinely struggling across questions).

**No repeated questions**: every asked question's exact text is
tracked (`already_asked_text`, built from `MockInterviewQuestion.
question_text` for the session) and excluded from both the curated
question bank sampling and the AI-phrased candidate text before it's
accepted.

## Question categories -> interview type mapping

`question_engine._category_for_sequence` â€” deterministic rotation, one
category per question in sequence, covering every category in the pool
before repeating (verified by
`test_category_rotation_is_deterministic_and_covers_pool`):

| `interview_type` | Category pool |
|---|---|
| `technical` | programming, dsa, oop, dbms, os, computer_networks, system_design, cloud, sql |
| `data_science` | data_science, machine_learning, sql |
| `behavioral` | leadership, teamwork, conflict, failure, problem_solving, communication, ownership, adaptability |
| `hr` | (a fixed HR question set) |
| `coding` | coding problems, by difficulty |
| `system_design` | system_design only, increasing depth via the difficulty ladder |
| `resume_based` | grounded in the candidate's own resume project entries (verbatim names only â€” never invented) |
| `job_specific` | grounded in the selected job's real `skills` field |
| `mixed` | rotates technical / behavioral / hr |
| `custom` | the candidate's own `focus_skills`, matched against known technical categories |

## Coding interviews

See `CODING_INTERVIEW_SECURITY.md`.

## Pause / Resume / Restart / End

All four are plain state-machine actions (see above) exposed as
`POST /interview/sessions/{id}/{pause,resume,restart,cancel}`. Pausing
tracks `total_paused_seconds` (accumulated across multiple pause/resume
cycles) so a session's true "active" duration is always recoverable,
independent of wall-clock time between pause and resume.

