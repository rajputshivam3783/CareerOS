"""REFRESH / PERFORMANCE — cached recommendation snapshots.

"Do not calculate recommendations from every job on every page
request. Support cached recommendation results where appropriate" +
"Recommendations should refresh when meaningful candidate/job data
changes" (resume updated, skills updated, career goal changed, new job
indexed, job closed, application submitted).

Rather than wiring an invasive "on save, call recompute()" hook into
every one of those unrelated endpoints (resume upload, career
preferences, job posting/closing, applications...), this computes a
short ``input_signature`` hash from exactly those signals each time
recommendations are requested. If the signature matches what's cached,
the cached ``RecommendationSnapshot`` is reused (fast path); if it
doesn't, or the snapshot has passed ``expires_at``, or the caller
passes ``force_refresh``, the pipeline recomputes and overwrites the
snapshot. This achieves the same end result (recommendations reflect
current data) without touching any other module's write path.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.domain import (
    Application,
    BehaviorSignalAggregate,
    CareerPreference,
    Job,
    RecommendationFeedback,
    RecommendationPreference,
    RecommendationSnapshot,
    Resume,
    SavedJob,
)

SNAPSHOT_TTL = timedelta(hours=6)


def compute_signature(db: Session, user_id: int) -> str:
    resume = db.get(Resume, user_id)
    career = db.get(CareerPreference, user_id)
    prefs = db.get(RecommendationPreference, user_id)

    saved_count = db.scalar(select(func.count()).select_from(SavedJob).where(SavedJob.user_id == user_id)) or 0
    applied_count = db.scalar(select(func.count()).select_from(Application).where(Application.user_id == user_id)) or 0
    feedback_count = db.scalar(
        select(func.count()).select_from(RecommendationFeedback).where(RecommendationFeedback.user_id == user_id)
    ) or 0
    # Newest update across published jobs — a coarse but cheap single-
    # aggregate proxy for "a job was indexed, edited, or closed since
    # we last computed this candidate's recommendations".
    max_job_updated = db.scalar(select(func.max(Job.updated_at)).where(Job.status == "published"))
    # V21.4 — newest behavior-signal update for this candidate. Covers
    # BEHAVIORAL SIGNALS (impressions/opens/etc.) that don't already
    # bump one of the counters above, so a meaningfully changed
    # learned profile is reflected without waiting for the TTL.
    max_behavior_updated = db.scalar(
        select(func.max(BehaviorSignalAggregate.updated_at)).where(BehaviorSignalAggregate.user_id == user_id)
    )

    parts = {
        "resume_at": resume.uploaded_at.isoformat() if resume else None,
        "career_at": career.updated_at.isoformat() if career else None,
        "prefs_at": prefs.updated_at.isoformat() if prefs else None,
        "saved": saved_count,
        "applied": applied_count,
        "feedback": feedback_count,
        "max_job_updated": max_job_updated.isoformat() if max_job_updated else None,
        "max_behavior_updated": max_behavior_updated.isoformat() if max_behavior_updated else None,
    }
    raw = json.dumps(parts, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_fresh_snapshot(db: Session, user_id: int, expected_signature: str) -> RecommendationSnapshot | None:
    snapshot = db.get(RecommendationSnapshot, user_id)
    if snapshot is None:
        return None
    if snapshot.input_signature != expected_signature:
        return None
    if snapshot.expires_at < datetime.utcnow():
        return None
    return snapshot


def save_snapshot(db: Session, user_id: int, signature: str, results_json: str) -> RecommendationSnapshot:
    snapshot = db.get(RecommendationSnapshot, user_id)
    now = datetime.utcnow()
    if snapshot is None:
        snapshot = RecommendationSnapshot(
            user_id=user_id,
            input_signature=signature,
            results_json=results_json,
            generated_at=now,
            expires_at=now + SNAPSHOT_TTL,
        )
        db.add(snapshot)
    else:
        snapshot.input_signature = signature
        snapshot.results_json = results_json
        snapshot.generated_at = now
        snapshot.expires_at = now + SNAPSHOT_TTL
    db.commit()
    db.refresh(snapshot)
    return snapshot
