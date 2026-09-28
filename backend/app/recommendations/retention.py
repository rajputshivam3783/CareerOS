"""DATA RETENTION — V21.4.

"Do not store behavioral events forever without purpose. Create
configurable retention/aggregation strategy. Aggregate older events
where appropriate. Allow deletion where required by existing privacy
architecture."

The design already minimizes what needs retention: ranking itself
never reads raw ``RecommendationEvent`` history — it reads the
already-aggregated, already-time-decayed ``BehaviorSignalAggregate``
rows (see app.recommendations.events/signals). Raw events exist only
for admin analytics (CTR, save rate, etc. — see
app.api.recommendations's admin endpoint), so their retention window
only needs to satisfy *that* use case, not ranking.

``purge_old_events`` deletes raw ``RecommendationEvent`` rows older
than ``ranking_config.get(db, "raw_event_retention_days")`` (default
180 days). It deliberately does NOT touch ``BehaviorSignalAggregate``
— those are already a small, bounded-per-signal-key summary, not raw
history, so there's nothing to "age out" there; a signal a candidate
hasn't reinforced in a long time already decays toward zero on its own
(TIME DECAY) without needing to be deleted.

Deletion-on-request (privacy architecture: GDPR-style erasure, account
deletion, etc.) is handled by the existing ``ON DELETE CASCADE`` on
every ``user_id`` foreign key in this package's tables (see the V21.4
migration) — deleting a ``User`` row already cascades to
``RecommendationEvent``, ``BehaviorSignalAggregate``,
``RecommendationFeedback``, and ``RecommendationSnapshot``
automatically; no separate erasure code path was needed or added here.

Not wired into a scheduler in this pass — see TEST_REPORT_V21_4.md.
``app/scheduler.py`` already runs periodic jobs for other V-phases and
would be the natural place to call ``purge_old_events`` on a daily
cadence; adding that call is a one-line follow-up once this function
itself has been exercised against a real database.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.domain import RecommendationEvent
from app.recommendations import ranking_config


def purge_old_events(db: Session) -> int:
    retention_days = ranking_config.get(db, "raw_event_retention_days")
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    deleted = db.query(RecommendationEvent).filter(RecommendationEvent.created_at < cutoff).delete()
    db.commit()
    return deleted
