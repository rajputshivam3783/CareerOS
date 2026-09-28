# RANKING_ENGINE_V21_4.md

## Component weights

`app.recommendations.ranking_config.DEFAULT_COMPONENT_WEIGHTS`, all
admin-overridable via `RankingConfiguration` (never exposed to normal
candidates). V21.3's original weights (skill 30 / resume 15 /
experience 15 / education 10 / location 10 / career_goal 10 /
work_mode 5 / recency 5) were rebalanced to make room for the two new
components, keeping every original component's *relative* proportion
to each other roughly intact:

| Component | V21.3 weight | V21.4 weight | Rationale |
|---|---|---|---|
| skill | 30 | 26 | Still the single largest factor |
| resume | 15 | 13 | |
| experience | 15 | 13 | |
| education | 10 | 9 | |
| location | 10 | 9 | |
| career_goal | 10 | 9 | |
| work_mode | 5 | 4 | |
| recency (freshness) | 5 | 4 | |
| **behavior** (NEW) | â€” | **9** | Learned signal â€” meaningful but never dominant; a candidate with zero history isn't disadvantaged (redistribution rule below) |
| **deadline_urgency** (NEW) | â€” | **4** | Nudges timely applications without overriding fit |

These are documented business assumptions, not learned weights â€” an
admin can retune them via `PUT /job-recommendations/admin/ranking-config/component_weights`
(see RANKING_EXPERIMENTS.md for measuring the effect of a change).

**Redistribution rule (unchanged from V21.3):** when a component is
unavailable (no data to score it from), its weight is not silently
zeroed â€” the remaining available components' weights are scaled up
proportionally so they still sum to 100%. A candidate with
personalization off, or with no behavioral history yet, is scored
purely on their explicit stated preferences, redistributed across
skill/resume/experience/etc â€” never penalized by a phantom zero for
"behavior."

## Event weights (SIGNAL QUALITY)

`DEFAULT_EVENT_WEIGHTS` â€” see `ranking_config.py`'s own docstring for
the full table and per-event rationale. Summary: Apply (1.00) > Save
(0.60) > Interested (0.50) > Share (0.40) > Open (0.30) > Filter Usage
(0.10) > Impression (0.05); negative: Not Interested (-0.40) > Dismiss
(-0.60) > Not Relevant (-0.80). Configurable via
`PUT /job-recommendations/admin/ranking-config/event_weights`.

## Time decay

Exponential half-life decay, default 21 days
(`time_decay_half_life_days`): `score_after(t) = score_before * 0.5 ** (t / half_life)`,
applied to a signal's existing score *before* adding a new event's
weight, every time a new event for that signal key arrives (see
`app.recommendations.events._decay_factor`/`_update_aggregates`).
Older behavior fades continuously rather than being deleted in a
batch job, and a signal untouched for one half-life has already lost
half its influence.

## Negative signals â€” dampen, never permanently exclude a category

Every `BehaviorSignalAggregate.score` is clamped to `[-5.0, 10.0]`
(`SCORE_CLAMP`) on every update. A burst of `not_relevant` events
against, say, Government roles can only ever drag that signal's
contribution down to the floor â€” it can never be pushed further
negative, and it decays back toward zero over time like any other
signal even with no further interaction. Government roles as a whole
are never excluded; only the *specific* job a candidate explicitly
dismissed is excluded (via the pre-existing, per-job
`RecommendationFeedback` mechanism, untouched from V21.3).

## Deadline-aware ranking (freshness/urgency)

`matching._deadline_urgency_match`: unavailable when a job has no
verified deadline (never fabricated); otherwise a fixed, documented
step function of days-remaining (â‰¤2 days â†’ 100, â‰¤5 â†’ 85, â‰¤14 â†’ 50,
else â†’ 20). Government deadlines are exactly the `Job.deadline` field
already populated from verified government source data (V19.1/V21.3) â€”
this component reads that field as-is, never estimates or infers one.

## Diversity

`diversity.py`'s existing greedy score-order walk (V21.3, unchanged in
mechanism) now also caps `opportunity_type` (Government/Private/
Internship/Apprenticeship) alongside company/location/title. Same
guarantee as before: a capped item is deferred, never dropped â€” the
output is always a bounded reordering of the top-N by score, never a
relevance cut.

## New-job cold start

See PERSONALIZATION_ARCHITECTURE.md's `cold_start.py` entry.
Independently, every candidate's core ranking (not just cold-start
candidates) already boosts brand-new jobs via the `recency` component,
which scores purely off `Job.created_at`/`start_date` â€” never off
engagement counts â€” so a new job's general visibility was never tied
to interaction history in the first place; only the cold-start
*supplemental* pool had that bias, now fixed.

## ML READINESS (interfaces only, nothing implemented)

Per "Do NOT implement complex ML models in V21.4 unless the existing
repository already contains a tested model that can safely be
reused" â€” it doesn't, for ranking specifically, so none is used.
What's positioned for a future phase without committing to one yet:

- `BehaviorSignalAggregate` is already a feature store in miniature â€”
  one row per (user, signal_type, signal_key) with a real-valued
  score â€” the same shape a learning-to-rank feature pipeline would
  want to read from, without this phase needing to build one.
- `ranking_config.py`'s weight dictionaries are a natural place a
  future learned model's output would replace a hand-set constant,
  one component at a time, without changing `scoring.score()`'s call
  shape.
- `experiments.py` gives a way to roll out a future model to a
  controlled percentage of users and measure it against the existing
  deterministic baseline via the same event log â€” before this phase,
  there was no way to do that at all.

None of this is wired to an actual model. Core ranking works, and is
tested, with zero ML training infrastructure.

## AI USAGE

No LLM call sits anywhere in the ranking hot path (unchanged from
V21.3 â€” `explanations.py` is deterministic template composition, not a
model call). `app.ai.observability.live_provider_health()` is surfaced
in admin analytics purely for visibility into unrelated AI features
(resume parsing, interview questions, etc.) elsewhere in the product â€”
ranking has no dependency on it, and the admin analytics response says
so explicitly (`"llm_dependency": "none"`).

