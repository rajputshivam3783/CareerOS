# AI Learning & Skill Intelligence Architecture â€” V20.5

## Design principle

One canonical Skill model, composed into by every feature â€” never a
second parallel vocabulary or a second gap/ranking engine. V20.5 adds
exactly one new package, `app.skill_intelligence`, and touches
existing V20.1â€“V20.4 code in exactly one place (`career_copilot.context_engine`,
additively) to surface it.

```
app/skill_intelligence/
    catalog.py          Phase 1 â€” seed skills/aliases/graph, idempotent
    normalization.py     Phase 1 â€” alias â†’ canonical resolution
    graph.py              Phase 1 â€” prerequisite/related/... traversal
    gap.py                 Phase 1 â€” unified gap: composes V20.2 + V20.3 + V20.4
    resources.py             Phase 2 â€” verified-resource lookups
    learning_path.py          Phase 2 â€” ordered, resourced skill sequence
    plans.py                    Phase 2 â€” LearningPlan lifecycle
    assessments.py                Phase 3 â€” MCQ scoring, weak topics
    practice.py                     Phase 3 â€” practice/project/cert guidance
    readiness.py                      Phase 3 â€” explainable readiness scores
```

## AI Gateway usage

**None of the above calls an AI provider.** Every V20.5 computation â€”
normalization, graph traversal, gap ranking, path building, plan
lifecycle, assessment scoring, practice recommendations, readiness
scoring â€” is deterministic: string/graph lookups and a fixed,
documented formula. This mirrors `app.resume_ai.skill_gap` and
`app.services.career` (V20.2/earlier), which are also deterministic.

If a future phase adds an AI-assisted feature (e.g. a natural-language
"explain my readiness" narrative), it must go through the V20.1 AI
Gateway (`app.ai.provider_router`, `app.ai.prompt_service`,
`app.ai.context_builder`) exactly like `app.career_copilot.assistant`
and `app.interview_ai` do â€” never a direct provider call from
`app.skill_intelligence`.

## Composition, not duplication

| V20.5 needs | Reuses | Never |
|---|---|---|
| Resume-vs-job skill gap | `app.resume_ai.skill_gap.analyze` | Re-parses or re-matches skills itself |
| Career goal | `CareerPreference` | A second preferences table |
| Interview weak areas | `MockInterviewReport.technical_gaps_json` | A second interview-scoring pass |
| Copilot explanations | `career_copilot.context_engine.CareerContext`, extended additively | A second AI career engine |
| Resume upload/profile | `app.resume_ai.pipeline.build_profile` | Its own resume parser |

`app.skill_intelligence.gap.compute()` is the one place all of the
above meet â€” see `SKILL_INTELLIGENCE.md`.

## Career Copilot integration

`context_engine.CareerContext` gained one field, `skill_intelligence`,
populated by reading (never recomputing differently):

- `gap.compute()` â†’ `priority_skill_gaps`, `unrecognized_skill_inputs`
- the candidate's active `LearningPlan` + `plans.progress()` â†’ `active_learning_plan`
- `readiness.compute()` â†’ `readiness`

Missing pieces (no gap yet, no active plan, no readiness data) are
named explicitly in `unknown_fields` â€” the same "known vs. unknown"
contract every other `CareerContext` field already follows â€” so the
copilot's grounding rules (`system_prompt.py`) apply to this data
exactly like everything else: relay it as given, never invent or
recompute a different value. `system_prompt.py`'s hallucination-
prevention list was extended to name learning/skill-gap/readiness
data explicitly.

`GET /api/v1/career-copilot/context` now includes `skill_intelligence`
in its response; every other field is unchanged.

## Interview integration

One-directional by design, matching the spec's worked example (Weak
SQL Interview Performance â†’ SQL Fundamentals â†’ Practice â†’ Assessment â†’
Repeat Interview): `gap.compute()` reads
`MockInterviewReport.technical_gaps_json` /
`recommended_topics_json` and folds them into the unified gap with
their own `source_signals` (`weak_interview_performance`,
`recommended_by_interview_report`). `app.interview_ai` itself is
untouched â€” V20.5 only reads its output.

## AI safety posture (unchanged rules, now also applied to V20.5 data)

- **Never fabricate skills** â€” `normalization.py` returns unrecognized
  input as unrecognized, never invents a canonical skill.
- **Never fabricate resources/URLs** â€” every `LearningResource` is
  admin-entered; `resources.py` only reads published+verified rows.
  Same rule extended to `practice.py`'s project/certification
  recommendations (they reuse `LearningResource`, never invent one).
  See `RESOURCE_MANAGEMENT.md`.
- **Never fabricate market demand** â€” not implemented in V20.5 (no
  external job-market data source exists yet); `gap.py`'s priority
  score uses only job-mention count, interview weakness, and career
  goal â€” all real, in-platform signals.
- **Never fabricate assessment answers** â€” questions and correct
  answers are admin-authored (`assessments.py`); scoring is exact
  match, never AI-judged.
- **Explainable, not black-box, scoring** â€” every `SkillGapItem` and
  every `ScoreComponent` (readiness) carries a plain-English reason
  and its source inputs.

## Testing

Four test files, 36 tests total, all passing:
`test_v20_5_skill_intelligence.py` (13), `test_v20_5b_learning_paths.py`
(10), `test_v20_5c_assessments_readiness.py` (10),
`test_v20_5d_copilot_integration.py` (3). See `TEST_REPORT_V20_5.md`
for the full run log and the pre-existing V16â€“V20.4 baseline
comparison.

