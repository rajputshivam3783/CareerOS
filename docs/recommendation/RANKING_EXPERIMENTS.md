# RANKING_EXPERIMENTS.md â€” A/B Testing Foundation

## What exists

A minimal, dormant-by-default abstraction (`app.recommendations.experiments`
+ `RankingExperiment` table): Experiment ID (`experiment_key`),
Variant + Allocation (`variants_json`, e.g. `{"control": 50,
"variant_b": 50}`), and Metrics (via `RecommendationEvent.experiment_variant`,
grouped in `GET /job-recommendations/analytics`'s `experiment_breakdown`).

Admin-only management endpoints:
```
GET  /job-recommendations/admin/experiments
POST /job-recommendations/admin/experiments
PUT  /job-recommendations/admin/experiments/{key}/status
```

## What does NOT exist (deliberately)

**No ranking logic is branched on a variant anywhere in this release.**
`service.py` calls `experiments.get_active_experiment`/`assign_variant`
purely to *tag* the response and its impression/feed_view events with
a variant label â€” every candidate gets the exact same ranking pipeline
regardless of variant. This is intentional: the spec asks for the
*foundation* ("Design interfaces for future... Do NOT implement
complex ML models in V21.4"), not a live experiment changing outcomes.
Wiring a variant into an actual ranking-parameter difference (e.g.
"variant_b uses different component weights") is a one-line future
change once this foundation has been exercised â€” reading
`ranking_config` values per-variant instead of globally â€” but isn't
done here, so there is nothing yet for an experiment to meaningfully
change.

## Why this is safe by default

- **Dormant with zero configuration.** `ranking_experiments` starts
  empty; `get_active_experiment` returns `None`; nothing else in the
  pipeline changes behavior. Creating a `draft` experiment still has
  zero effect â€” only `status="active"` causes any tagging at all.
- **At most one active experiment.** Activating one automatically
  stops any other (`set_experiment_status`), so event tagging is never
  ambiguous about which experiment a variant belongs to.
- **No randomness at request time.** `assign_variant(user_id, experiment)`
  is a pure function: `sha256(f"{experiment_key}:{user_id}")` mapped
  onto the cumulative allocation percentages. The same candidate always
  gets the same variant for the same experiment â€” reproducible,
  auditable, and requiring zero per-user storage (no assignment table,
  no drift risk between a stored assignment and the experiment's
  current definition).
- **Admin-gated.** Every experiment-management endpoint requires
  `admin_guard` â€” a candidate can never create, activate, or discover
  the existence of an experiment through any candidate-facing endpoint
  beyond the neutral fact that *some* variant tag may appear on their
  own events (which carries no information about what the experiment
  tests).

## Metrics

Reuses the exact same event log and rate calculations
(`GET /job-recommendations/analytics`) already computed for the
non-experiment case â€” CTR, save rate, apply rate, dismiss rate â€” now
additionally grouped by `experiment_variant` in the response's
`experiment_breakdown` field. No second metrics pipeline was built.

## Known limitation

Since no ranking difference exists between variants in this release,
`experiment_breakdown` today can only show that event *volume* is
split roughly per the configured allocation â€” it cannot yet show a
meaningful outcome difference between variants, because there isn't
one to show. This will become meaningful once a future phase wires a
variant into an actual ranking-parameter difference, as noted above.

