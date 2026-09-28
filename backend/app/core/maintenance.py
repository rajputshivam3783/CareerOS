"""V25.2 — maintenance mode (spec section 20).

WHAT IT DOES
------------
When the ``maintenance_mode`` platform setting is on, ordinary API
traffic receives ``503`` with a JSON body carrying the configured
message and ``Retry-After``. Platform administrators keep full access,
so the people who can turn it back off are never locked out.

WHAT IS NEVER BLOCKED
---------------------
- ``/health``, ``/live``, ``/ready``, ``/metrics`` — an orchestrator
  must still be able to tell a maintaining process from a dead one.
  Blocking readiness probes during maintenance would get the pod
  killed and restarted in a loop.
- ``/api/v1/auth/login`` and the token-refresh endpoints — an
  administrator has to be able to *obtain* a token to prove they are
  an administrator. Blocking login would make the admin exemption
  unreachable, which is precisely the "do not accidentally lock all
  administrators out" failure section 20 names.
- Every ``/api/v1/admin/...`` route — those carry their own
  platform-admin authorization, so leaving them open here delegates
  the decision to the gate that is actually qualified to make it
  rather than duplicating role logic in middleware.
- ``OPTIONS`` preflight requests, which carry no credentials and whose
  failure would surface to the browser as an opaque CORS error rather
  than as the maintenance message.

FAIL-OPEN, DELIBERATELY
-----------------------
If the setting cannot be read (database briefly unavailable), the
request proceeds. Maintenance mode is an operational convenience, not
a security control — no authorization decision depends on it — so the
correct failure mode is "serve the request" rather than "take the
entire platform down because a flag lookup failed". Every actual
authorization check in CareerOS fails *closed*; this one is not an
authorization check.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.hardening import safe_equals
from app.core.platform_admin import platform_permissions_for_role
from app.core.security import decode_access_token

log = logging.getLogger("careeros.maintenance")

# Exact paths that must keep working regardless of maintenance state.
ALWAYS_ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        "/",
        "/health",
        "/live",
        "/ready",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/v1/auth/login",
        "/api/v1/auth/recruiter/login",
        "/api/v1/auth/admin/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
    }
)

# Path prefixes that must keep working — the admin surface, which
# gates itself.
ALWAYS_ALLOWED_PREFIXES: tuple[str, ...] = ("/api/v1/admin",)


def _is_platform_admin_request(request: Request) -> bool:
    """Decide from the Bearer token alone whether this caller is a
    platform administrator.

    Deliberately does NOT open a database session: this runs on every
    request, and adding a DB round-trip to all traffic to support a
    rarely-used flag would be a poor trade. The role claim is part of
    the JWT this server signed, so trusting it *for this purpose* is
    sound — and the consequence of being wrong is only that a request
    is allowed through during maintenance, never that it bypasses an
    authorization check. Every endpoint the request then reaches still
    performs its own full, database-backed authorization.
    """
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        # The shared admin key is also honoured, for the same reason
        # it is honoured everywhere else in this codebase.
        #
        # V25.6: it must now actually MATCH the configured key. Previously the mere
        # presence of any X-Admin-Key header (any value) bypassed maintenance mode.
        supplied = request.headers.get("x-admin-key")
        return bool(settings.admin_key_auth_enabled and supplied and safe_equals(supplied, settings.admin_api_key))
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_access_token(token)
    except Exception:
        return False
    return bool(platform_permissions_for_role(claims.get("role")))


async def maintenance_mode_middleware(request: Request, call_next):
    path = request.url.path
    if (
        request.method == "OPTIONS"
        or path in ALWAYS_ALLOWED_PATHS
        or path.startswith(ALWAYS_ALLOWED_PREFIXES)
    ):
        return await call_next(request)

    try:
        from app.core.platform_settings import get_setting_safe, peek_cached

        # Fast path: the settings cache is warm, so this costs nothing
        # per request. Only a cold cache opens a database session.
        hit, cached = peek_cached("maintenance_mode")
        if hit and not cached:
            return await call_next(request)

        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            enabled = bool(get_setting_safe(db, "maintenance_mode", False))
            message = get_setting_safe(db, "maintenance_message", "") if enabled else ""
        finally:
            db.close()
    except Exception:
        log.warning("Maintenance-mode check failed; serving the request", exc_info=True)
        return await call_next(request)

    if not enabled or _is_platform_admin_request(request):
        return await call_next(request)

    return JSONResponse(
        status_code=503,
        content={"detail": message or "CareerOS is temporarily unavailable for maintenance.", "maintenance": True},
        headers={"Retry-After": "300"},
    )
