"""A/B TESTING FOUNDATION — V21.4.

A minimal, dormant-by-default abstraction: Experiment ID, Variant,
Allocation, Metrics. "Do NOT launch uncontrolled experiments. Do NOT
randomly change ranking for users without configuration."

Design choices that keep this safe-by-default:

- At most one ``RankingExperiment`` with ``status == "active"`` is
  ever honored (``get_active_experiment``); everything else behaves
  exactly like V21.3's baseline ranking. With zero rows in
  ``ranking_experiments`` (the out-of-the-box state), this module is a
  complete no-op.
- Variant assignment (``assign_variant``) is a **deterministic pure
  function** of ``(user_id, experiment_key)`` — a stable hash mapped
  onto the experiment's allocation percentages. The same user always
  gets the same variant for the same experiment, with no per-user
  storage needed and no randomness at request time (spec: "Do NOT
  randomly change ranking for users without configuration" — this
  reads as "don't flip a coin per request"; a fixed, reproducible,
  configured allocation is exactly what deterministic hashing gives).
- Ranking itself is NOT branched on a variant anywhere in this V21.4
  pass — ``app.recommendations.service`` calls
  ``get_active_experiment``/``assign_variant`` only to tag
  ``RecommendationEvent.experiment_variant`` for future metrics
  analysis. There is no variant-conditional ranking logic to review or
  audit yet; that's deliberately left for a future phase once this
  foundation has been exercised, per "Design interfaces for future...
  Do NOT implement complex ML models in V21.4."
- METRICS: an active experiment's effect is measured by grouping
  ``RecommendationEvent`` rows by ``experiment_variant`` in
  ``app.api.recommendations``'s admin analytics endpoint — reusing the
  exact same event log and rates (CTR, save rate, apply rate) already
  computed for the non-experiment case, not a second metrics system.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import RankingExperiment


def get_active_experiment(db: Session) -> RankingExperiment | None:
    return db.scalar(select(RankingExperiment).where(RankingExperiment.status == "active").limit(1))


def assign_variant(user_id: int, experiment: RankingExperiment) -> str:
    try:
        variants: dict[str, float] = json.loads(experiment.variants_json)
    except (ValueError, TypeError):
        return "control"
    if not variants:
        return "control"

    total = sum(variants.values()) or 1.0
    digest = hashlib.sha256(f"{experiment.experiment_key}:{user_id}".encode("utf-8")).hexdigest()
    bucket = (int(digest[:8], 16) % 10000) / 10000.0 * total

    cumulative = 0.0
    for variant_name, allocation in sorted(variants.items()):
        cumulative += allocation
        if bucket < cumulative:
            return variant_name
    return next(iter(sorted(variants)))
