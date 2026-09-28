"""V25.6 — last-line database guard against script-scheme URLs.

Every user-, partner- or scraper-supplied URL eventually reaches a browser as an
``<a href>``. API inputs are validated with an allow-list (``app.core.validators``), but
jobs also arrive through ingestion adapters, admin tools and pre-V25.6 rows, none of which
can return a 422 to a person. This installs a SQLAlchemy attribute-``set`` listener on
every URL-like string column of every mapped model: a value using a ``javascript:``,
``data:``, ``vbscript:``, ``file:`` or ``blob:`` scheme is stored as NULL instead.

Deliberately a deny-list, not an allow-list: it must never turn a merely *odd* value
(relative path, malformed URL that data-quality checks are meant to report) into data
loss. The browser app additionally refuses non-http(s) hrefs (frontend/src/lib/safe.ts).
"""

from __future__ import annotations

import logging

from sqlalchemy import String, event

from app.core.hardening import has_dangerous_url_scheme

log = logging.getLogger("careeros.url_guard")

_installed = False

_URL_COLUMN_NAMES = {"url", "website", "official_website", "job_url", "meeting_url"}


def _is_url_column(name: str) -> bool:
    return name in _URL_COLUMN_NAMES or name.endswith("_url")


def _guard(target, value, oldvalue, initiator):
    if isinstance(value, str) and has_dangerous_url_scheme(value):
        log.warning("Dropped a URL with a dangerous scheme on %s.%s", type(target).__name__, getattr(initiator, "key", "?"))
        return None
    return value


def install_url_guards(base) -> int:
    """Attach the guard to every URL-like String column mapped under ``base``.
    Idempotent. Returns the number of columns guarded (0 on repeat calls)."""
    global _installed
    if _installed:
        return 0
    guarded = 0
    for mapper in base.registry.mappers:
        for attr in mapper.column_attrs:
            column = attr.columns[0]
            if _is_url_column(attr.key) and isinstance(column.type, String):
                event.listen(getattr(mapper.class_, attr.key), "set", _guard, retval=True)
                guarded += 1
    _installed = True
    return guarded
