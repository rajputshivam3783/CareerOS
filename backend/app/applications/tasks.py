"""V22.3 — Application Tasks / follow-ups service layer.

Ownership always flows through ``app.applications.service.get_application``
first, same pattern as notes.py — see that module's docstring.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications import service
from app.applications.events import EVENT_TASK_COMPLETED, EVENT_TASK_CREATED, record_event
from app.models.domain import ApplicationTask

MAX_TITLE_LENGTH = 220


class TaskNotFoundError(Exception):
    pass


class InvalidTaskError(ValueError):
    pass


def _validate_title(title: str) -> str:
    title = (title or "").strip()
    if not title:
        raise InvalidTaskError("Task title cannot be empty")
    if len(title) > MAX_TITLE_LENGTH:
        raise InvalidTaskError(f"Task title must be at most {MAX_TITLE_LENGTH} characters")
    return title


def _get_owned(db: Session, user_id: int, application_id: int, task_id: int) -> ApplicationTask:
    service.get_application(db, user_id, application_id)
    record = db.scalar(
        select(ApplicationTask).where(ApplicationTask.id == task_id, ApplicationTask.application_id == application_id)
    )
    if record is None:
        raise TaskNotFoundError(f"Task {task_id} not found")
    return record


def list_tasks(db: Session, user_id: int, application_id: int, *, include_completed: bool = True) -> list[ApplicationTask]:
    service.get_application(db, user_id, application_id)
    stmt = select(ApplicationTask).where(ApplicationTask.application_id == application_id)
    if not include_completed:
        stmt = stmt.where(ApplicationTask.completed.is_(False))
    stmt = stmt.order_by(ApplicationTask.completed.asc(), ApplicationTask.due_at.asc().nulls_last(), ApplicationTask.id.asc())
    return db.scalars(stmt).all()


def create_task(
    db: Session,
    user_id: int,
    application_id: int,
    *,
    title: str,
    description: str | None = None,
    due_at: datetime | None = None,
) -> ApplicationTask:
    service.get_application(db, user_id, application_id)
    title = _validate_title(title)
    now = datetime.utcnow()
    record = ApplicationTask(
        application_id=application_id,
        title=title,
        description=description,
        due_at=due_at,
        completed=False,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.flush()
    record_event(
        db,
        application_id,
        event_type=EVENT_TASK_CREATED,
        title=f"Task created: {title}",
        occurred_at=now,
        metadata={"task_id": record.id},
    )
    db.commit()
    db.refresh(record)
    return record


def update_task(db: Session, user_id: int, application_id: int, task_id: int, **fields) -> ApplicationTask:
    record = _get_owned(db, user_id, application_id, task_id)

    if "title" in fields and fields["title"] is not None:
        fields["title"] = _validate_title(fields["title"])

    was_completed = record.completed
    for key, value in fields.items():
        if value is not None or key in {"description", "due_at"}:
            setattr(record, key, value)

    record.updated_at = datetime.utcnow()

    if record.completed and not was_completed:
        record.completed_at = datetime.utcnow()
        record_event(
            db,
            application_id,
            event_type=EVENT_TASK_COMPLETED,
            title=f"Task completed: {record.title}",
            metadata={"task_id": record.id},
        )
    elif not record.completed and was_completed:
        record.completed_at = None

    db.commit()
    db.refresh(record)
    return record


def set_completed(db: Session, user_id: int, application_id: int, task_id: int, completed: bool) -> ApplicationTask:
    return update_task(db, user_id, application_id, task_id, completed=completed)


def delete_task(db: Session, user_id: int, application_id: int, task_id: int) -> None:
    record = _get_owned(db, user_id, application_id, task_id)
    db.delete(record)
    db.commit()


def is_overdue(task: ApplicationTask, *, today: date | None = None) -> bool:
    if task.completed or task.due_at is None:
        return False
    today = today or date.today()
    due_date = task.due_at.date() if isinstance(task.due_at, datetime) else task.due_at
    return due_date < today
