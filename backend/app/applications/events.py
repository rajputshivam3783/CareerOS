"""V22.3 — shared helper for writing ``ApplicationEvent`` rows.

Every child-resource module (notes/interviews/tasks/documents) calls
``record_event`` at the point it creates or meaningfully transitions
its own row, so the unified timeline (app.applications.timeline) never
has to guess activity from other tables. Status changes are the one
exception — those already have their own immutable
``ApplicationStatusHistory`` table and are read from there directly
(see timeline.py) rather than duplicated here.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.domain import ApplicationEvent

# Canonical event_type vocabulary — kept here as the single source of
# truth so the timeline module and any future producer agree on exact
# spelling.
EVENT_NOTE_ADDED = "NOTE_ADDED"
EVENT_INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
EVENT_INTERVIEW_COMPLETED = "INTERVIEW_COMPLETED"
EVENT_TASK_CREATED = "TASK_CREATED"
EVENT_TASK_COMPLETED = "TASK_COMPLETED"
EVENT_DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"


def record_event(
    db: Session,
    application_id: int,
    *,
    event_type: str,
    title: str,
    description: str | None = None,
    metadata: dict | None = None,
    occurred_at: datetime | None = None,
) -> ApplicationEvent:
    event = ApplicationEvent(
        application_id=application_id,
        event_type=event_type,
        title=title,
        description=description,
        metadata_json=json.dumps(metadata) if metadata else None,
        occurred_at=occurred_at or datetime.utcnow(),
    )
    db.add(event)
    return event
