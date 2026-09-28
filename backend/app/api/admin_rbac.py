"""V17.3 — Enterprise RBAC, session management, and admin user controls.

A separate router (not appended to app.api.admin) so this pass's diff
stays fully additive and isolated — nothing here edits an existing
route in admin.py, auth.py, or any of the "do not touch" areas
(Government Hub, Recruiter ATS, AI, Search, Notifications, Analytics).
Mounted under the same "/admin" prefix as the existing admin router
(see app.api.routes), so from the outside this simply adds more
"/admin/..." endpoints.

Auth: every route here uses app.core.rbac.require_permission_dual,
the same dual-mode pattern (shared X-Admin-Key OR a logged-in admin's
JWT) app.api.admin.guard already established — reused, not
reimplemented. Where JWT auth is used, the specific dot-namespaced
permission is enforced (DB-override-aware), not just "is this any
kind of admin."

Several capabilities the brief asked for reuse existing, already-built
mechanisms rather than duplicating them:
- "Activate/Deactivate account" = the existing
  POST /admin/users/{id}/lock (permanent=true) / unlock.
- "Approve/Reject recruiter" = the existing
  POST /admin/recruiters/{id}/approve / reject.
- Single-session revoke = the existing POST /admin/sessions/{id}/revoke.
Those are intentionally not duplicated here — see RBAC_ARCHITECTURE.md.
"""

import csv
import io
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.rbac import (
    PERMISSION_CATALOG,
    ROLE_HIERARCHY,
    effective_permissions_for_role,
    require_permission_dual,
)
from app.core.sessions import count_active_sessions, list_all_active_sessions, revoke_all_sessions
from app.core.user_agent import parse_user_agent
from app.db.session import get_db
from app.models.domain import AuditLog, RolePermissionOverride, User

router = APIRouter()


# --------------------------- Roles & permissions -----------------------------

@router.get("/rbac/roles", dependencies=[Depends(require_permission_dual("roles.manage"))])
def list_roles(db: Session = Depends(get_db)):
    """Every known role, its position in the display hierarchy, and its
    *effective* permissions (static defaults merged with any DB
    overrides) — the source of truth an admin sees is the same one
    ``require_dot_permission`` actually checks against at request time.
    """
    return [
        {
            "role": role,
            "hierarchy_position": i,
            "permissions": sorted(effective_permissions_for_role(role, db)),
        }
        for i, role in enumerate(ROLE_HIERARCHY)
    ]


@router.get("/rbac/permissions", dependencies=[Depends(require_permission_dual("permissions.read"))])
def list_permissions():
    """The full permission catalog (every dot-namespaced permission
    string this codebase knows about, with a human-readable
    description) — see app.core.rbac.PERMISSION_CATALOG."""
    return [{"permission": key, "description": desc} for key, desc in sorted(PERMISSION_CATALOG.items())]


class PermissionGrant(BaseModel):
    permission: str


@router.post("/rbac/roles/{role}/grant", dependencies=[Depends(require_permission_dual("roles.manage"))])
def grant_role_permission(role: str, payload: PermissionGrant, db: Session = Depends(get_db)):
    if payload.permission not in PERMISSION_CATALOG:
        raise HTTPException(400, f"Unknown permission: {payload.permission}")
    if role not in ROLE_HIERARCHY:
        raise HTTPException(400, f"Unknown role: {role}")

    existing = db.scalar(
        select(RolePermissionOverride).where(
            RolePermissionOverride.role == role, RolePermissionOverride.permission == payload.permission
        )
    )
    if existing:
        existing.granted = True
    else:
        db.add(RolePermissionOverride(role=role, permission=payload.permission, granted=True))
    log_audit(db, action="rbac_grant", entity_type="role", entity_id=role, detail=payload.permission)
    db.commit()
    return {"role": role, "permissions": sorted(effective_permissions_for_role(role, db))}


@router.post("/rbac/roles/{role}/revoke", dependencies=[Depends(require_permission_dual("roles.manage"))])
def revoke_role_permission(role: str, payload: PermissionGrant, db: Session = Depends(get_db)):
    if role not in ROLE_HIERARCHY:
        raise HTTPException(400, f"Unknown role: {role}")

    existing = db.scalar(
        select(RolePermissionOverride).where(
            RolePermissionOverride.role == role, RolePermissionOverride.permission == payload.permission
        )
    )
    if existing:
        existing.granted = False
    else:
        db.add(RolePermissionOverride(role=role, permission=payload.permission, granted=False))
    log_audit(db, action="rbac_revoke", entity_type="role", entity_id=role, detail=payload.permission)
    db.commit()
    return {"role": role, "permissions": sorted(effective_permissions_for_role(role, db))}


# --------------------------------- Sessions -----------------------------------

