"""V22.3 — Unified application timeline.

Merges two sources at read time rather than duplicating either into a
third table:

  1. ``ApplicationStatusHistory`` (V22.1) — every status change,
     including the synthetic "created" row written when the
     application itself was created.
  2. ``ApplicationEvent`` (V22.3) — notes/interviews/tasks/documents
     activity, written by their own modules (see events.py).

Ordered newest-first by default, per spec.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications import service
from app.applications.status import STATUS_VALUES
from app.models.domain import ApplicationEvent, ApplicationStatusHistory

_STATUS_LABELS = {s: s.replace("_", " ").title() for s in STATUS_VALUES}


def _status_history_to_entry(h: ApplicationStatusHistory) -> dict:
    if h.old_status is None:
        title = f"Application created ({_STATUS_LABELS.get(h.new_status, h.new_status)})"
        event_type = "APPLICATION_CREATED"
    else:
        title = f"Status changed: {_STATUS_LABELS.get(h.old_status, h.old_status)} → {_STATUS_LABELS.get(h.new_status, h.new_status)}"
        event_type = "STATUS_CHANGED"
    metadata = json.loads(h.metadata_json) if h.metadata_json else None
    return {
        "event_type": event_type,
        "title": title,
        "description": (metadata or {}).get("note") if metadata else None,
        "metadata": metadata,
        "occurred_at": h.changed_at.isoformat(),
        "source": "status_history",
        "source_id": h.id,
    }


def _event_to_entry(e: ApplicationEvent) -> dict:
    return {
        "event_type": e.event_type,
        "title": e.title,
        "description": e.description,
        "metadata": json.loads(e.metadata_json) if e.metadata_json else None,
        "occurred_at": e.occurred_at.isoformat(),
        "source": "event",
        "source_id": e.id,
    }


def get_timeline(db: Session, user_id: int, application_id: int, *, order: str = "desc") -> list[dict]:
    service.get_application(db, user_id, application_id)  # ownership check

    history_rows = db.scalars(
        select(ApplicationStatusHistory)
        .where(ApplicationStatusHistory.application_id == application_id)
        .order_by(ApplicationStatusHistory.changed_at.asc(), ApplicationStatusHistory.id.asc())
    ).all()
    event_rows = db.scalars(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application_id)
        .order_by(ApplicationEvent.occurred_at.asc(), ApplicationEvent.id.asc())
    ).all()

    entries = [_status_history_to_entry(h) for h in history_rows] + [_event_to_entry(e) for e in event_rows]
    entries.sort(key=lambda e: e["occurred_at"], reverse=(order == "desc"))
    return entries
