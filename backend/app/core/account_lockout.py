"""V17.2 — account lockout.

Deliberately separate from ``app.core.rate_limit``: the rate limiter
is keyed by *IP*, so it stops a single source hammering many accounts
(or one account) fast. This module is keyed by *account*, so it stops
an attacker rotating IPs against one known email — a real gap the
per-IP limiter alone doesn't close.

Two tiers, both scoped to ``app.api.auth._login``:

1. **Progressive delay** — once ``failed_login_count`` passes
   ``account_progressive_delay_after_attempts``, each subsequent
   attempt must wait an increasing number of seconds since the last
   failure. This is enforced by *rejecting* an attempt that arrives
   too soon (HTTP 429) — never by having the request thread sleep,
   which would tie up a worker and is itself a mini denial-of-service
   risk under load.
2. **Temporary lock** — at ``account_lockout_threshold`` failures, the
   account is locked for a duration that escalates with
   ``User.lock_count`` (a repeat offender gets a longer lock each
   time), capped at ``account_lockout_max_minutes``. Lifts
   automatically once ``locked_until`` passes — no separate cleanup
   job needed, since the check happens at login time regardless.

**Permanent lock reuses ``User.active``**, deliberately, rather than
adding a redundant column: every authentication code path in this
project (``_login``, ``current_user``, ``rotate_refresh_token``)
already checks ``user.active`` and already treats an inactive user as
fully unable to authenticate, including with existing valid sessions/
tokens — which a *temporary* lock (this module) does not attempt to
do, to avoid touching those call sites for what "do not redesign
authentication" scopes as a login-time control. An admin sets
``active=False`` via ``POST /admin/users/{id}/lock`` with
``permanent=true`` (see app.api.admin) to invoke it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.config import settings
from app.core.security_events import SecurityEvent, record_security_event
from app.models.domain import User
from sqlalchemy.orm import Session


def progressive_delay_seconds(failed_login_count: int) -> int:
    """Seconds an account must wait since its last failure, given how
    many failures it's accumulated. 0 below the threshold."""
    threshold = settings.account_progressive_delay_after_attempts
    if failed_login_count < threshold:
        return 0
    exponent = failed_login_count - threshold
    delay = settings.account_progressive_delay_base_seconds * (2**exponent)
    return min(delay, settings.account_progressive_delay_max_seconds)


def lock_duration_minutes(lock_count: int) -> int:
    """Escalating lock duration for repeat offenders: doubles per
    prior lock, capped. lock_count=0 (first-ever lock) -> base."""
    duration = settings.account_lockout_base_minutes * (2**lock_count)
    return min(duration, settings.account_lockout_max_minutes)


def seconds_until_unlocked(user: User, now: datetime) -> int:
    if not user.locked_until or user.locked_until <= now:
        return 0
    return int((user.locked_until - now).total_seconds())


def clear_lock_if_expired(user: User, now: datetime) -> None:
    """Auto-lift an expired temporary lock. Does not touch
    failed_login_count — a successful login is what resets that (see
    record_successful_login); merely waiting out a lock and then
    failing again should still count as continued abuse."""
    if user.locked_until and user.locked_until <= now:
        user.locked_until = None


def is_locked(user: User, now: datetime) -> bool:
    return bool(user.locked_until and user.locked_until > now)


def record_failed_login(db: Session, user: User) -> bool:
    """Call after a failed password check for a *known* user (not for
    a nonexistent email — there's nothing to track). Returns True if
    this attempt just triggered a new temporary lock."""
    now = datetime.utcnow()
    user.failed_login_count += 1
    user.last_failed_login_at = now

    if user.failed_login_count >= settings.account_lockout_threshold:
        duration = lock_duration_minutes(user.lock_count)
        user.locked_until = now + timedelta(minutes=duration)
        user.lock_count += 1
        user.failed_login_count = 0  # this cycle's counting is done; a fresh count starts after unlock
        record_security_event(
            db, SecurityEvent.ACCOUNT_LOCKED, entity_type="user", entity_id=str(user.id),
            detail=f"temporary lock #{user.lock_count}, {duration}min",
        )
        return True
    return False


def record_successful_login(db: Session, user: User) -> None:
    if user.failed_login_count or user.locked_until:
        user.failed_login_count = 0
        user.locked_until = None
