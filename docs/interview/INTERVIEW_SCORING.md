# INTERVIEW_SCORING.md â€” V20.4

## Per-answer evaluation (8 dimensions)

Every answer is scored 0-100 on: **correctness, technical_depth,
relevance, clarity, communication, structure, confidence,
completeness** (`MockInterviewEvaluation`). `overall_score` is the
simple average of all eight â€” no hidden weighting, no separate AI
judgment of "overall" independent of the eight dimensions it's an
average of.

**"Do NOT generate arbitrary scores" is enforced structurally, not
just by instruction**: the model must return every one of the 8 scores
*and* an `explanation` in one JSON response
(`evaluation_engine._SYSTEM_PROMPT`); `_parse_and_validate` refuses to
store a response missing any required field or a non-JSON response,
falling back to `_degraded_result` (all scores `0`, `degraded=True`,
an honest "could not be evaluated" explanation) rather than ever
inventing a plausible-looking number itself. Every score is also
clamped to `[0, 100]` regardless of what the model returns
(`_clamp`) â€” a model hallucinating `150` or `"very good"` cannot
corrupt the stored data.

Every evaluation also returns, in the same response: `strengths`,
`weaknesses`, `missing`, `improvement_tips`, and one `stronger_example`
â€” see `FEEDBACK` below.

## Final report (6 dimensions)

`MockInterviewReport`'s scores are a **pure, deterministic aggregation**
of the per-answer evaluations already shown to the candidate during
the session (`report_engine.aggregate_scores` â€” plain averages, zero
AI calls, unit-tested directly with hand-built evaluation rows):

| Report score | Computed as |
|---|---|
| `overall_score` | average of every answer's `overall_score` |
| `technical_score` | average of `(correctness + technical_depth) / 2` per answer |
| `communication_score` | average of `(clarity + communication + structure) / 3` per answer |
| `problem_solving_score` | average of `(completeness + correctness) / 2` per answer |
| `role_fit_score` | average of `relevance` per answer |
| `confidence_score` | average of `confidence` per answer |

Because these are direct aggregates of numbers the candidate already
saw per-question, **the report can never disagree with the
question-by-question breakdown it's summarizing** â€” there's no second,
independent "how did they really do" AI judgment call to potentially
contradict the per-answer scores.

Only the *narrative text* (`summary`, `communication_feedback`,
`recommended_topics`, `next_steps`) is AI-generated
(`report_engine.generate_report_narrative`), and the prompt hands the
model the already-computed aggregate numbers and instructs it
explicitly not to introduce a new score or contradict them â€” it
narrates, it doesn't re-judge. If AI is unavailable, a deterministic
fallback narrative built directly from the same aggregate numbers is
used instead (`_fallback_narrative`) â€” never a blank report.

## Feedback (every answer)

Per the spec's FEEDBACK section, every `MockInterviewEvaluation`
carries all five required elements in one response:

- **What was good** â€” `strengths`
- **What was weak** â€” `weaknesses`
- **What was missing** â€” `missing`
- **How to improve** â€” `improvement_tips`
- **Example of a stronger answer** â€” `stronger_example` (a short
  illustrative opening/approach, explicitly not a full model answer to
  copy â€” see the evaluator's system prompt)

## Skill gap cross-reference

When the session has a job attached, `report_engine.
collect_technical_gaps` merges two sources into `technical_gaps`:
per-answer `missing` items on technical-category questions scoring
below 60, and the candidate's actual missing skills vs. the target job
from V20.2's `skill_gap.analyze` (reused, not recomputed) â€” so the
report's technical gaps reflect both "topics you struggled with in
this interview" and "skills the job wants that aren't on your resume."

