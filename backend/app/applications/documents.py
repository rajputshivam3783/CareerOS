"""V22.3 — Application Documents: secure file storage + metadata.

SECURITY MODEL (see the model's own docstring in app/models/domain.py):
  - The on-disk filename is always a server-generated UUID
    (``stored_filename``); the user-supplied ``original_filename`` is
    stored purely for display and is NEVER used to build a filesystem
    path, closing off path traversal (``../../etc/passwd``-style
    filenames) entirely rather than trying to sanitize them.
  - Files live under ``settings.application_document_storage_dir``, a
    directory that is never mounted as static/public by app/main.py —
    the only way to read a file back is through
    ``get_document_path``, which re-checks application ownership
    every time before returning a path.
  - Extension + content-type are validated the same way
    app.core.uploads.read_upload_limited already validates resumes;
    size is capped by ``settings.application_document_max_upload_mb``.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications import service
from app.applications.events import EVENT_DOCUMENT_UPLOADED, record_event
from app.core.config import settings
from app.core.hardening import sanitize_display_filename
from app.core.uploads import read_upload_limited
from app.models.domain import ApplicationDocument

DOCUMENT_CATEGORIES: tuple[str, ...] = (
    "RESUME",
    "COVER_LETTER",
    "PORTFOLIO",
    "CERTIFICATE",
    "ASSESSMENT",
    "OFFER_LETTER",
    "OTHER",
)

_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".png", ".jpg", ".jpeg"}
_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
    "image/png",
    "image/jpeg",
    "application/octet-stream",  # some browsers send this for any binary file
}


class DocumentNotFoundError(Exception):
    pass


class InvalidDocumentError(ValueError):
    pass


def _storage_dir() -> Path:
    path = Path(settings.application_document_storage_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _normalize_category(value: str) -> str:
    candidate = (value or "").strip().upper()
    if candidate not in DOCUMENT_CATEGORIES:
        raise InvalidDocumentError(f"category must be one of {DOCUMENT_CATEGORIES}")
    return candidate


def _get_owned(db: Session, user_id: int, application_id: int, document_id: int) -> ApplicationDocument:
    service.get_application(db, user_id, application_id)
    record = db.scalar(
        select(ApplicationDocument).where(
            ApplicationDocument.id == document_id, ApplicationDocument.application_id == application_id
        )
    )
    if record is None:
        raise DocumentNotFoundError(f"Document {document_id} not found")
    return record


def list_documents(db: Session, user_id: int, application_id: int) -> list[ApplicationDocument]:
    service.get_application(db, user_id, application_id)
    return db.scalars(
        select(ApplicationDocument)
        .where(ApplicationDocument.application_id == application_id)
        .order_by(ApplicationDocument.uploaded_at.desc())
    ).all()


async def upload_document(
    db: Session, user_id: int, application_id: int, *, category: str, file: UploadFile
) -> ApplicationDocument:
    service.get_application(db, user_id, application_id)  # ownership check before touching disk
    normalized_category = _normalize_category(category)

    file_bytes = await read_upload_limited(
        file,
        max_bytes=settings.application_document_max_upload_mb * 1024 * 1024,
        allowed_extensions=_ALLOWED_EXTENSIONS,
        allowed_content_types=_ALLOWED_CONTENT_TYPES,
    )

    # V25.6: the display name is cleaned (no path components / control characters) because it is
    # echoed back in a Content-Disposition header on download.
    original_name = sanitize_display_filename(file.filename)
    # NEVER TRUST FILENAME: only the extension (already validated
    # above against an allowlist) is reused; the stored filename on
    # disk is a fresh UUID regardless of what the client sent.
    ext = Path(original_name).suffix.lower()
    stored_filename = f"{uuid.uuid4().hex}{ext}"

    dest = _storage_dir() / stored_filename
    with open(dest, "wb") as fh:
        fh.write(file_bytes)

    now = datetime.utcnow()
    record = ApplicationDocument(
        application_id=application_id,
        category=normalized_category,
        original_filename=original_name[:255],
        stored_filename=stored_filename,
        file_size=len(file_bytes),
        mime_type=file.content_type,
        uploaded_at=now,
    )
    db.add(record)
    db.flush()
    record_event(
        db,
        application_id,
        event_type=EVENT_DOCUMENT_UPLOADED,
        title=f"{normalized_category.replace('_', ' ').title()} uploaded: {record.original_filename}",
        metadata={"document_id": record.id, "category": normalized_category},
        occurred_at=now,
    )
    db.commit()
    db.refresh(record)
    return record


def get_document_path(db: Session, user_id: int, application_id: int, document_id: int) -> tuple[ApplicationDocument, Path]:
    """Resolves a document to its on-disk path — re-checks ownership
    every call (via _get_owned) so a stale/guessed document_id can
    never be used to reach another user's file."""
    record = _get_owned(db, user_id, application_id, document_id)
    path = _storage_dir() / record.stored_filename
    if not path.is_file():
        raise DocumentNotFoundError(f"Stored file for document {document_id} is missing")
    return record, path


def delete_document(db: Session, user_id: int, application_id: int, document_id: int) -> None:
    record = _get_owned(db, user_id, application_id, document_id)
    path = _storage_dir() / record.stored_filename
    db.delete(record)
    db.commit()
    try:
        if path.is_file():
            os.remove(path)
    except OSError:
        pass  # DB row is already gone — a stray file on disk is not user-visible
