"""V23.3 — Smart Job Alerts & Personalized Job Notifications.

    schemas.py    request/response shapes for the API layer.
    service.py    JobAlert CRUD, ownership enforcement, ORM<->API mapping.
    matching.py   the matching engine — structural candidate filtering
                  (via app.search's index) + relevance scoring (via
                  app.recommendations when personalized, app.search.ranking
                  otherwise). Creates no new ranking engine — see its
                  module docstring.
    execution.py  the alert execution pipeline: due-alert selection,
                  per-alert run (match -> threshold -> dedupe -> notify/
                  email), digest aggregation. Reuses app.notifications
                  and app.email exactly as every other event in this
                  codebase does.
"""
