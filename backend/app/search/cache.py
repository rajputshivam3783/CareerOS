"""V21.1 — SEARCH PERFORMANCE: caching, done narrowly and safely.

A short-TTL, in-process cache for search/autocomplete/facets
responses, used **only** for the anonymous actor. That's a
deliberate, load-bearing restriction, not an oversight: a cached
response for a recruiter or admin could contain their own
unpublished/private rows (see app.search.permissions), and reusing
that response for a *different* logged-in user would leak private
data through the cache. Anonymous responses are, by construction
(``apply_visibility`` only ever returns ``visibility == "public"``
rows for an anonymous actor), the same for every anonymous visitor —
the one case where caching is unconditionally safe.

Invalidation: every ``app.search.hooks.sync_*`` call clears the whole
cache after a successful index write, so a newly published job is
visible to search immediately — the cache never masks V21.1's
real-time indexing (Phase 3). The TTL (default 30s) is a second,
independent bound in case a write happens through a path that isn't
hooked yet (see SEARCH_INDEXING.md for what is/isn't hooked).

This is intentionally a plain dict behind a lock, not a dependency on
Redis or another external cache — consistent with the same
"don't introduce infrastructure the repository doesn't need yet"
reasoning as the provider abstraction (see SEARCH_ARCHITECTURE.md).
A future high-traffic deployment could swap this module's two
functions for a Redis-backed implementation without touching any
caller.
"""

from __future__ import annotations

import threading
import time
from typing import Any

_TTL_SECONDS = 30.0
_MAX_ENTRIES = 500

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}


def get(key: str) -> Any | None:
    with _lock:
        entry = _store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del _store[key]
            return None
        return value


def set(key: str, value: Any, ttl: float = _TTL_SECONDS) -> None:
    with _lock:
        if len(_store) >= _MAX_ENTRIES and key not in _store:
            # Simple oldest-expiry eviction — not a strict LRU, but
            # cheap and sufficient at this scale (a few hundred distinct
            # cached queries at once is already a generous ceiling for
            # a jobs-search cache).
            oldest_key = min(_store, key=lambda k: _store[k][0])
            del _store[oldest_key]
        _store[key] = (time.monotonic() + ttl, value)


def clear() -> None:
    """Called by app.search.hooks after every successful index write —
    see this module's docstring for why a full clear (not a
    targeted invalidation) is the right trade-off here."""
    with _lock:
        _store.clear()


def cache_key(*parts: object) -> str:
    return "|".join(repr(p) for p in parts)
