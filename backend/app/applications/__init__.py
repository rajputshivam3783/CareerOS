"""V22.1 — Application Tracking Infrastructure.

A candidate-owned application tracker: the complete lifecycle of every
job application, whether it came from a CareerOS listing or was added
manually for a job found elsewhere. Extends the existing V7
``Application`` model in place (see its own docstring in
app/models/domain.py) — this is not a second application system.

    app.applications.status   — canonical status vocabulary + legacy
                                 value normalization (STATUS LIFECYCLE)
    app.applications.service  — the one place that creates, updates,
                                 deletes, and transitions an
                                 Application; every operation is
                                 scoped to a user_id derived from
                                 authentication, never trusted from
                                 the caller (SECURITY)

``app/api/applications.py`` is the only HTTP-facing layer — it should
never touch ``Application``/``ApplicationStatusHistory`` directly,
only call into ``service``.

V22.3 (Application Timeline, Notes & Documents) adds child-resource
modules that each turn one application into a fuller candidate
workspace, all layered on top of the above rather than replacing it:

    app.applications.notes       — private per-application notes
    app.applications.interviews  — per-application interview rounds
    app.applications.tasks       — per-application follow-ups/tasks
    app.applications.documents   — secure per-application file storage
    app.applications.events      — shared ApplicationEvent writer used
                                    by the four modules above
    app.applications.timeline    — merges ApplicationStatusHistory +
                                    ApplicationEvent into one feed

Every one of these resolves ownership through
``service.get_application`` first — never a second, parallel
ownership check — so an application's own access control lives in
exactly one place. Their HTTP layer is
``app/api/application_workspace.py``.
"""
