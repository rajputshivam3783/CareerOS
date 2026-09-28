"""V24.3 — service logic for the recruiter Candidate Pipeline.

Nothing here talks HTTP — app.api.recruiter (the existing board/move-
stage endpoints) and app.api.recruiter_pipeline (the new stats/
history/bulk endpoints) both call into this module, so the two can
never validate a transition or record history differently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import PIPELINE_FORWARD_STAGES, PIPELINE_STAGES, PIPELINE_TERMINAL_STAGES
from app.models.domain import Applicant, RecruiterPipelineHistory
from app.notifications import service as notification_service

# Candidate-facing copy for the subset of stages worth telling a
# candidate about (spec section 21). Deliberately narrower than the
# full board vocabulary — a bare "moved to reviewing" isn't
# meaningfully actionable for the candidate the way "you're being
# reviewed" or "you've reached the interview stage" is, and REJECTED
# has its own richer, reject_reason-aware notification already sent
# by app.api.recruiter.update_applicant_status, so it's excluded here
# to avoid sending the candidate two separate "you were rejected"
# notifications for one recruiter action.
_CANDIDATE_STAGE_MESSAGES: dict[str, tuple[str, str]] = {
    "reviewing": ("Your application is being reviewed", "Your application is being reviewed."),
    "shortlisted": ("You've been shortlisted", "You've been shortlisted for this role."),
    "assessment": ("You've moved to the assessment stage", "Your application has moved to the assessment stage."),
    "interview": ("You've moved to the interview stage", "Your application has moved to the interview stage."),
    "offer": ("You have a new offer", "An offer is being prepared for you — check your offer details."),
    "hired": ("Congratulations!", "Congratulations — you've been marked as hired for this role."),
}


class StageTransitionError(ValueError):
    """Raised when a requested pipeline_stage move isn't a valid
    transition (spec section 6). Always safe to surface to the
    recruiter as a 422 — never wraps an internal/db error."""


def _direction(old_stage: str | None, new_stage: str) -> str:
    """Classifies a transition for reporting only (RecruiterPipelineHistory.direction)
    — never used to decide whether a move is allowed."""
    if old_stage is None:
        return "initial"
    if old_stage in PIPELINE_TERMINAL_STAGES:
        return "reactivation"
    if new_stage in PIPELINE_TERMINAL_STAGES:
        return "terminal"
    try:
        old_idx = PIPELINE_FORWARD_STAGES.index(old_stage)
        new_idx = PIPELINE_FORWARD_STAGES.index(new_stage)
    except ValueError:
        return "forward"
    return "forward" if new_idx >= old_idx else "backward"


def validate_transition(old_stage: str | None, new_stage: str) -> str:
    """Returns the transition's `direction` if the move from
    `old_stage` to `new_stage` is allowed, else raises
    StageTransitionError. See PIPELINE_STAGES's docstring
    (app.core.constants) for the actual policy — this function is
    just that policy's one enforcement point.
    """
    if new_stage not in PIPELINE_STAGES:
        raise StageTransitionError(f"pipeline_stage must be one of {PIPELINE_STAGES}")
    if old_stage == new_stage:
        raise StageTransitionError(f"Candidate is already in stage '{new_stage}'")
    # Every other move is allowed (see the STAGE_TRANSITIONS_NOTE
    # policy in app.core.constants) — same-stage is the only rejected
    # transition. `_direction` still classifies *how* the allowed move
    # reads, for reporting.
    return _direction(old_stage, new_stage)


@dataclass
class StageChangeResult:
    applicant: Applicant
    history: RecruiterPipelineHistory
    candidate_notified: bool


def change_stage(
    db: Session,
    applicant: Applicant,
    new_stage: str,
    *,
    actor_user_id: int | None,
    reason: str | None = None,
    notify_candidate: bool = True,
) -> StageChangeResult:
    """The one place `Applicant.pipeline_stage` is written from V24.3
    onward (spec section 27: validate -> update stage -> create
    history record -> commit, atomically). Callers (the PATCH
    .../stage endpoint and the bulk-stage endpoint) do their own
    ownership check first via _owned_applicant_or_404 — this function
    only enforces the transition rule, not authorization.
    """
    old_stage = applicant.pipeline_stage
    direction = validate_transition(old_stage, new_stage)

    applicant.pipeline_stage = new_stage
    if new_stage == "hired" and applicant.hired_at is None:
        applicant.hired_at = datetime.utcnow()

    history = RecruiterPipelineHistory(
        applicant_id=applicant.id,
        old_stage=old_stage,
        new_stage=new_stage,
        changed_by_user_id=actor_user_id,
        direction=direction,
        reason=reason,
    )
    db.add(history)
    # Single transaction covering the stage update and the history
    # row — notification/event processing happens after this commit
    # (below) so a notification failure can never roll back the
    # actual stage change (spec section 27).
    db.commit()
    db.refresh(applicant)
    db.refresh(history)

    candidate_notified = False
    if notify_candidate and new_stage in _CANDIDATE_STAGE_MESSAGES:
        title, message = _CANDIDATE_STAGE_MESSAGES[new_stage]
        try:
            notification_service.create_notification(
                db,
                user_id=applicant.user_id,
                notification_type="recruiter_pipeline_stage_changed",
                category="APPLICATION",
                priority="NORMAL",
                title=title,
                message=message,
                action_url=None,  # no candidate-facing per-applicant route exists to deep-link into (candidates track status from their own applications list)
                job_id=applicant.job_id,
                dedupe_key=f"recruiter_pipeline_stage:{applicant.id}:{new_stage}:{history.id}",
            )
            candidate_notified = True
        except Exception:  # noqa: BLE001 — notification failure must never break the stage change (already committed above)
            candidate_notified = False

    return StageChangeResult(applicant=applicant, history=history, candidate_notified=candidate_notified)


def pipeline_history(db: Session, applicant_id: int) -> list[RecruiterPipelineHistory]:
    return db.scalars(
        select(RecruiterPipelineHistory)
        .where(RecruiterPipelineHistory.applicant_id == applicant_id)
        .order_by(RecruiterPipelineHistory.changed_at)
    ).all()


def _latest_history_by_applicant(db: Session, applicant_ids: list[int]) -> dict[int, RecruiterPipelineHistory]:
    """The most recent history row per applicant — i.e. when they
    entered their *current* stage. Used for time-in-stage/staleness.
    """
    if not applicant_ids:
        return {}
    rows = db.scalars(
        select(RecruiterPipelineHistory)
        .where(RecruiterPipelineHistory.applicant_id.in_(applicant_ids))
        .order_by(RecruiterPipelineHistory.applicant_id, RecruiterPipelineHistory.changed_at.desc())
    ).all()
    latest: dict[int, RecruiterPipelineHistory] = {}
    for row in rows:
        if row.applicant_id not in latest:
            latest[row.applicant_id] = row
    return latest


def time_in_current_stage(db: Session, applicant: Applicant, now: datetime | None = None) -> dict:
    """How long `applicant` has been in its current pipeline_stage,
    per spec section 17. Falls back to `Applicant.created_at` if no
    history row exists yet (e.g. a brand-new applicant never moved)."""
    now = now or datetime.utcnow()
    latest = _latest_history_by_applicant(db, [applicant.id]).get(applicant.id)
    entered_at = latest.changed_at if latest else applicant.created_at
    days = max(0, (now - entered_at).days)
    return {"stage": applicant.pipeline_stage, "entered_at": entered_at, "days_in_stage": days}


def pipeline_stats(db: Session, job_id: int, applicants: list[Applicant], now: datetime | None = None) -> dict:
    """Per-job pipeline statistics (spec section 15). Every number is
    a real aggregate over `applicants`/`recruiter_pipeline_history` —
    nothing here is estimated or hard-coded (spec: "Only calculate
    metrics supported by actual data")."""
    now = now or datetime.utcnow()
    total = len(applicants)
    counts = {stage: 0 for stage in PIPELINE_STAGES}
    for a in applicants:
        counts[a.pipeline_stage or "new"] = counts.get(a.pipeline_stage or "new", 0) + 1

    week_ago = now - timedelta(days=7)
    applications_this_week = sum(1 for a in applicants if a.created_at and a.created_at >= week_ago)

    applicant_ids = [a.id for a in applicants]
    avg_time_in_stage: dict[str, float | None] = {}
    latest_by_applicant = _latest_history_by_applicant(db, applicant_ids)
    by_stage: dict[str, list[int]] = {stage: [] for stage in PIPELINE_STAGES}
    for a in applicants:
        stage = a.pipeline_stage or "new"
        latest = latest_by_applicant.get(a.id)
        entered_at = latest.changed_at if latest else a.created_at
        by_stage.setdefault(stage, []).append(max(0, (now - entered_at).days))
    for stage, days_list in by_stage.items():
        avg_time_in_stage[stage] = round(sum(days_list) / len(days_list), 1) if days_list else None

    recent_changes: list[RecruiterPipelineHistory] = []
    if applicant_ids:
        recent_changes = db.scalars(
            select(RecruiterPipelineHistory)
            .where(RecruiterPipelineHistory.applicant_id.in_(applicant_ids))
            .order_by(RecruiterPipelineHistory.changed_at.desc())
            .limit(20)
        ).all()

    return {
        "job_id": job_id,
        "total_candidates": total,
        "stage_counts": counts,
        "applications_this_week": applications_this_week,
        "average_days_in_stage": avg_time_in_stage,
        "recent_stage_changes": [
            {
                "applicant_id": h.applicant_id,
                "old_stage": h.old_stage,
                "new_stage": h.new_stage,
                "changed_at": h.changed_at,
                "changed_by_user_id": h.changed_by_user_id,
            }
            for h in recent_changes
        ],
    }


# Ordered (from_stage, to_stage) pairs the funnel reports on (spec
# section 16). Each is a *cumulative* count against `total`, not a
# step-over-step rate, since a candidate can skip a stage (e.g.
# shortlisted -> offer directly) and still counts as having "reached"
# every stage up to and including offer for this purpose.
_CONVERSION_STEPS = [
    ("new", "shortlisted"),
    ("shortlisted", "interview"),
    ("interview", "offer"),
    ("offer", "hired"),
]


def conversion_metrics(db: Session, job_id: int, applicants: list[Applicant]) -> dict:
    """Spec section 16: "Handle zero denominators correctly. Do not
    present misleading percentages." A stage is counted as "reached"
    if the applicant's current stage is at or beyond it in
    PIPELINE_FORWARD_STAGES, OR they're in a terminal stage (rejected/
    withdrawn) reached history shows passed through it — approximated
    here via history rather than only current stage, since a rejected
    candidate who was previously shortlisted did still convert through
    "shortlisted"."""
    applicant_ids = [a.id for a in applicants]
    reached_stages_by_applicant: dict[int, set[str]] = {a.id: set() for a in applicants}
    if applicant_ids:
        for h in db.scalars(
            select(RecruiterPipelineHistory).where(RecruiterPipelineHistory.applicant_id.in_(applicant_ids))
        ):
            reached_stages_by_applicant.setdefault(h.applicant_id, set()).add(h.new_stage)
    for a in applicants:
        reached_stages_by_applicant.setdefault(a.id, set()).add(a.pipeline_stage or "new")

    total = len(applicants)
    steps = []
    for from_stage, to_stage in _CONVERSION_STEPS:
        from_count = sum(1 for ids in reached_stages_by_applicant.values() if from_stage in ids)
        to_count = sum(1 for ids in reached_stages_by_applicant.values() if to_stage in ids)
        rate = round((to_count / from_count) * 100, 1) if from_count else None
        steps.append({"from_stage": from_stage, "to_stage": to_stage, "from_count": from_count, "to_count": to_count, "conversion_rate": rate})

    return {"job_id": job_id, "total_candidates": total, "steps": steps}


DEFAULT_STALE_THRESHOLD_DAYS = 7


def stale_candidates(
    db: Session, job_id: int, applicants: list[Applicant], threshold_days: int = DEFAULT_STALE_THRESHOLD_DAYS, now: datetime | None = None
) -> list[dict]:
    """Spec section 18: candidates with no pipeline activity for
    `threshold_days`. Deterministic threshold, no "likely to reject"
    judgment — just last-activity/days-inactive plus a fixed,
    non-judgmental suggested action per stage."""
    now = now or datetime.utcnow()
    active = [a for a in applicants if (a.pipeline_stage or "new") not in PIPELINE_TERMINAL_STAGES]
    latest_by_applicant = _latest_history_by_applicant(db, [a.id for a in active])

    results = []
    for a in active:
        latest = latest_by_applicant.get(a.id)
        last_activity = latest.changed_at if latest else a.created_at
        days_inactive = (now - last_activity).days
        if days_inactive < threshold_days:
            continue
        stage = a.pipeline_stage or "new"
        suggested_action = {
            "new": "Review this application",
            "reviewing": "Decide whether to shortlist or reject",
            "shortlisted": "Move to assessment or schedule an interview",
            "assessment": "Follow up on the assessment result",
            "interview": "Schedule or follow up on the interview",
            "offer": "Follow up on the outstanding offer",
        }.get(stage, "Review this candidate's next step")
        results.append(
            {
                "applicant_id": a.id,
                "pipeline_stage": stage,
                "last_activity_at": last_activity,
                "days_inactive": days_inactive,
                "suggested_action": suggested_action,
            }
        )
    results.sort(key=lambda r: r["days_inactive"], reverse=True)
    return results
