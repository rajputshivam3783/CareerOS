"""EVENT PROCESSING — V21.4's clean abstraction: Record Event ->
Validate Event -> (dedupe) -> Aggregate Signals -> Apply Time Decay ->
Update User Profile Signals. "Refresh Recommendations" is deliberately
NOT triggered synchronously from here — V21.3's existing cache
signature (app.recommendations.cache.compute_signature) already
invalidates automatically once feedback/saved/applied counts change,
which covers the meaningful cases without adding a second,
event-driven invalidation path to keep in sync with the first.

This module is now the single place that writes to
``RecommendationEvent`` (BEHAVIOR SIGNALS: Job Impression / Open /
Save / Apply / Dismiss / Share / Search / Filter Usage /
Recommendation Feedback). ``app.recommendations.feedback`` — V21.3's
existing module for the *explicit* Interested/Not Interested/Dismiss/
Not Relevant verdict (``RecommendationFeedback``) — now calls into
this module for its own event-log side effect, so there is exactly one
INSERT path for ``RecommendationEvent`` rows, never two.

PRIVACY: this module never stores resume text, search query text (that
already lives in V21.2's own ``RecentSearch``, user-owned and
separately deletable), or any other free-form candidate-authored
content. ``filters_json`` on an event is a short, structured
dict of known keys only (e.g. ``{"dimension": "location"}`` or
``{"result_count": 0, "latency_ms": 42}``) — never search text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import BehaviorSignalAggregate, Job, RecommendationEvent
from app.recommendations import ranking_config
from app.recommendations.job_features import build as build_job_features

VALID_EVENT_TYPES = {
    "impression", "open", "save", "apply", "dismiss", "not_relevant",
    "interested", "not_interested", "share", "filter_usage", "feed_view",
}

# Event types that represent an opinion/action on one specific job and
# should feed the behavior-signal aggregates. "filter_usage" and
# "feed_view" are meta-events about the *feed itself*, not about one
# job, so they never touch BehaviorSignalAggregate.
_JOB_LINKED_EVENT_TYPES = VALID_EVENT_TYPES - {"filter_usage", "feed_view"}

# PERFORMANCE: "impression" is by far the highest-volume event (one per
# card shown on every feed load — up to `limit` per request) and, per
# SIGNAL QUALITY, deliberately the *weakest* signal (weight 0.05).
# Updating ~5-8 BehaviorSignalAggregate rows for every impression would
# multiply feed-load DB writes by an order of magnitude for the
# lowest-value signal in the system. Impressions are still recorded in
# RecommendationEvent (for CTR/analytics), just excluded from the
# aggregate-update step; every deliberate, lower-volume, higher-signal
# action (open/save/apply/share/dismiss/not_relevant/interested/
# not_interested) still updates aggregates as normal.
_AGGREGATE_UPDATING_EVENT_TYPES = _JOB_LINKED_EVENT_TYPES - {"impression"}


class EventValidationError(ValueError):
    pass


@dataclass
class SignalKey:
    signal_type: str
    signal_key: str


def _normalize(value: str) -> str:
    """BehaviorSignalAggregate.signal_key is always stored normalized
    (stripped + lowercased) so storage and lookup
    (app.recommendations.signals.BehaviorSignals.score_for, which
    normalizes its query the same way) can never silently mismatch on
    case or whitespace — e.g. a job's organization stored as "Acme
    Corp" must match a later lookup for "acme corp"."""
    return value.strip().lower()


def _derive_signal_keys(job: Job) -> list[SignalKey]:
    """The set of behavioral signal keys one interaction with `job`
    should influence. Kept small and directly explainable — every key
    here can be turned back into a plain-English clause in
    app.recommendations.explanations (e.g. "you frequently viewed
    backend roles")."""
    features = build_job_features(job)
    keys = [
        SignalKey("company", _normalize(job.organization)),
        SignalKey("location", _normalize(job.location)),
        SignalKey("job_type", _normalize(job.job_type)),
    ]
    if job.industry:
        keys.append(SignalKey("industry", _normalize(job.industry)))
    for skill in features.skills:
        keys.append(SignalKey("skill", _normalize(skill)))

    stopwords = {"the", "and", "for", "with", "of", "in", "at", "to", "a", "an", "-", "&"}
    title_words = [w.strip(".,()") for w in (job.title or "").lower().split()]
    role_keywords = [w for w in title_words if len(w) > 3 and w not in stopwords][:3]
    for word in role_keywords:
        keys.append(SignalKey("role_keyword", _normalize(word)))
    return keys


