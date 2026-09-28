"""V24.4 — Recruiter Analytics & AI Hiring Intelligence.

``service.py`` is the deterministic source of truth (counts,
conversion rates, time-in-stage, stale candidates, match-score
distribution) — nothing in this package calls an LLM. ``ai.py`` is a
thin, strictly-grounded explanation layer on top of ``service.py``'s
own output: summarize/explain/compare, never decide. ``cache.py``
caches the AI layer's output only. See
docs/V24_4_RECRUITER_ANALYTICS_AI.md.
"""
