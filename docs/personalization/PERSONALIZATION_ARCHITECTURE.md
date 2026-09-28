# PERSONALIZATION_ARCHITECTURE.md â€” V21.4

## Summary

V21.4 extends V21.3's recommendation engine in place â€” no new
recommendation database, no second ranking engine, no second job
matching system. Every V21.3 module (`candidate_features.py`,
`job_features.py`, `matching.py`, `scoring.py`, `diversity.py`,
`explanations.py`, `government.py`, `feedback.py`, `preferences.py`,
`retrieval.py`, `cache.py`, `cold_start.py`, `service.py`) is still the
same module doing the same job; each was additively extended, never
replaced.

## Pipeline (per the spec's own diagram)

```
Candidate Retrieval          app.recommendations.retrieval   (V21.3, unchanged)
      |
Base Match Score             app.recommendations.matching.compute (V21.3 components, unchanged)
      |
Personalization Signals      the same compute() call â€” career goal, location,
      |                      work mode, skills, resume, education (all
      |                      explicit *stated* preferences, V21.3)
      |
Behavioral Signals           NEW: app.recommendations.signals + events
      |                      (the "behavior" component in matching.py)
      |
Freshness                    app.recommendations.matching's "recency"
      |                      component (V21.3, unchanged)
      |
Deadline Urgency             NEW: app.recommendations.matching's
      |                      "deadline_urgency" component
      |
Diversity                    app.recommendations.diversity (V21.3,
      |                      extended to cover opportunity_type)
      v
Final Ranking                app.recommendations.service (V21.3
                              orchestrator, extended)
```

"Base Match Score" and "Personalization Signals" are computed together
in one `matching.compute()` call, exactly as V21.3 already did â€” V21.4
does not split them into two passes, since they were never two passes
to begin with; the spec's own listing of components under each stage
maps onto the *same* set of component functions V21.3 already had.

## New modules (all under `app/recommendations/`, all additive)

| Module | Purpose |
|---|---|
| `ranking_config.py` | RANKING CONFIGURATION â€” documented defaults + admin overrides for every weight/decay/dedup constant |
| `events.py` | EVENT PROCESSING â€” validate â†’ dedupe â†’ record â†’ aggregate â†’ decay, the single `RecommendationEvent` insert path |
| `signals.py` | Reads `BehaviorSignalAggregate` into a `BehaviorSignals` snapshot; computes per-job affinity + plain-English reasons |
| `experiments.py` | A/B TESTING FOUNDATION â€” dormant by default, deterministic variant assignment |
| `controls.py` | USER CONTROLS â€” "Clear Recommendation History" |
| `retention.py` | DATA RETENTION â€” purges raw events past a configurable window |

## Extended modules

- `matching.py` â€” two new components: `behavior`, `deadline_urgency`.
- `scoring.py` â€” component weights now read from `ranking_config`
  (admin-overridable) instead of a hardcoded dict; two new components
  folded into the weighted sum via the same redistribution rule V21.3
  already used for missing components.
- `explanations.py` â€” leads with behavioral reasons when present
  ("Recommended because you frequently viewed backend roles...", the
  spec's own example); new `personalized_match`/`personalization_reasons`
  fields on `Explanation`.
- `diversity.py` â€” `DiversityKey` gained `opportunity_type`
  (Government/Private/Internship/Apprenticeship), capped like company/
  location/title already were.
- `cold_start.py` â€” NEW JOB COLD START fix: `popular_verified_jobs`
  now reserves a fraction of its output for the freshest verified jobs
  regardless of engagement, so a brand-new job isn't buried behind
  every job with even one save.
- `feedback.py` â€” its own `RecommendationEvent` insert delegates to
  `events.py` (one insert path, not two); `VALID_EVENT_TYPES` is now an
  alias onto `events.VALID_EVENT_TYPES`.
- `preferences.py` â€” `personalization_enabled` toggle + `reset_to_defaults`.
- `cache.py` â€” signature now also depends on the candidate's newest
  `BehaviorSignalAggregate.updated_at`, so a meaningfully changed
  learned profile invalidates the cache like any other tracked input.
- `service.py` â€” wires `signals.build()` into `matching.compute()`
  (skipped entirely when personalization is off), passes `db` into
  `scoring.score()`, tags responses with the active A/B experiment
  variant (if any).

## Deliberately NOT built

- A second job/recommendation database â€” retrieval still goes entirely
  through the same V21.1/V21.2 Search Service `retrieval.py` already used.
- A second `RecommendationEvent`-equivalent table â€” `RecommendationEvent`
  itself was extended (nullable `job_id`, `filters_json`,
  `experiment_variant`), not duplicated.
- A second candidate-preferences table â€” `RecommendationPreference`
  gained one column (`personalization_enabled`).
- A second per-user assignment table for experiments â€” variant
  assignment is a deterministic pure function, needs no storage (see
  RANKING_EXPERIMENTS.md).
- Deep learning, collaborative filtering, or a learning-to-rank
  training pipeline â€” explicitly out of scope per the spec's own DO
  NOT IMPLEMENT list; see ML READINESS notes in RANKING_ENGINE_V21_4.md.

See RANKING_ENGINE_V21_4.md, BEHAVIOR_SIGNALS.md,
RANKING_EXPLAINABILITY.md, PERSONALIZATION_PRIVACY.md,
RANKING_FAIRNESS.md, and RANKING_EXPERIMENTS.md for the details behind
each piece above.

