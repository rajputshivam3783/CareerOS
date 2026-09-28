"""V25.6 — self-service account lifecycle: deactivation and personal-data erasure.

Two deliberately separate operations (see app.core.account_lifecycle for the full data
map):

    POST /account/deactivate   reversible; sign-in stops, nothing is deleted
    POST /account/delete       irreversible; personal data erased/anonymised

Both require the caller to be authenticated AND to re-enter their current password (a stolen
access token alone must not be able to destroy an account), are rate limited, and are
recorded as security events. Platform administrator accounts cannot use them - admin
accounts are deprovisioned through the admin tooling so a break-glass path is never removed
by accident.

Not implemented (documented gap, docs/DATA_RETENTION_AND_DELETION.md): a machine-readable
data-export endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.account_lifecycle import AccountLifecycleError, deactivate_account, erase_account
from app.core.rate_limit import enforce_rate_limit
from app.core.security import ADMIN_ROLES, current_user, verify_password
from app.core.security_events import SecurityEvent, record_security_event
from app.db.session import get_db
from app.models.domain import User

router = APIRouter(prefix="/account", tags=["V25.6 Account Lifecycle"])

ERASURE_CONFIRMATION_PHRASE = "DELETE MY ACCOUNT"


class DeactivateIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class EraseIn(DeactivateIn):
    confirm: str = Field(min_length=1, max_length=64, description=f'Must equal "{ERASURE_CONFIRMATION_PHRASE}"')


def _reauthenticate(db: Session, user: User, password: str, request: Request) -> None:
    enforce_rate_limit(request, bucket="account-lifecycle", limit=5, window=300)
    if user.role in ADMIN_ROLES:
        raise HTTPException(403, "Administrator accounts cannot be closed through self-service")
    if not verify_password(password, user.password_hash):
        record_security_event(db, SecurityEvent.ACCOUNT_LIFECYCLE_AUTH_FAILED, entity_type="user", entity_id=str(user.id))
        db.commit()
        raise HTTPException(403, "Password is incorrect")


@router.post("/deactivate")
def deactivate(payload: DeactivateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _reauthenticate(db, user, payload.password, request)
    try:
        deactivate_account(db, user)
    except AccountLifecycleError as exc:
        raise HTTPException(409, str(exc)) from exc
    record_security_event(db, SecurityEvent.ACCOUNT_SELF_DEACTIVATED, entity_type="user", entity_id=str(user.id))
    db.commit()
    return {
        "status": "deactivated",
        "reversible": True,
        "message": "Your account is deactivated and all sessions have ended. Contact support to reactivate it.",
    }


@router.post("/delete")
def delete_account(payload: EraseIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _reauthenticate(db, user, payload.password, request)
    if payload.confirm.strip() != ERASURE_CONFIRMATION_PHRASE:
        raise HTTPException(422, f'Type "{ERASURE_CONFIRMATION_PHRASE}" exactly to confirm')
    user_id = user.id
    try:
        # The event is written first (and committed by erase_account together with the erasure)
        # so the audit trail always shows who was erased and when - by id, never by email.
        record_security_event(db, SecurityEvent.ACCOUNT_ERASED, entity_type="user", entity_id=str(user_id))
        result = erase_account(db, user)
    except AccountLifecycleError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return {
        "status": "erased",
        "reversible": False,
        "records_removed": sum(result.deleted_rows.values()),
        "applicant_records_scrubbed": result.applicant_records_scrubbed,
        "document_files_removed": result.document_files_removed,
    }