@router.get("/rbac/sessions", dependencies=[Depends(require_permission_dual("sessions.read"))])
def list_all_sessions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """System-wide active-session listing (as opposed to the existing
    GET /admin/users/{id}/sessions, which is scoped to one user)."""
    sessions = list_all_active_sessions(db, limit=limit, offset=offset, user_id=user_id)
    total = count_active_sessions(db, user_id=user_id)
    users_by_id = {u.id: u for u in db.scalars(select(User).where(User.id.in_({s.user_id for s in sessions}))).all()}

    results = []
    for s in sessions:
        ua = parse_user_agent(s.user_agent)
        user = users_by_id.get(s.user_id)
        results.append(
            {
                "id": s.id,
                "user_id": s.user_id,
                "user_email": user.email if user else None,
                "device_id": s.device_id,
                "device_label": s.device_label,
                "ip_address": s.ip_address,
                "browser": ua["browser"],
                "os": ua["os"],
                "device": ua["device"],
                "country": None,
                "created_at": s.created_at,
                "last_seen_at": s.last_seen_at,
            }
        )
    return {"total": total, "limit": limit, "offset": offset, "results": results}


@router.post("/rbac/users/{user_id}/force-logout", dependencies=[Depends(require_permission_dual("sessions.revoke"))])
def force_logout(user_id: int, db: Session = Depends(get_db)):
    """Revoke every active session for a user — reuses the same
    app.core.sessions.revoke_all_sessions function the existing
    self-service POST /auth/logout-all already calls."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    count = revoke_all_sessions(db, user)
    log_audit(db, action="admin_force_logout", entity_type="user", entity_id=str(user_id), detail=f"sessions_revoked={count}")
    db.commit()
    return {"user_id": user_id, "sessions_revoked": count}


# ------------------------------ User management --------------------------------

class SuspendIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/rbac/users/{user_id}/suspend", dependencies=[Depends(require_permission_dual("users.suspend"))])
def suspend_user(user_id: int, payload: SuspendIn, db: Session = Depends(get_db)):
    """Administrative hold, distinct from the V17.2 security lockout —
    see the User.suspended_at/suspension_reason docstring in
    app/models/domain.py for why this reuses `active=False` to actually
    block login rather than adding a second auth gate."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    user.active = False
    user.suspended_at = datetime.utcnow()
    user.suspension_reason = payload.reason
    log_audit(db, action="admin_suspend_user", entity_type="user", entity_id=str(user_id), detail=payload.reason)
    db.commit()
    return {"user_id": user_id, "suspended": True, "reason": payload.reason}


@router.post("/rbac/users/{user_id}/unsuspend", dependencies=[Depends(require_permission_dual("users.suspend"))])
def unsuspend_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    was_suspended = user.suspended_at is not None
    user.active = True
    user.suspended_at = None
    user.suspension_reason = None
    log_audit(db, action="admin_unsuspend_user", entity_type="user", entity_id=str(user_id))
    db.commit()
    return {"user_id": user_id, "suspended": False, "was_suspended": was_suspended}


@router.post("/rbac/users/{user_id}/reset-password", dependencies=[Depends(require_permission_dual("users.reset_password"))])
def admin_reset_password(user_id: int, db: Session = Depends(get_db)):
    """Sends the user the same password-reset OTP email the existing
    self-service POST /auth/forgot-password sends — reuses that flow's
    OTP-issuance helper rather than inventing a second one, and never
    sets or reveals a password directly (a temp-password-by-email
    pattern is weaker: it puts a live credential in an inbox instead of
    a short-lived, single-use code)."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    from app.api.auth import _issue  # reusing the existing OTP-issuance helper — see module docstring

    _issue(db, user, purpose="reset_password")
    log_audit(db, action="admin_trigger_password_reset", entity_type="user", entity_id=str(user_id))
    db.commit()
    return {"user_id": user_id, "reset_email_sent": True}


# -------------------------------- Audit log export ------------------------------

@router.get("/rbac/audit-logs/export", dependencies=[Depends(require_permission_dual("admin.audit.read"))])
def export_audit_logs(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    search: str | None = Query(default=None, description="Substring match on action/entity_type/actor_label"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    """Search/filter/date-range/export for the audit log — the existing
    GET /admin/audit-logs (exact action/entity_type match + pagination)
    is unchanged; this is an additional, export-oriented endpoint
    rather than a rewrite of it, so nothing that already calls that one
    is affected.
    """
    query = select(AuditLog).order_by(AuditLog.id.desc())
    if search:
        like = f"%{search}%"
        query = query.where(
            AuditLog.action.ilike(like) | AuditLog.entity_type.ilike(like) | AuditLog.actor_label.ilike(like)
        )
    if date_from:
        query = query.where(AuditLog.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.where(AuditLog.created_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))

    rows = db.scalars(query.limit(limit)).all()
    log_audit(db, action="admin_export_audit_logs", entity_type="audit_log", detail=f"format={format} count={len(rows)}")
    db.commit()

    records = [
        {
            "id": r.id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "detail": r.detail,
            "actor_type": r.actor_type,
            "actor_id": r.actor_id,
            "actor_label": r.actor_label,
            "request_id": r.request_id,
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]

    if format == "json":
        return records

    buffer = io.StringIO()
    fieldnames = [
        "id", "action", "entity_type", "entity_id", "detail",
        "actor_type", "actor_id", "actor_label", "request_id", "ip_address", "created_at",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(records)
    return Response(content=buffer.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": "attachment; filename=audit_logs.csv"
    })
