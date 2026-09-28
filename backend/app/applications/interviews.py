"""V22.3 — Application Interview tracking service layer.

Ownership always flows through ``app.applications.service.get_application``
first, same pattern as notes.py — see that module's docstring.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications import service
from app.applications.events import EVENT_INTERVIEW_COMPLETED, EVENT_INTERVIEW_SCHEDULED, record_event
from app.notifications import events as notification_events
from app.models.domain import ApplicationInterview

INTERVIEW_TYPES: tuple[str, ...] = (
    "PHONE",
    "VIDEO",
    "TECHNICAL",
    "HR",
    "MANAGERIAL",
    "ASSESSMENT",
    "ONSITE",
    "OTHER",
)

INTERVIEW_RESULTS: tuple[str, ...] = (
    "SCHEDULED",
    "COMPLETED",
    "PASSED",
    "FAILED",
    "CANCELLED",
    "RESCHEDULED",
)

# Results that mean the round has actually happened/resolved, distinct
# from still-pending (SCHEDULED/RESCHEDULED) or never-happened
# (CANCELLED) — used to decide whether an INTERVIEW_COMPLETED timeline
# event is recorded on an update.
_RESOLVED_RESULTS = {"COMPLETED", "PASSED", "FAILED"}


class InterviewNotFoundError(Exception):
    pass


class InvalidInterviewError(ValueError):
    pass


def _normalize_type(value: str) -> str:
    candidate = (value or "").strip().upper()
    if candidate not in INTERVIEW_TYPES:
        raise InvalidInterviewError(f"interview_type must be one of {INTERVIEW_TYPES}")
    return candidate


def _normalize_result(value: str | None) -> str:
    if value is None:
        return "SCHEDULED"
    candidate = value.strip().upper()
    if candidate not in INTERVIEW_RESULTS:
        raise InvalidInterviewError(f"result must be one of {INTERVIEW_RESULTS}")
    return candidate


def _get_owned(db: Session, user_id: int, application_id: int, interview_id: int) -> ApplicationInterview:
    service.get_application(db, user_id, application_id)
    record = db.scalar(
        select(ApplicationInterview).where(
            ApplicationInterview.id == interview_id, ApplicationInterview.application_id == application_id
        )
    )
    if record is None:
        raise InterviewNotFoundError(f"Interview {interview_id} not found")
    return record


def list_interviews(db: Session, user_id: int, application_id: int) -> list[ApplicationInterview]:
    service.get_application(db, user_id, application_id)
    return db.scalars(
        select(ApplicationInterview)
        .where(ApplicationInterview.application_id == application_id)
        .order_by(ApplicationInterview.scheduled_at.asc().nulls_last(), ApplicationInterview.id.asc())
    ).all()


def create_interview(
    db: Session,
    user_id: int,
    application_id: int,
    *,
    interview_type: str,
    round_name: str | None = None,
    scheduled_at: datetime | None = None,
    duration_minutes: int | None = None,
    interviewer_name: str | None = None,
    interviewer_email: str | None = None,
    meeting_url: str | None = None,
    location: str | None = None,
    notes: str | None = None,
    result: str | None = None,
) -> ApplicationInterview:
    application = service.get_application(db, user_id, application_id)
    itype = _normalize_type(interview_type)
    result_value = _normalize_result(result)
    now = datetime.utcnow()

    record = ApplicationInterview(
        application_id=application_id,
        interview_type=itype,
        round_name=round_name,
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        interviewer_name=interviewer_name,
        interviewer_email=interviewer_email,
        meeting_url=meeting_url,
        location=location,
        notes=notes,
        result=result_value,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.flush()

    title = f"{round_name or itype.title()} interview scheduled"
    record_event(
        db,
        application_id,
        event_type=EVENT_INTERVIEW_SCHEDULED,
        title=title,
        description=scheduled_at.isoformat() if scheduled_at else None,
        metadata={"interview_id": record.id, "interview_type": itype},
        occurred_at=now,
    )
    db.commit()
    db.refresh(record)
    # V23.1 — fires after commit; failure here can never fail the
    # interview creation itself (already committed).
    notification_events.interview_scheduled(db, user_id=user_id, application=application, interview=record)
    return record


def update_interview(db: Session, user_id: int, application_id: int, interview_id: int, **fields) -> ApplicationInterview:
    record = _get_owned(db, user_id, application_id, interview_id)
    old_result = record.result

    if "interview_type" in fields and fields["interview_type"] is not None:
        fields["interview_type"] = _normalize_type(fields["interview_type"])
    if "result" in fields and fields["result"] is not None:
        fields["result"] = _normalize_result(fields["result"])

    for key, value in fields.items():
        if value is not None or key in {"round_name", "interviewer_name", "interviewer_email", "meeting_url", "location", "notes", "scheduled_at", "duration_minutes"}:
            setattr(record, key, value)

    record.updated_at = datetime.utcnow()

    new_result = record.result
    if new_result in _RESOLVED_RESULTS and old_result not in _RESOLVED_RESULTS:
        record_event(
            db,
            application_id,
            event_type=EVENT_INTERVIEW_COMPLETED,
            title=f"{record.round_name or record.interview_type.title()} interview {new_result.lower()}",
            metadata={"interview_id": record.id, "result": new_result},
        )

    db.commit()
    db.refresh(record)
    # V23.1 — fires after commit; failure here can never fail the
    # interview update itself (already committed).
    application = service.get_application(db, user_id, application_id)
    notification_events.interview_updated(db, user_id=user_id, application=application, interview=record)
    return record


def delete_interview(db: Session, user_id: int, application_id: int, interview_id: int) -> None:
    record = _get_owned(db, user_id, application_id, interview_id)
    db.delete(record)
    db.commit()
