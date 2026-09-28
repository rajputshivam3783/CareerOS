"""Password hashing and JWT-based authentication.

V17.1 Auth Core: access tokens are now short-lived (see
``settings.access_token_minutes``) and carry a ``sid`` (session id)
claim in addition to ``sub``/``role``, so a revoked session's access
tokens can be told apart from another session's even though both
belong to the same user. Long-lived sessions live in
``app.core.sessions`` (refresh-token issuance/rotation/revocation),
kept in a separate module so this file stays focused on password
hashing + short-lived access-token verification, matching its
existing single responsibility rather than growing into a mixed
auth/session module.
"""

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.request_context import Actor, set_actor
from app.db.session import get_db
from app.models.domain import User, UserSession

ph = PasswordHash.recommended()  # Argon2id with sane defaults.
bearer = HTTPBearer(auto_error=False)

# Roles that are allowed to authenticate at all. Admin/super_admin
# accounts are never created through public registration (see
# app/api/admin.py's create_admin_user, gated the same way every other
# admin route already is) — this set only governs which roles a
# *token* can legitimately carry, not who can request one.
KNOWN_ROLES = {"candidate", "recruiter", "admin", "super_admin"}
ADMIN_ROLES = {"admin", "super_admin"}


def decode_access_token(token: str) -> dict:
    """Verify signature and expiry of an access token and return its claims.

    V25.6: ``exp`` and ``sub`` are *required* claims. PyJWT only checks ``exp`` when it
    is present, so a (hypothetical) token minted without one would otherwise never
    expire. Every place that decodes an access token goes through here."""
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})


def access_token_session_is_active(db: Session, claims: dict) -> bool:
    """False if the token's session has been revoked (logout, "log out this device",
    logout-all, password reset, refresh-token reuse detection, admin revocation).

    Tokens without a ``sid`` claim (issued by the legacy session-less code path) are
    accepted, as before. A token whose ``sid`` points at a missing session, or at a
    session that belongs to a different user, is rejected."""
    if not settings.access_token_session_check:
        return True
    sid = claims.get("sid")
    if sid is None:
        return True
    try:
        session_id = int(sid)
        user_id = int(claims["sub"])
    except (TypeError, ValueError, KeyError):
        return False
    session_row = db.get(UserSession, session_id)
    return session_row is not None and session_row.revoked_at is None and session_row.user_id == user_id


def hash_password(value: str) -> str:
    return ph.hash(value)


def verify_password(value: str, hashed: str) -> bool:
    return ph.verify(value, hashed)


def token_for(user: User, session_id: int | None = None) -> str:
    """Issue a short-lived access token.

    ``session_id`` is optional so this still works for any code path
    that hasn't been migrated to session-aware login (kept for
    backward compatibility — see app/api/auth.py's legacy aliases);
    when present it's embedded as ``sid`` for forward-compatibility
    with session-aware access-token checks.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "sid": session_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(401, "Authentication required")

    try:
        claims = decode_access_token(credentials.credentials)
        user_id = int(claims["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

    user = db.get(User, user_id)
    if not user or not user.active:
        raise HTTPException(401, "Invalid user")
    # V25.6: a revoked session's access token stops working immediately.
    if not access_token_session_is_active(db, claims):
        raise HTTPException(401, "Session has been revoked")
    # V16 — every authenticated request now has an actor in context, so
    # app.core.audit.log_audit can attribute recruiter/candidate actions
    # to a real user without every route remembering to set it itself
    # (previously only wired manually into the admin/auth flows).
    #
    # This dependency must stay `async def` (not plain `def`) for that
    # to actually work: FastAPI dispatches a sync callable via
    # starlette.concurrency.run_in_threadpool, which runs it inside an
    # independent contextvars.copy_context() — a set_actor() call made
    # there would never be visible to a *different* threadpool
    # submission later (the endpoint body, or another dependency). An
    # async dependency runs directly in the request's own task, so its
    # context mutation is present before any later threadpool
    # submission copies that context — the same reason request_id/
    # client_ip (set in async middleware) already work correctly.
    set_actor(Actor(actor_type="user", actor_id=str(user.id), label=user.email))
    return user


async def optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """V21.1 — like ``current_user``, but returns None instead of
    raising 401 when there's no (or an invalid) token. Added for
    endpoints that must work for anonymous visitors but personalize
    when a token is present — search is the first caller (an
    anonymous search sees public results only; a logged-in recruiter
    also sees their own unpublished postings — see
    app.search.permissions). Never raises; a bad/expired token is
    treated the same as no token, not as an error, since the whole
    point is this endpoint doesn't require auth."""
    if not credentials:
        return None
    try:
        claims = decode_access_token(credentials.credentials)
        user_id = int(claims["sub"])
    except Exception:
        return None
    user = db.get(User, user_id)
    if not user or not user.active or not access_token_session_is_active(db, claims):
        return None
    set_actor(Actor(actor_type="user", actor_id=str(user.id), label=user.email))
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    """Admin or super_admin. Reserved for role-gated endpoints that
    should key off the logged-in user's role rather than the shared
    admin API key."""
    if user.role not in ADMIN_ROLES:
        raise HTTPException(403, "Admin role required")
    return user


def require_super_admin(user: User = Depends(current_user)) -> User:
    """V17.1 — the small set of actions reserved for super_admin only
    (e.g. creating other admin/super_admin accounts)."""
    if user.role != "super_admin":
        raise HTTPException(403, "Super admin role required")
    return user


def require_recruiter(user: User = Depends(current_user)) -> User:
    """V9 — recruiter-facing endpoints authenticate as a real logged-in
    user with role='recruiter' (or an admin role, which can do anything
    a recruiter can) rather than the shared admin API key. A candidate
    can't self-elevate to recruiter by registering — only an admin can
    grant the role, via POST /admin/users/{id}/role."""
    if user.role in ADMIN_ROLES:
        return user
    if user.role != "recruiter" or user.recruiter_status != "approved":
        raise HTTPException(403, "Approved recruiter role required")
    return user


def current_session_id(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> int | None:
    """V17.3 — the ``sid`` claim of the current request's access token,
    if any (older tokens issued without session-aware login, if any
    ever reach a live server, simply have no ``sid`` — see
    ``token_for``'s docstring). Used only to mark "this is the current
    session" in a session listing; never raises, so it's safe to depend
    on even from an endpoint that doesn't otherwise require a session
    (though in practice every caller of this also depends on
    ``current_user``, which does)."""
    if not credentials:
        return None
    try:
        claims = decode_access_token(credentials.credentials)
        sid = claims.get("sid")
        return int(sid) if sid is not None else None
    except Exception:
        return None
