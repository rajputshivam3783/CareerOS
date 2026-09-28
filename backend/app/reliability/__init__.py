"""V25.5 — Platform Scale, Observability & Reliability.

This package holds infrastructure added specifically for V25.5:
durable dead-letter tracking for background work (``models.py`` /
``dead_letter.py``) and the read-only aggregate observability view
(``app.api.admin_observability``) that assembles it together with the
metrics/AI-usage/job-health signals V16-V25.4 already collect.

Deliberately additive: nothing here changes an existing table, route,
or call site outside of the scheduler's failure path (see
``app.scheduler``), which now also records to ``FailedJobRecord`` in
addition to the in-memory ``job_health`` it already updated.
"""
