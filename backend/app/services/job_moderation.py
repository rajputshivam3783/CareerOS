"""V25.2 — platform job moderation.

This is deliberately NOT a second publication system (spec section 8).
CareerOS has had exactly one job review workflow since V9: a Job's
``status`` column moves through ``review`` -> ``published`` /
``rejected``, and ``app.api.admin``'s publish/reject routes are how it
moves. This module takes over the *body* of those transitions —
including the two original routes, which now delegate here — and adds
the two states the governance layer needs:

    review ──approve──▶ published ──suspend──▶ suspended ──restore──▶ published
      │                                            ▲
      └──reject──▶ rejected ──restore──▶ review    │
                                                   │
                    (an organization suspension also lands jobs here,
                     tagged so reactivation restores exactly that set —
                     see app.core.platform_lifecycle)

``suspended`` is a new *value* of the existing column, not a new
column: adding a status value without a migration is the same pattern
V14/V16 already used for role and update_type values, and it means
every query that filters ``status == "published"`` — search indexing,
the public job list, candidate-facing endpoints — excludes suspended
jobs automatically, with no code change and no risk of one of them
being missed.

WHAT IS AND ISN'T SHOWN TO THE RECRUITER
----------------------------------------
``moderation_reason`` is a structured code from ``MODERATION_REASONS``
below and IS recruiter-visible: a recruiter whose posting was rejected
is entitled to know why. ``moderation_note`` is the administrator's
free-text internal note and is returned ONLY on platform-admin
endpoints (spec section 9). Nothing in this module writes the note
anywhere a recruiter- or candidate-facing serializer reads from.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.domain import Job

log = logging.getLogger("careeros.job_moderation")

# Structured moderation reasons (spec section 9). A free-text-only
# reason would make "how often do we reject for prohibited content?"
# unanswerable, which is the question the analytics screen exists to
# answer.
MODERATION_REASONS: tuple[str, ...] = (
    "policy_violation",
    "incomplete_information",
    "misleading_information",
    "duplicate_listing",
    "prohibited_content",
    "suspicious_activity",
    "spam",
    "expired",
    "other",
)

# Every status a Job may hold. The first four predate this version and
# are unchanged; "suspended" is added by V25.2.
JOB_STATUSES: tuple[str, ...] = ("draft", "review", "published", "rejected", "closed", "suspended")

# Statuses whose listings are visible to candidates. Used only for
# reporting here — the actual visibility rules live in the existing
# query filters, which this module does not touch.
PUBLIC_STATUSES: frozenset[str] = frozenset({"published"})


class ModerationError(HTTPException):
    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(status_code, detail)


def validate_reason(reason: str) -> str:
    if reason not in MODERATION_REASONS:
        raise HTTPException(422, f"reason must be one of: {', '.join(MODERATION_REASONS)}")
    return reason


def _stamp(job: Job, *, reason: str | None, note: str | None, actor_user_id: int | None) -> None:
    job.moderation_reason = reason
    job.moderation_note = (note or None) if note is None else note[:4000]
    job.moderated_at = datetime.utcnow()
    job.moderated_by_user_id = actor_user_id


def approve_job(db: Session, job: Job, *, actor_user_id: int | None, note: str | None = None) -> Job:
    """Approve/publish a job. Identical in effect to the V9
    ``POST /admin/jobs/{id}/publish`` route, which now calls this —
    including the V24.1 rule that ``published_at`` is set once, the
    first time a listing ever goes live, and never rewritten by a
    later close/reopen or restore.
    """
    job.status = "published"
    job.verified = True
    if job.published_at is None:
        job.published_at = datetime.utcnow()
    job.pre_moderation_status = None
    _stamp(job, reason=None, note=note, actor_user_id=actor_user_id)
    sync_search(db, job.id)
    return job


def reject_job(
    db: Session, job: Job, *, reason: str, actor_user_id: int | None, note: str | None = None
) -> Job:
    """Reject a job with a structured reason.

    The reason is required here even though the legacy route made it
    optional — see ``app.api.admin.reject``, which supplies "other"
    when a caller predating V25.2 sends no body. That keeps the old
    contract working without leaving new rejections unexplained.
    """
    validate_reason(reason)
    job.pre_moderation_status = job.status
    job.status = "rejected"
    job.verified = False
    _stamp(job, reason=reason, note=note, actor_user_id=actor_user_id)
    sync_search(db, job.id)
    return job


def suspend_job(
    db: Session, job: Job, *, reason: str, actor_user_id: int | None, note: str | None = None
) -> Job:
    """Unpublish a live listing pending investigation.

    Records the status it held beforehand so ``restore_job`` is an
    exact undo. Suspending an already-suspended job is rejected rather
    than silently overwriting ``pre_moderation_status`` with
    "suspended", which would make the job unrestorable.
    """
    validate_reason(reason)
    if job.status == "suspended":
        raise ModerationError("Job is already suspended")
    job.pre_moderation_status = job.status
    job.status = "suspended"
    _stamp(job, reason=reason, note=note, actor_user_id=actor_user_id)
    sync_search(db, job.id)
    return job


def restore_job(db: Session, job: Job, *, actor_user_id: int | None, note: str | None = None) -> Job:
    """Reverse a suspension or rejection.

    Restores the exact status the job held before the moderation
    action. A job with no recorded prior status (e.g. rejected before
    V25.2 existed) returns to ``review`` rather than straight to
    ``published`` — the safe direction: it re-enters the queue for a
    human decision instead of being auto-published by a restore.
    """
    if job.status not in ("suspended", "rejected"):
        raise ModerationError("Only a suspended or rejected job can be restored")
    job.status = job.pre_moderation_status or "review"
    job.pre_moderation_status = None
    job.moderation_reason = None
    job.moderated_at = datetime.utcnow()
    job.moderated_by_user_id = actor_user_id
    if note:
        job.moderation_note = note[:4000]
    sync_search(db, job.id)
    return job


def sync_search(db: Session, job_id: int) -> None:
    """Refresh this job's V21.1 search document after a status change.

    Guarded: the search index is a derived cache (see
    app/search/indexer.py), so a failure to update it must not roll
    back or block the moderation decision itself.
    """
    try:
        from app.search.hooks import sync_job

        sync_job(db, job_id)
    except Exception:  # pragma: no cover - defensive
        log.warning("Search sync failed for job %s after moderation", job_id, exc_info=True)


def recruiter_visible_moderation(job: Job) -> dict:
    """The moderation fields a recruiter may see for their own job.

    Note the absence of ``moderation_note`` and
    ``moderated_by_user_id``: the internal note and the identity of
    the moderating administrator are never exposed outside the
    platform-admin surface.
    """
    return {
        "status": job.status,
        "moderation_reason": job.moderation_reason,
        "moderated_at": job.moderated_at,
    }
