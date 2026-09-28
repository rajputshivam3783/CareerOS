"""USER CONTROLS — "Clear Recommendation History".

Distinct from ``app.recommendations.preferences.reset_to_defaults``
("Reset Recommendation Preferences" — reverts *stated* settings).
This clears *learned* data instead: the candidate's
``BehaviorSignalAggregate`` rows (what the ranking engine has inferred
from their impressions/opens/saves/etc.) and their raw
``RecommendationEvent`` history. It deliberately leaves
``RecommendationFeedback`` (explicit per-job dismiss/not-relevant
verdicts) untouched — those are the candidate's direct, intentional
statements about specific jobs, not inferred behavior, and clearing
them would silently un-exclude jobs the candidate explicitly asked not
to see again.

After this call, the candidate's next ``GET /job-recommendations`` is
effectively a fresh cold-start computation for the *behavioral*
component (their stated profile/resume/career-goal signals are
untouched and keep working immediately).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.domain import BehaviorSignalAggregate, RecommendationEvent, RecommendationSnapshot


def clear_behavior_history(db: Session, user_id: int) -> dict:
    aggregates_deleted = (
        db.query(BehaviorSignalAggregate).filter(BehaviorSignalAggregate.user_id == user_id).delete()
    )
    events_deleted = db.query(RecommendationEvent).filter(RecommendationEvent.user_id == user_id).delete()
    # Force the next recommendation request to recompute rather than
    # serving a snapshot that was built using the data just cleared.
    db.query(RecommendationSnapshot).filter(RecommendationSnapshot.user_id == user_id).delete()
    db.commit()
    return {"behavior_signals_cleared": aggregates_deleted, "events_cleared": events_deleted}
