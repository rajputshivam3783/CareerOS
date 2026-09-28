"""V25.6 — reusable pydantic field validators.

Kept separate from ``app.core.hardening`` (which is standard-library only, so it can be
imported anywhere and unit-tested without pydantic).
"""

from __future__ import annotations

from pydantic import field_validator

from app.core.hardening import validate_http_url


def http_url_validator(*fields: str, assume_https: bool = False):
    """Field validator: the value must be empty or an absolute http(s) URL.

    Rejects ``javascript:``, ``data:``, ``file:``, relative paths, control characters and
    URLs with embedded credentials (HTTP 422). Use it on every URL a recruiter, partner or
    organization can supply, because a browser will later render it as a link.

        class JobIn(BaseModel):
            apply_url: str | None = None
            _validate_urls = http_url_validator("apply_url")

    ``assume_https=True`` is for human-typed fields (company website, ...): a bare
    ``acme.com/careers`` becomes ``https://acme.com/careers``. Anything that already
    contains a colon (``javascript:...``, ``mailto:...``, ``acme.com:8080``) is *not*
    rewritten and is rejected by the http(s) check.
    """

    def _check(value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("URL must be a string")
        candidate = value.strip()
        if assume_https and candidate and ":" not in candidate and "." in candidate and " " not in candidate:
            candidate = "https://" + candidate
        return validate_http_url(candidate)

    return field_validator(*fields)(_check)