def _decay_factor(elapsed_seconds: float, half_life_days: float) -> float:
    if elapsed_seconds <= 0 or half_life_days <= 0:
        return 1.0
    elapsed_days = elapsed_seconds / 86400.0
    return 0.5 ** (elapsed_days / half_life_days)


def _is_duplicate(db: Session, *, user_id: int, job_id: int | None, event_type: str) -> bool:
    """EVENT PROCESSING: "Avoid duplicate events." Impressions dedupe
    per (user, job) within a rolling window (a list re-render
    shouldn't re-count as a fresh "shown" signal); every other
    job-linked event type dedupes within a short window (double-click/
    double-submit protection) — genuine save/apply state itself is
    already idempotent via SavedJob/Application's own constraints, this
    is purely about not double-counting the *behavioral signal*."""
    if job_id is None:
        return False
    if event_type == "impression":
        window = timedelta(hours=ranking_config.get(db, "impression_dedupe_hours"))
    else:
        window = timedelta(seconds=ranking_config.get(db, "generic_event_dedupe_seconds"))
    cutoff = datetime.utcnow() - window
    existing = db.scalar(
        select(RecommendationEvent.id).where(
            RecommendationEvent.user_id == user_id,
            RecommendationEvent.job_id == job_id,
            RecommendationEvent.event_type == event_type,
            RecommendationEvent.created_at >= cutoff,
        ).limit(1)
    )
    return existing is not None


def _update_aggregates(db: Session, *, user_id: int, job: Job, event_type: str) -> None:
    event_weights = ranking_config.get(db, "event_weights")
    weight = event_weights.get(event_type)
    if weight is None:
        return  # a job-linked event type with no configured weight (shouldn't happen) contributes nothing, never errors

    half_life = ranking_config.get(db, "time_decay_half_life_days")
    clamp_low, clamp_high = ranking_config.get(db, "score_clamp")
    now = datetime.utcnow()

    for sk in _derive_signal_keys(job):
        row = db.get(BehaviorSignalAggregate, (user_id, sk.signal_type, sk.signal_key))
        if row is None:
            score = max(clamp_low, min(clamp_high, weight))
            db.add(
                BehaviorSignalAggregate(
                    user_id=user_id,
                    signal_type=sk.signal_type,
                    signal_key=sk.signal_key,
                    score=score,
                    event_count=1,
                    last_event_at=now,
                )
            )
        else:
            elapsed = (now - row.last_event_at).total_seconds()
            decayed = row.score * _decay_factor(elapsed, half_life)
            new_score = max(clamp_low, min(clamp_high, decayed + weight))
            row.score = new_score
            row.event_count += 1
            row.last_event_at = now


def record_event(
    db: Session,
    *,
    user_id: int,
    event_type: str,
    job_id: int | None = None,
    filters: dict | None = None,
    experiment_variant: str | None = None,
    commit: bool = True,
) -> RecommendationEvent | None:
    """VALIDATE -> dedupe -> RECORD -> AGGREGATE -> DECAY, in one call.
    Returns the created row, or None if the event was recognized as a
    duplicate and intentionally skipped (not an error).

    ``commit=False`` lets a caller logging several events in one
    request (e.g. one impression per card in a feed response) batch
    them into a single transaction/commit instead of one round-trip
    per event — the caller is then responsible for calling
    ``db.commit()`` itself afterward."""
    if event_type not in VALID_EVENT_TYPES:
        raise EventValidationError(f"Unsupported event_type '{event_type}'. Expected one of {sorted(VALID_EVENT_TYPES)}")

    job: Job | None = None
    if job_id is not None:
        job = db.get(Job, job_id)
        if job is None:
            raise EventValidationError(f"Job {job_id} not found")
    elif event_type in _JOB_LINKED_EVENT_TYPES:
        raise EventValidationError(f"event_type '{event_type}' requires a job_id")

    if _is_duplicate(db, user_id=user_id, job_id=job_id, event_type=event_type):
        return None

    row = RecommendationEvent(
        user_id=user_id,
        job_id=job_id,
        event_type=event_type,
        filters_json=json.dumps(filters) if filters is not None else None,
        experiment_variant=experiment_variant,
    )
    db.add(row)

    if job is not None and event_type in _AGGREGATE_UPDATING_EVENT_TYPES:
        _update_aggregates(db, user_id=user_id, job=job, event_type=event_type)

    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row
