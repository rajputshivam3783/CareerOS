"""V22.3 — Application Notes service layer.

Every function here first resolves the parent application through
``app.applications.service.get_application`` (which already scopes to
``user_id`` and raises ``ApplicationNotFoundError`` on any mismatch),
so a note can never be created, read, edited, or deleted against an
application that isn't the caller's own — the same ownership guarantee
``service.py`` already gives the Application itself.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications import service
from app.applications.events import EVENT_NOTE_ADDED, record_event
from app.models.domain import ApplicationNote

MAX_NOTE_LENGTH = 10_000


class NoteNotFoundError(Exception):
    pass


class InvalidNoteError(ValueError):
    pass


def _validate_content(content: str) -> str:
    content = (content or "").strip()
    if not content:
        raise InvalidNoteError("Note content cannot be empty")
    if len(content) > MAX_NOTE_LENGTH:
        raise InvalidNoteError(f"Note content must be at most {MAX_NOTE_LENGTH} characters")
    return content


def _get_owned_note(db: Session, user_id: int, application_id: int, note_id: int) -> ApplicationNote:
    service.get_application(db, user_id, application_id)  # 404s + ownership check
    note = db.scalar(
        select(ApplicationNote).where(ApplicationNote.id == note_id, ApplicationNote.application_id == application_id)
    )
    if note is None:
        raise NoteNotFoundError(f"Note {note_id} not found")
    return note


def list_notes(db: Session, user_id: int, application_id: int) -> list[ApplicationNote]:
    service.get_application(db, user_id, application_id)
    return db.scalars(
        select(ApplicationNote).where(ApplicationNote.application_id == application_id).order_by(ApplicationNote.created_at.desc())
    ).all()


def create_note(db: Session, user_id: int, application_id: int, content: str) -> ApplicationNote:
    service.get_application(db, user_id, application_id)
    content = _validate_content(content)
    now = datetime.utcnow()
    note = ApplicationNote(application_id=application_id, content=content, created_at=now, updated_at=now)
    db.add(note)
    db.flush()
    record_event(
        db,
        application_id,
        event_type=EVENT_NOTE_ADDED,
        title="Note added",
        description=content[:200],
        occurred_at=now,
    )
    db.commit()
    db.refresh(note)
    return note


def update_note(db: Session, user_id: int, application_id: int, note_id: int, content: str) -> ApplicationNote:
    note = _get_owned_note(db, user_id, application_id, note_id)
    note.content = _validate_content(content)
    note.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(note)
    return note


def delete_note(db: Session, user_id: int, application_id: int, note_id: int) -> None:
    note = _get_owned_note(db, user_id, application_id, note_id)
    db.delete(note)
    db.commit()
