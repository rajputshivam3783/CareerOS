"""V22.3 — Application Timeline, Notes & Documents API.

Builds on top of V22.1's Application Tracking Infrastructure without
touching app/api/applications.py or app/applications/service.py:
every endpoint here is a *child resource* of an existing Application
(notes/interviews/tasks/documents/timeline), and every one of them
resolves ownership through app.applications.service.get_application
before doing anything else — see each service module's own docstring.

SECURITY: same convention as app/api/applications.py — the acting
user is always `current_user` (the verified JWT), never a
caller-supplied id; application_id/note_id/etc. are always re-checked
against ownership inside the service layer, not just trusted from the
URL.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.applications import documents, interviews, notes, service, tasks, timeline
from app.applications.interviews import INTERVIEW_RESULTS, INTERVIEW_TYPES
from app.applications.documents import DOCUMENT_CATEGORIES
from app.applications.tasks import is_overdue
from app.core.security import current_user
from app.db.session import get_db

router = APIRouter()


def _not_found(exc: Exception):
    raise HTTPException(404, str(exc)) from exc


def _unprocessable(exc: Exception):
    raise HTTPException(422, str(exc)) from exc


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


class NoteIn(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)


def _note_out(n) -> dict:
    return {
        "id": n.id,
        "application_id": n.application_id,
        "content": n.content,
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


@router.get("/applications/{application_id}/notes")
def list_notes(application_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        rows = notes.list_notes(db, u.id, application_id)
    except service.ApplicationNotFoundError as exc:
        _not_found(exc)
    return [_note_out(n) for n in rows]


@router.post("/applications/{application_id}/notes", status_code=201)
def create_note(application_id: int, payload: NoteIn, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        record = notes.create_note(db, u.id, application_id, payload.content)
    except service.ApplicationNotFoundError as exc:
        _not_found(exc)
    except notes.InvalidNoteError as exc:
        _unprocessable(exc)
    return _note_out(record)


@router.patch("/applications/{application_id}/notes/{note_id}")
def update_note(application_id: int, note_id: int, payload: NoteIn, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        record = notes.update_note(db, u.id, application_id, note_id, payload.content)
    except (service.ApplicationNotFoundError, notes.NoteNotFoundError) as exc:
        _not_found(exc)
    except notes.InvalidNoteError as exc:
        _unprocessable(exc)
    return _note_out(record)


@router.delete("/applications/{application_id}/notes/{note_id}", status_code=204)
def delete_note(application_id: int, note_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        notes.delete_note(db, u.id, application_id, note_id)
    except (service.ApplicationNotFoundError, notes.NoteNotFoundError) as exc:
        _not_found(exc)


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------


class InterviewIn(BaseModel):
    interview_type: str = Field(description=f"One of {INTERVIEW_TYPES}")
    round_name: str | None = Field(default=None, max_length=120)
    scheduled_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    interviewer_name: str | None = Field(default=None, max_length=220)
    interviewer_email: str | None = Field(default=None, max_length=255)
    meeting_url: str | None = Field(default=None, max_length=1000)
    location: str | None = Field(default=None, max_length=220)
    notes: str | None = Field(default=None, max_length=5000)
    result: str | None = Field(default=None, description=f"One of {INTERVIEW_RESULTS}")

    @field_validator("meeting_url")
    @classmethod
    def _validate_url(cls, v):
        if v and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("meeting_url must start with http:// or https://")
        return v


class InterviewUpdateIn(BaseModel):
    interview_type: str | None = None
    round_name: str | None = Field(default=None, max_length=120)
    scheduled_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    interviewer_name: str | None = Field(default=None, max_length=220)
    interviewer_email: str | None = Field(default=None, max_length=255)
    meeting_url: str | None = Field(default=None, max_length=1000)
    location: str | None = Field(default=None, max_length=220)
    notes: str | None = Field(default=None, max_length=5000)
    result: str | None = None


def _interview_out(i) -> dict:
    return {
        "id": i.id,
        "application_id": i.application_id,
        "interview_type": i.interview_type,
        "round_name": i.round_name,
        "scheduled_at": i.scheduled_at.isoformat() if i.scheduled_at else None,
        "duration_minutes": i.duration_minutes,
        "interviewer_name": i.interviewer_name,
        "interviewer_email": i.interviewer_email,
        "meeting_url": i.meeting_url,
        "location": i.location,
        "notes": i.notes,
        "result": i.result,
        "created_at": i.created_at.isoformat(),
        "updated_at": i.updated_at.isoformat() if i.updated_at else None,
    }


@router.get("/applications/{application_id}/interviews")
def list_interviews(application_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        rows = interviews.list_interviews(db, u.id, application_id)
    except service.ApplicationNotFoundError as exc:
        _not_found(exc)
    return [_interview_out(i) for i in rows]


@router.post("/applications/{application_id}/interviews", status_code=201)
def create_interview(application_id: int, payload: InterviewIn, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        record = interviews.create_interview(db, u.id, application_id, **payload.model_dump())
    except service.ApplicationNotFoundError as exc:
        _not_found(exc)
    except interviews.InvalidInterviewError as exc:
        _unprocessable(exc)
    return _interview_out(record)


@router.patch("/applications/{application_id}/interviews/{interview_id}")
def update_interview(application_id: int, interview_id: int, payload: InterviewUpdateIn, u=Depends(current_user), db: Session = Depends(get_db)):
    fields = payload.model_dump(exclude_unset=True)
    try:
        record = interviews.update_interview(db, u.id, application_id, interview_id, **fields)
    except (service.ApplicationNotFoundError, interviews.InterviewNotFoundError) as exc:
        _not_found(exc)
    except interviews.InvalidInterviewError as exc:
        _unprocessable(exc)
    return _interview_out(record)


@router.delete("/applications/{application_id}/interviews/{interview_id}", status_code=204)
def delete_interview(application_id: int, interview_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        interviews.delete_interview(db, u.id, application_id, interview_id)
    except (service.ApplicationNotFoundError, interviews.InterviewNotFoundError) as exc:
        _not_found(exc)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=220)
    description: str | None = Field(default=None, max_length=5000)
    due_at: datetime | None = None


class TaskUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=220)
    description: str | None = Field(default=None, max_length=5000)
    due_at: datetime | None = None
    completed: bool | None = None


def _task_out(t) -> dict:
    return {
        "id": t.id,
        "application_id": t.application_id,
        "title": t.title,
        "description": t.description,
        "due_at": t.due_at.isoformat() if t.due_at else None,
        "completed": t.completed,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "overdue": is_overdue(t),
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@router.get("/applications/{application_id}/tasks")
def list_tasks(application_id: int, include_completed: bool = Query(default=True), u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        rows = tasks.list_tasks(db, u.id, application_id, include_completed=include_completed)
    except service.ApplicationNotFoundError as exc:
        _not_found(exc)
    return [_task_out(t) for t in rows]


@router.post("/applications/{application_id}/tasks", status_code=201)
def create_task(application_id: int, payload: TaskIn, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        record = tasks.create_task(db, u.id, application_id, title=payload.title, description=payload.description, due_at=payload.due_at)
    except service.ApplicationNotFoundError as exc:
        _not_found(exc)
    except tasks.InvalidTaskError as exc:
        _unprocessable(exc)
    return _task_out(record)


@router.patch("/applications/{application_id}/tasks/{task_id}")
def update_task(application_id: int, task_id: int, payload: TaskUpdateIn, u=Depends(current_user), db: Session = Depends(get_db)):
    fields = payload.model_dump(exclude_unset=True)
    try:
        record = tasks.update_task(db, u.id, application_id, task_id, **fields)
    except (service.ApplicationNotFoundError, tasks.TaskNotFoundError) as exc:
        _not_found(exc)
    except tasks.InvalidTaskError as exc:
        _unprocessable(exc)
    return _task_out(record)


@router.delete("/applications/{application_id}/tasks/{task_id}", status_code=204)
def delete_task(application_id: int, task_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        tasks.delete_task(db, u.id, application_id, task_id)
    except (service.ApplicationNotFoundError, tasks.TaskNotFoundError) as exc:
        _not_found(exc)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def _document_out(d) -> dict:
    return {
        "id": d.id,
        "application_id": d.application_id,
        "category": d.category,
        "original_filename": d.original_filename,
        "file_size": d.file_size,
        "mime_type": d.mime_type,
        "uploaded_at": d.uploaded_at.isoformat(),
    }


@router.get("/applications/{application_id}/documents")
def list_documents(application_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        rows = documents.list_documents(db, u.id, application_id)
    except service.ApplicationNotFoundError as exc:
        _not_found(exc)
    return [_document_out(d) for d in rows]


@router.post("/applications/{application_id}/documents", status_code=201)
async def upload_document(
    application_id: int,
    category: str = Form(..., description=f"One of {DOCUMENT_CATEGORIES}"),
    file: UploadFile = File(...),
    u=Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        record = await documents.upload_document(db, u.id, application_id, category=category, file=file)
    except service.ApplicationNotFoundError as exc:
        _not_found(exc)
    except documents.InvalidDocumentError as exc:
        _unprocessable(exc)
    return _document_out(record)


@router.get("/applications/{application_id}/documents/{document_id}/download")
def download_document(application_id: int, document_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    """Secure download — never exposes the raw storage path to the
    frontend; ownership is re-checked on every call
    (documents.get_document_path -> _get_owned)."""
    try:
        record, path = documents.get_document_path(db, u.id, application_id, document_id)
    except (service.ApplicationNotFoundError, documents.DocumentNotFoundError) as exc:
        _not_found(exc)
    return FileResponse(path, filename=record.original_filename, media_type=record.mime_type or "application/octet-stream")


@router.delete("/applications/{application_id}/documents/{document_id}", status_code=204)
def delete_document(application_id: int, document_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        documents.delete_document(db, u.id, application_id, document_id)
    except (service.ApplicationNotFoundError, documents.DocumentNotFoundError) as exc:
        _not_found(exc)


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


@router.get("/applications/{application_id}/timeline")
def get_timeline(
    application_id: int,
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    u=Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        return timeline.get_timeline(db, u.id, application_id, order=order)
    except service.ApplicationNotFoundError as exc:
        _not_found(exc)
