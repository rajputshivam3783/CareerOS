"""Rate limiter — in-memory by default, optionally Redis-backed.

The in-memory implementation (used whenever ``settings.redis_url`` is
unset — the default) is a real mitigation against casual
credential-stuffing/brute-force scripts, but it is per-process:
running more than one backend replica means each has its own budget,
which is effectively a higher combined limit than intended.

V16 — docker-compose.production.yml has referenced an optional
``REDIS_URL`` since it was written, with a comment saying the limiter
"falls back to in-memory when unset". Until now that was only half
true: the fallback was real, but there was no Redis path to fall back
*from* — REDIS_URL was never actually read anywhere. That's fixed
here: when ``settings.redis_url`` is set, hits are counted with a
Redis fixed-window counter (``INCR`` + ``EXPIRE``) shared across every
process/replica pointed at the same Redis instance. If Redis is
configured but unreachable at request time, this fails *open* to the
in-memory limiter for that call rather than either crashing the
request or (worse) silently allowing unlimited attempts — logged once
per bucket so an operator notices, not once per request.
"""

import logging
import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request

from app.core.config import settings

log = logging.getLogger("careeros.rate_limit")

_hits: dict[str, list[float]] = defaultdict(list)
_lock = Lock()

_redis_client = None
_redis_init_attempted = False
_redis_warned_buckets: set[str] = set()


def _get_redis_client():
    """Lazily construct a redis client the first time it's needed, so
    a deployment that never sets REDIS_URL never imports/depends on
    the redis package at all — it stays an optional extra, not a hard
    dependency (see requirements.txt)."""
    global _redis_client, _redis_init_attempted
    if _redis_init_attempted:
        return _redis_client
    _redis_init_attempted = True
    if not settings.redis_url:
        return None
    try:
        import redis  # local import — see docstring above

        _redis_client = redis.Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
        _redis_client.ping()
    except Exception:
        log.warning("REDIS_URL is set but Redis is unreachable at startup; falling back to in-memory rate limiting.")
        _redis_client = None
    return _redis_client


# V25.6 — bound the in-memory table. Previously a key was never removed once created, so a
# flood of requests from many distinct addresses grew this dict without limit (slow memory
# exhaustion). Entries whose newest hit is older than the longest window in use are dropped,
# and if an attack keeps the table above the cap the least-recently-hit keys are evicted.
_MAX_TRACKED_KEYS = 20000
_PRUNE_HORIZON_SECONDS = 3600.0


def _prune_locked(now: float) -> None:
    stale = [k for k, hits in _hits.items() if not hits or now - hits[-1] >= _PRUNE_HORIZON_SECONDS]
    for k in stale:
        del _hits[k]
    overflow = len(_hits) - _MAX_TRACKED_KEYS
    if overflow > 0:
        for k, _ in sorted(_hits.items(), key=lambda item: item[1][-1])[:overflow]:
            del _hits[k]


def _enforce_in_memory(key: str, limit: int, window: int) -> None:
    now = time.monotonic()
    with _lock:
        if len(_hits) > _MAX_TRACKED_KEYS:
            _prune_locked(now)
        attempts = [t for t in _hits[key] if now - t < window]
        if len(attempts) >= limit:
            _hits[key] = attempts
            raise HTTPException(status_code=429, detail="Too many attempts. Please try again shortly.")
        attempts.append(now)
        _hits[key] = attempts


def _enforce_redis(client, key: str, limit: int, window: int, bucket: str) -> bool:
    """Returns True if it successfully enforced the limit via Redis,
    False if Redis itself failed and the caller should fall back."""
    try:
        redis_key = f"careeros:ratelimit:{key}"
        count = client.incr(redis_key)
        if count == 1:
            client.expire(redis_key, window)
        if count > limit:
            raise HTTPException(status_code=429, detail="Too many attempts. Please try again shortly.")
        return True
    except HTTPException:
        raise
    except Exception:
        if bucket not in _redis_warned_buckets:
            _redis_warned_buckets.add(bucket)
            log.warning("Redis rate-limit check failed for bucket %r; falling back to in-memory for this call.", bucket)
        return False


def enforce_rate_limit(request: Request, bucket: str, limit: int | None = None, window: int | None = None) -> None:
    """Raise 429 if the caller has exceeded the allowed attempt rate.

    ``bucket`` namespaces the limit (e.g. "login", "register",
    "admin-key") so different endpoints don't share one budget. Keyed
    by client IP.

    V17.2 — ``limit``/``window`` are optional per-call overrides for a
    bucket that needs a different budget than the shared
    ``auth_rate_limit_attempts``/``auth_rate_limit_window_seconds``
    default (e.g. a stricter one for admin login). Every pre-existing
    call site omits them and keeps behaving exactly as before.
    """
    client_ip = request.client.host if request.client else "unknown"
    key = f"{bucket}:{client_ip}"
    window = window if window is not None else settings.auth_rate_limit_window_seconds
    limit = limit if limit is not None else settings.auth_rate_limit_attempts

    client = _get_redis_client()
    if client is not None and _enforce_redis(client, key, limit, window, bucket):
        return
    _enforce_in_memory(key, limit, window)
