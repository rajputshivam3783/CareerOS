"""V19.2 — Change detection.

Diffs an incoming, normalized JobRecord against whatever ``find_matching_job``
finds already on file and classifies what happened, writing a
``RecruitmentUpdate`` row (the existing V14/V16 lifecycle-event table —
unchanged schema, see app.models.domain.RecruitmentUpdate) so the
existing government dashboard/timeline UI picks these up automatically
without any change on that side.

This intentionally reuses RecruitmentUpdate rather than adding a
parallel "change log" table — one government job, one lifecycle
timeline, exactly like every hand-entered admin update already works.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ingestion.models.job_record import JobRecord
from app.ingestion.services.deduplicate import find_matching_job
from app.models.domain import Job, RecruitmentUpdate

CANCELLED_TITLE_MARKERS = ("cancel", "withdrawn", "postponed indefinitely")


@dataclass
class ChangeResult:
    change_type: str  # new_recruitment | updated_recruitment | cancelled_recruitment |
                       # deadline_extended | result_published | admit_card_published |
                       # answer_key_published | no_change
    job: Job | None = None
    detail: str | None = None


def detect_change(db: Session, record: JobRecord) -> ChangeResult:
    """Read-only classification — does not write Job or
    RecruitmentUpdate itself; call ``apply_change`` (or let
    app.ingestion.orchestrator do it) once you've decided to act on
    the result. Kept split so callers/tests can inspect the
    classification without side effects."""
    existing = find_matching_job(db, record)

    if existing is None:
        return ChangeResult(change_type="new_recruitment")

    title_lower = (record.title or "").lower()
    if any(marker in title_lower for marker in CANCELLED_TITLE_MARKERS):
        return ChangeResult(change_type="cancelled_recruitment", job=existing)

    if record.result_url and record.result_url != existing.result_url:
        return ChangeResult(change_type="result_published", job=existing, detail=record.result_url)

    if record.admit_card_url and record.admit_card_url != existing.admit_card_url:
        return ChangeResult(change_type="admit_card_published", job=existing, detail=record.admit_card_url)

    if record.answer_key_url and record.answer_key_url != existing.answer_key_url:
        return ChangeResult(change_type="answer_key_published", job=existing, detail=record.answer_key_url)

    if record.deadline and existing.deadline and record.deadline > existing.deadline:
        return ChangeResult(change_type="deadline_extended", job=existing, detail=str(record.deadline))

    # Anything else structurally different (vacancies, fee, exam date)
    # still counts as an update worth flagging, just a lower-signal one.
    if (
        (record.vacancies is not None and record.vacancies != existing.vacancies)
        or (record.exam_date is not None and record.exam_date != existing.exam_date)
    ):
        return ChangeResult(change_type="updated_recruitment", job=existing)

    return ChangeResult(change_type="no_change", job=existing)


def apply_change(db: Session, result: ChangeResult, source_url: str | None = None) -> RecruitmentUpdate | None:
    """Write a RecruitmentUpdate for a non-trivial change. No-ops for
    'new_recruitment' (the Job row being created *is* the event — see
    app.ingestion.services.publisher) and 'no_change'."""
    if result.change_type in {"new_recruitment", "no_change"} or result.job is None:
        return None

    update = RecruitmentUpdate(
        job_id=result.job.id,
        update_type=_UPDATE_TYPE_MAP.get(result.change_type, "notice"),
        title=_TITLE_MAP.get(result.change_type, "Recruitment updated").format(org=result.job.organization),
        source_url=result.detail or source_url,
        official=True,
        status="published",
    )
    db.add(update)
    db.commit()
    db.refresh(update)
    return update


_UPDATE_TYPE_MAP = {
    "cancelled_recruitment": "cancelled",
    "result_published": "result",
    "admit_card_published": "admit_card",
    "answer_key_published": "answer_key",
    "deadline_extended": "notice",
    "updated_recruitment": "notice",
}

_TITLE_MAP = {
    "cancelled_recruitment": "Recruitment cancelled — {org}",
    "result_published": "Result published — {org}",
    "admit_card_published": "Admit card published — {org}",
    "answer_key_published": "Answer key published — {org}",
    "deadline_extended": "Application deadline extended — {org}",
    "updated_recruitment": "Recruitment details updated — {org}",
}
