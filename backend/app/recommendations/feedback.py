"""FEEDBACK LOOP — Interested / Not Interested / Dismiss / Not
Relevant (the explicit verdict). Save and Apply are NOT stored again
here — they already have a canonical home (``SavedJob``,
``Application``; see SAVED/APPLIED INTEGRATION: "Do not create
duplicate application storage").

This module owns exactly one thing: the candidate's current *opinion*
on one job (``RecommendationFeedback`` — one row per (user, job),
latest state wins), which ``app.recommendations.candidate_features``
reads back as ``excluded_job_ids`` for future ranking.

V21.4 change: the analytics event-log side effect (previously this
module's own ``record_event``/``VALID_EVENT_TYPES``) has moved to
``app.recommendations.events`` — the single EVENT PROCESSING entry
point (validate/dedupe/record/aggregate/decay) shared by every event
source (impression, open, share, filter_usage, feed_view, and this
module's own feedback verdicts). ``record_event``/``VALID_EVENT_TYPES``
remain importable here as thin aliases so no existing caller (V21.3's
own tests, or any other in-repo caller) breaks.

"Do NOT create a black-box ML model yet" — feedback affects ranking
through two well-defined, inspectable paths only: the hard per-job
exclusion list here, and the bounded, decaying, clamped
BehaviorSignalAggregate scores in app.recommendations.events — never
through an opaque learned weight.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import Job, RecommendationEvent, RecommendationFeedback
from app.recommendations import events as events_service

VALID_FEEDBACK_TYPES = {"interested", "not_interested", "dismiss", "not_relevant"}

# Backward-compatible alias — V21.3 callers/tests that imported this
# name still work; the actual valid set now lives in app.recommendations.events.
VALID_EVENT_TYPES = events_service.VALID_EVENT_TYPES


def record_feedback(db: Session, *, user_id: int, job_id: int, feedback_type: str) -> RecommendationFeedback:
    if feedback_type not in VALID_FEEDBACK_TYPES:
        raise ValueError(f"Unsupported feedback_type '{feedback_type}'. Expected one of {sorted(VALID_FEEDBACK_TYPES)}")
    if db.get(Job, job_id) is None:
        raise ValueError(f"Job {job_id} not found")

    existing = db.scalar(
        select(RecommendationFeedback).where(
            RecommendationFeedback.user_id == user_id, RecommendationFeedback.job_id == job_id
        )
    )
    if existing is not None:
        existing.feedback_type = feedback_type
        existing.updated_at = datetime.utcnow()
        row = existing
    else:
        row = RecommendationFeedback(user_id=user_id, job_id=job_id, feedback_type=feedback_type)
        db.add(row)

    # events_service.record_event commits the session itself, which
    # also persists the RecommendationFeedback add/update above in the
    # same transaction — one commit, one atomic write.
    events_service.record_event(db, user_id=user_id, job_id=job_id, event_type=feedback_type)
    db.refresh(row)
    return row


def record_event(
    db: Session,
    *,
    user_id: int,
    job_id: int | None,
    event_type: str,
    filters: dict | None = None,
    experiment_variant: str | None = None,
    commit: bool = True,
) -> RecommendationEvent | None:
    """Backward-compatible thin wrapper — delegates to
    app.recommendations.events.record_event (the single EVENT
    PROCESSING entry point). Kept here so no V21.3 call site needs to
    change its import."""
    return events_service.record_event(
        db,
        user_id=user_id,
        job_id=job_id,
        event_type=event_type,
        filters=filters,
        experiment_variant=experiment_variant,
        commit=commit,
    )


def get_excluded_job_ids(db: Session, user_id: int) -> set[int]:
    rows = db.scalars(
        select(RecommendationFeedback.job_id).where(
            RecommendationFeedback.user_id == user_id,
            RecommendationFeedback.feedback_type.in_(["dismiss", "not_relevant", "not_interested"]),
        )
    ).all()
    return set(rows)
