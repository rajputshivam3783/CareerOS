"""V23.1 — Notification Infrastructure API.

Adds exactly the endpoints the existing V7/V19.4 notification API
(app/api/notification_engine.py) doesn't already have:

    GET  /notifications              — general list (category/priority/
                                        unread filters), distinct from
                                        /notifications/center's search+
                                        notification_type filters — both
                                        read the same table through
                                        app.notifications.service, no
                                        second data path.
    GET  /notifications/unread-count — a single COUNT query, no rows.
    POST /notifications/{id}/unread  — the missing inverse of the
                                        existing POST .../read.

POST .../read, POST .../read-all, and DELETE .../{id} are NOT
redefined here — they already exist in notification_engine.py at
these exact paths and already do exactly what this spec asks for;
redefining them here would be the duplicate route/duplicate system
this project's every V-series guardrail explicitly forbids. See
docs/V23_1_NOTIFICATION_INFRASTRUCTURE.md for the full endpoint map.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import current_user
from app.db.session import get_db
from app.notifications import service as notification_service

router = APIRouter()


def _notification_out(n) -> dict:
    return {
        "id": n.id,
        "type": n.notification_type,
        "category": n.category,
        "title": n.title,
        "message": n.message,
        "priority": n.priority,
        "read": n.read,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "action_url": n.action_url,
        "metadata": json.loads(n.metadata_json) if n.metadata_json else None,
        "job_id": n.job_id,
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


@router.get("/notifications")
def list_notifications(
    unread_only: bool = Query(default=False),
    category: str | None = Query(default=None, description=f"One of {notification_service.CATEGORIES}"),
    priority: str | None = Query(default=None, description=f"One of {notification_service.PRIORITIES}"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    u=Depends(current_user),
    db: Session = Depends(get_db),
):
    if category is not None and category.upper() not in notification_service.CATEGORIES:
        raise HTTPException(422, f"category must be one of {notification_service.CATEGORIES}")
    if priority is not None and priority.upper() not in notification_service.PRIORITIES:
        raise HTTPException(422, f"priority must be one of {notification_service.PRIORITIES}")

    items, total = notification_service.list_notifications(
        db, u.id,
        unread_only=unread_only,
        category=category.upper() if category else None,
        priority=priority.upper() if priority else None,
        limit=limit, offset=offset,
    )
    return {
        "items": [_notification_out(n) for n in items],
        "total": total,
        "unread_count": notification_service.get_unread_count(db, u.id),
        "has_more": offset + len(items) < total,
    }


@router.get("/notifications/unread-count")
def unread_count(u=Depends(current_user), db: Session = Depends(get_db)):
    return {"unread_count": notification_service.get_unread_count(db, u.id)}


@router.post("/notifications/{notification_id}/unread")
def mark_unread(notification_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        record = notification_service.mark_unread(db, u.id, notification_id)
    except notification_service.NotificationError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _notification_out(record)
