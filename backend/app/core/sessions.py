"""V17.1 Auth Core — session + refresh-token lifecycle.

Kept separate from ``app.core.security`` (which only ever dealt with
password hashing and short-lived access tokens) because this is a
genuinely different concern: long-lived, revocable, per-device state
that lives in the database rather than being self-contained inside a
JWT.

Design:
  * A ``UserSession`` row is created once per login (one per device,
    identified by a client-supplied or server-generated ``device_id``).
  * Each session owns a chain of ``RefreshToken`` rows. Only the most
    recent, unrevoked token in the chain is valid — using the refresh
    endpoint rotates it (issues a new one, marks the old one
    ``replaced_by_id``). This is standard refresh-token rotation: it
    means a leaked *old* refresh token is useless after it's next
    used by the legitimate client, and reuse of an already-rotated
    token is a strong signal of theft (handled by revoking the whole
    session on reuse).
  * Revoking a session (logout) revokes its current refresh token.
    Revoking all of a user's sessions (logout-all / password reset)
    walks every session they have.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.domain import RefreshToken, User, UserSession


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_raw_token() -> str:
    return secrets.token_urlsafe(48)


@dataclass(frozen=True)
class IssuedSession:
    session: UserSession
    refresh_token: str
    refresh_token_row: RefreshToken


def start_session(
    db: Session,
    user: User,
    request: Request | None,
    device_id: str | None,
    device_label: str | None,
    remember_me: bool,
) -> IssuedSession:
    """Create a new session + its first refresh token. Called once per
    successful login (not on refresh — see ``rotate_refresh_token``)."""
    resolved_device_id = device_id or secrets.token_hex(16)
    ip_address = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None

    session_row = UserSession(
        user_id=user.id,
        device_id=resolved_device_id,
        device_label=device_label,
        ip_address=ip_address,
        user_agent=user_agent[:400] if user_agent else None,
        remember_me=remember_me,
    )
    db.add(session_row)
    db.flush()  # assigns session_row.id without ending the caller's transaction

    raw_token, token_row = _issue_refresh_token(db, user, session_row, remember_me)
    return IssuedSession(session=session_row, refresh_token=raw_token, refresh_token_row=token_row)


def _issue_refresh_token(
    db: Session, user: User, session_row: UserSession, remember_me: bool, replaces: RefreshToken | None = None
) -> tuple[str, RefreshToken]:
    days = settings.refresh_token_remember_me_days if remember_me else settings.refresh_token_days
    raw_token = _new_raw_token()
    row = RefreshToken(
        user_id=user.id,
        session_id=session_row.id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.utcnow() + timedelta(days=days),
    )
    db.add(row)
    db.flush()
    if replaces is not None:
        replaces.replaced_by_id = row.id
    return raw_token, row


def rotate_refresh_token(db: Session, raw_token: str) -> tuple[User, IssuedSession]:
    """Validate an incoming refresh token and rotate it.

    Raises HTTPException(401) for any invalid, expired, revoked, or
    already-rotated token. Reuse of an already-rotated token revokes
    the entire session it belongs to (theft signal), matching the
    module docstring's rotation-detection design.

    V17.2 — also enforces idle/absolute session timeouts here. This is
    the natural checkpoint: access tokens are short-lived (15 min by
    default), so a legitimate client calls this frequently, making it
    an effective (not just theoretical) place to expire a session —
    unlike e.g. only checking on next login, which could be arbitrarily
    far in the future for a "remember me" session that's still being
    silently refreshed by a background tab.
    """
    token_hash = _hash_token(raw_token)
    # V25.6: lock the token row for the duration of the rotation transaction. Without
    # this, two concurrent refresh calls presenting the same token could both pass the
    # "not yet rotated" check and each mint a new refresh token. (No-op on SQLite.)
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update())
    if not row:
        raise HTTPException(401, "Invalid refresh token")

    session_row = db.get(UserSession, row.session_id)
    if not session_row or session_row.revoked_at is not None:
        raise HTTPException(401, "Session has been revoked")

    now = datetime.utcnow()
    idle_cutoff = session_row.last_seen_at + timedelta(minutes=settings.session_idle_timeout_minutes)
    absolute_cutoff = session_row.created_at + timedelta(days=settings.session_absolute_timeout_days)
    if now > idle_cutoff or now > absolute_cutoff:
        _revoke_session(db, session_row)
        db.commit()
        reason = "inactivity" if now > idle_cutoff else "maximum session age"
        raise HTTPException(401, f"Session expired ({reason}); please log in again")

    if row.revoked_at is not None or row.replaced_by_id is not None:
        # Reuse of a token that was already rotated away — treat as
        # compromise and kill the whole session so both the attacker
        # and the legitimate client are forced to log in again.
        _revoke_session(db, session_row)
        # V25.6: SecurityEvent.REFRESH_TOKEN_REUSE_DETECTED existed in the taxonomy (and in
        # the admin security-events screen) but was never actually emitted. No token value
        # is recorded - only the user and session ids.
        from app.core.security_events import SecurityEvent, record_security_event

        record_security_event(
            db,
            SecurityEvent.REFRESH_TOKEN_REUSE_DETECTED,
            entity_type="user",
            entity_id=str(row.user_id),
            detail=f"session_id={session_row.id}",
        )
        db.commit()
        raise HTTPException(401, "Refresh token reuse detected; session revoked")

    if row.expires_at < datetime.utcnow():
        raise HTTPException(401, "Refresh token expired")

    user = db.get(User, row.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Invalid user")

    row.revoked_at = datetime.utcnow()
    session_row.last_seen_at = datetime.utcnow()
    new_raw, new_row = _issue_refresh_token(db, user, session_row, session_row.remember_me, replaces=row)
    return user, IssuedSession(session=session_row, refresh_token=new_raw, refresh_token_row=new_row)


def _revoke_session(db: Session, session_row: UserSession) -> None:
    if session_row.revoked_at is None:
        session_row.revoked_at = datetime.utcnow()
    active = db.scalars(
        select(RefreshToken).where(
            RefreshToken.session_id == session_row.id,
            RefreshToken.revoked_at.is_(None),
        )
    ).all()
    for t in active:
        t.revoked_at = datetime.utcnow()


def revoke_session_by_refresh_token(db: Session, raw_token: str, user: User | None = None) -> None:
    """Logout of the current device.

    V25.6: when ``user`` is given, a refresh token that belongs to a *different* user is
    ignored (defence in depth - the token is a 384-bit secret, so this is not reachable
    without already holding someone else's refresh token)."""
    token_hash = _hash_token(raw_token)
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if not row:
        return
    if user is not None and row.user_id != user.id:
        return
    session_row = db.get(UserSession, row.session_id)
    if session_row:
        _revoke_session(db, session_row)


def revoke_current_session_from_claims(db: Session, user: User, session_id: int | None) -> bool:
    """V25.6 — logout must end the session the request is actually using, not only the
    one a client-supplied refresh token points at. ``session_id`` is the ``sid`` claim of
    the caller's own (already verified) access token; ownership is re-checked here."""
    if session_id is None:
        return False
    return revoke_session_by_id(db, user, session_id)


def revoke_session_by_id(db: Session, user: User, session_id: int) -> bool:
    session_row = db.get(UserSession, session_id)
    if not session_row or session_row.user_id != user.id:
        return False
    _revoke_session(db, session_row)
    return True


def revoke_session_by_id_admin(db: Session, session_id: int) -> UserSession | None:
    """V17.2 — admin variant of revoke_session_by_id: no ownership
    check, since the caller is an admin route already authorized by
    app.api.admin.guard, not the session's own owner. Returns the
    revoked session (so the caller can report which user it belonged
    to) or None if it doesn't exist."""
    session_row = db.get(UserSession, session_id)
    if not session_row:
        return None
    _revoke_session(db, session_row)
    return session_row


def revoke_all_sessions(db: Session, user: User, except_session_id: int | None = None) -> int:
    """Logout of every device. Used for the explicit "logout all
    sessions" action, and also on password reset (a changed password
    should invalidate every other refresh token in flight)."""
    sessions = db.scalars(
        select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
    ).all()
    count = 0
    for s in sessions:
        if except_session_id is not None and s.id == except_session_id:
            continue
        _revoke_session(db, s)
        count += 1
    return count


def list_active_sessions(db: Session, user: User) -> list[UserSession]:
    return list(
        db.scalars(
            select(UserSession)
            .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .order_by(UserSession.last_seen_at.desc())
        ).all()
    )


def list_all_active_sessions(
    db: Session, limit: int = 50, offset: int = 0, user_id: int | None = None
) -> list[UserSession]:
    """V17.3 — system-wide active-session listing for the admin panel
    (as opposed to list_active_sessions above, which is scoped to one
    user for self-service / the existing per-user admin endpoint)."""
    query = select(UserSession).where(UserSession.revoked_at.is_(None))
    if user_id is not None:
        query = query.where(UserSession.user_id == user_id)
    query = query.order_by(UserSession.last_seen_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(query).all())


def count_active_sessions(db: Session, user_id: int | None = None) -> int:
    query = select(func.count()).select_from(UserSession).where(UserSession.revoked_at.is_(None))
    if user_id is not None:
        query = query.where(UserSession.user_id == user_id)
    return db.scalar(query) or 0
