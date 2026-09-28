"""V25.3 — the CareerOS intelligence/analytics layer.

One analytics layer, five views onto it:

    CareerOS tables
        ↓  corpus.py        (one filtered job/application corpus loader)
        ↓  skills.py        (one skill aggregation engine)
        ↓  roles.py         (one role→corpus resolver)
        ↓
    candidate.py · market.py · organization.py · platform_intel.py
        ↓
    ai.py (explains; never calculates)
        ↓
    candidate / recruiter / organization / admin API views

Two rules shape every module here:

1. **Deterministic calculation is the source of truth.** Every number
   any endpoint returns is a COUNT, a ratio of two counts, or a date
   arithmetic over rows that exist. The AI layer receives those
   numbers already computed and may only phrase them.

2. **Platform-derived, and labelled as such.** Everything measured
   here is CareerOS activity, not "the job market". Every response
   that reports market-shaped figures carries an explicit
   ``scope`` label saying so. CareerOS holds no external
   labour-market dataset, so no endpoint claims one.

Reuse, not reimplementation. This package deliberately calls into:

- ``app.skill_intelligence.normalization`` — skill canonicalization
  (V20.5). No second alias table.
- ``app.skill_intelligence.gap`` — per-*job* candidate skill gap
  (V20.5). V25.3 adds the per-*role* aggregate it did not have.
- ``app.recruiter_analytics.service`` — hiring funnel, time-in-stage,
  stale candidates (V24.4). Organization intelligence is that service
  called with the organization's member ids, not a second funnel.
- ``app.recruiter_analytics.ai`` / ``.cache`` — the grounded
  generate/cache/guard pipeline (V24.4), extended with new prompts.
- ``app.services.platform_analytics`` — platform counts (V25.2).
- ``app.core.platform_settings`` — the sample-size thresholds, so
  they are operator-tunable and defined in exactly one place.
"""
