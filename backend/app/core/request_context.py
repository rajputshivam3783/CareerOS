"""V16 — per-request context.

FastAPI handlers, middleware and background code all run inside the
same async task for a given request, so a ``contextvars.ContextVar``
is a safe way to make two things available anywhere in that call
stack without threading them through every function signature:

1. The request ID (generated or propagated by ``RequestIDMiddleware``
   in ``app.main``), so logs and audit rows from the same request can
   be correlated.
2. The authenticated "actor" (a User, or the shared admin key), set by
   whichever auth dependency ran for this request, so
   ``app.core.audit.log_audit`` can attribute an action without every
   call site having to pass the current user down explicitly.

Contextvars are reset per request by Starlette's ASGI machinery
(each request gets its own task), so there's no cross-request leakage
risk here the way there would be with a plain module-level global.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    actor_type: str  # "user" | "admin_key"
    actor_id: str | None
    label: str


_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_actor: ContextVar[Actor | None] = ContextVar("actor", default=None)
_client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()


def set_client_ip(value: str | None) -> None:
    _client_ip.set(value)


def get_client_ip() -> str | None:
    return _client_ip.get()


def set_actor(actor: Actor) -> None:
    _actor.set(actor)


def get_actor() -> Actor | None:
    return _actor.get()
