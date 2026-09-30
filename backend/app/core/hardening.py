"""V25.6 — security-hardening primitives (standard library only).

Everything here is a *pure function* (or a tiny class) with no import of FastAPI,
SQLAlchemy, pydantic or the app settings object. That is deliberate:

  * it can be unit-tested in isolation (see tests/test_v25_6_hardening_unit.py);
  * it can be imported from anywhere (config, logging, middleware, models) without
    creating an import cycle;
  * callers pass in the values they want checked, so nothing here reads global state.

Contents
--------
  sanitize_request_id      untrusted X-Request-ID  -> safe correlation id
  safe_equals              constant-time compare that never raises on non-ASCII
  validate_http_url        absolute http(s) URL allow-list (blocks javascript:/data:/...)
  is_placeholder_secret    detects .env.example / default secrets
  production_config_findings   fatal errors + warnings for a production deployment
  sanitize_display_filename    client-supplied filename -> safe display string
  validate_file_signature      magic-byte + archive-bomb checks for uploads
  redact_sensitive_text / RedactingFilter   keeps credentials out of log lines
  neutralize_prompt_delimiters   stops untrusted text closing an LLM delimiter block
  api_security_headers     headers for JSON API responses

None of these is a substitute for authorization checks; they are input/output
hygiene that removes whole classes of bug.
"""

from __future__ import annotations

import hmac
import io
import logging
import os
import re
import zipfile
from typing import Iterable, Mapping
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
# Request IDs
# ---------------------------------------------------------------------------

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")


def sanitize_request_id(candidate: str | None, generate) -> str:
    """Return ``candidate`` only if it is a short, boring token; otherwise a freshly
    generated id. An inbound X-Request-ID flows into log lines, audit rows and a
    response header, so it must not carry newlines, control characters or unbounded
    length (log injection / log flooding)."""
    if candidate and _REQUEST_ID_RE.match(candidate):
        return candidate
    return generate()


# ---------------------------------------------------------------------------
# Constant-time comparison
# ---------------------------------------------------------------------------


def safe_equals(a: str | bytes | None, b: str | bytes | None) -> bool:
    """``hmac.compare_digest`` on bytes. ``compare_digest`` raises TypeError for str
    arguments containing non-ASCII characters, which turned a hostile header value into
    an HTTP 500; encoding first makes it a plain ``False``."""
    if a is None or b is None:
        return False
    a_bytes = a if isinstance(a, bytes) else a.encode("utf-8", "surrogatepass")
    b_bytes = b if isinstance(b, bytes) else b.encode("utf-8", "surrogatepass")
    return hmac.compare_digest(a_bytes, b_bytes)


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def validate_http_url(value: str | None, *, max_length: int = 1000) -> str | None:
    """Return the stripped URL if it is an absolute http(s) URL with a host, ``None`` for
    empty input, and raise ``ValueError`` for anything else (javascript:, data:, file:,
    relative paths, control characters, over-long values).

    Used as a pydantic field-validator helper for every user/partner-supplied URL that a
    browser will later render as a link."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) > max_length:
        raise ValueError(f"URL must be at most {max_length} characters")
    if _CONTROL_CHARS_RE.search(stripped):
        raise ValueError("URL contains control characters")
    parts = urlsplit(stripped)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError("URL must be an absolute http:// or https:// address")
    if parts.username or parts.password:
        raise ValueError("URL must not embed credentials")
    return stripped


_DANGEROUS_URL_SCHEMES = ("javascript:", "data:", "vbscript:", "file:", "blob:")


def has_dangerous_url_scheme(value: str | None) -> bool:
    """True if ``value`` starts with a scheme that executes or exfiltrates when used as a
    link target. Whitespace/control characters are removed first because browsers ignore
    tabs and newlines inside a scheme (``java\nscript:``).

    This is a *deny-list* used as a last-resort database guard for data that arrives by
    paths that cannot be given an API 422 (ingestion, admin tools, legacy rows). API
    inputs use the stricter allow-list ``validate_http_url``."""
    if not value:
        return False
    compact = re.sub(r"[\x00-\x20\x7f]", "", value).lower()
    return compact.startswith(_DANGEROUS_URL_SCHEMES)


def is_safe_http_url(value: str | None) -> bool:
    try:
        return validate_http_url(value) is not None
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Secrets / production configuration
# ---------------------------------------------------------------------------

_PLACEHOLDER_PREFIXES = (
    "change-this",
    "changeme",
    "change_me",
    "replace-with",
    "replace_with",
    "replace-me",
    "your-",
    "your_",
    "example",
    "placeholder",
    "secret",
    "password",
    "default",
    "insecure",
    "dev-",
    "test-",
)


def is_placeholder_secret(value: str | None) -> bool:
    """True for empty values and for anything that looks like a template default —
    including the exact strings shipped in ``.env.example``, which are long enough to
    pass a naive length check."""
    if not value:
        return True
    lowered = value.strip().lower()
    if not lowered:
        return True
    if any(lowered.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES):
        return True
    # A single repeated character ("aaaaaaaa...") is not a secret.
    if len(set(lowered)) <= 2:
        return True
    return False


def production_config_findings(
    *,
    jwt_secret: str,
    admin_api_key: str,
    database_url: str,
    smtp_host: str | None,
    smtp_from_email: str | None,
    cors_origins: Iterable[str],
    auto_verify_email_in_tests: bool,
    email_mode: str,
    jwt_min_length: int = 32,
    admin_key_min_length: int = 24,
) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for a production deployment.

    ``errors`` must stop the process from starting; ``warnings`` are logged. Kept
    separate from ``app.main`` so every rule is unit-testable without booting the app."""
    errors: list[str] = []
    warnings: list[str] = []

    if is_placeholder_secret(jwt_secret) or len(jwt_secret) < jwt_min_length:
        errors.append(f"JWT_SECRET must be a random secret of at least {jwt_min_length} characters (not a placeholder)")
    if is_placeholder_secret(admin_api_key) or len(admin_api_key) < admin_key_min_length:
        errors.append(
            f"ADMIN_API_KEY must be a random secret of at least {admin_key_min_length} characters (not a placeholder)"
        )
    if jwt_secret and admin_api_key and jwt_secret == admin_api_key:
        errors.append("JWT_SECRET and ADMIN_API_KEY must be different values")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        errors.append("Production requires PostgreSQL")
    if not smtp_host or not smtp_from_email:
        errors.append("Production requires SMTP configuration for verified-email authentication")
    if auto_verify_email_in_tests:
        errors.append("AUTO_VERIFY_EMAIL_IN_TESTS must not be enabled in production (it bypasses email verification)")
    if (email_mode or "").lower() not in {"smtp", "brevo"}:
        errors.append(
            "EMAIL_MODE must be 'smtp' or 'brevo' in production "
            "(console mode never delivers OTP or reset emails)"
        )

    origins = [o for o in cors_origins]
    if not origins:
        errors.append("FRONTEND_ORIGIN must list at least one allowed browser origin")
    for origin in origins:
        if origin == "*" or "*" in origin:
            errors.append("FRONTEND_ORIGIN must not contain a wildcard: credentialed CORS requires explicit origins")
            continue
        parts = urlsplit(origin)
        if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path not in {"", "/"}:
            errors.append(f"FRONTEND_ORIGIN entry {origin!r} is not a bare origin like https://app.example.com")
        elif parts.scheme == "http" and parts.hostname not in {"localhost", "127.0.0.1"}:
            warnings.append(f"FRONTEND_ORIGIN entry {origin!r} uses plain http:// in production")
        elif parts.hostname in {"localhost", "127.0.0.1"}:
            warnings.append(f"FRONTEND_ORIGIN entry {origin!r} is a localhost origin in production")
    return errors, warnings


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------

_FILENAME_STRIP_RE = re.compile(r"[\x00-\x1f\x7f\\/:*?\"<>|]")


def sanitize_display_filename(name: str | None, *, fallback: str = "document", max_length: int = 255) -> str:
    """Filename safe to store and to echo back in a Content-Disposition header.

    The on-disk name is always a server-generated UUID (see app.applications.documents);
    this only cleans the *display* name: no path components, no control characters, no
    characters that are special in shells/HTML/headers, bounded length."""
    if not name:
        return fallback
    base = name.replace("\\", "/").split("/")[-1]
    base = _FILENAME_STRIP_RE.sub("_", base).strip(" .")
    if not base:
        return fallback
    return base[:max_length]


_PNG = b"\x89PNG\r\n\x1a\n"
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# Archive-bomb guards for .docx (which is a zip container parsed by python-docx).
MAX_ZIP_ENTRIES = 2000
MAX_ZIP_TOTAL_UNCOMPRESSED = 200 * 1024 * 1024
MAX_ZIP_SINGLE_ENTRY = 100 * 1024 * 1024
MAX_ZIP_RATIO = 200


def validate_file_signature(filename: str, data: bytes) -> None:
    """Raise ``ValueError`` if ``data`` does not look like what ``filename``'s extension
    claims. Extension + client-supplied Content-Type alone are trivially spoofed.

    This is a *format sanity check*, not malware scanning. Files are still stored under a
    random name, never executed, and always served as attachments with nosniff."""
    ext = os.path.splitext((filename or "").lower())[1]
    if ext == ".pdf":
        if b"%PDF-" not in data[:1024]:
            raise ValueError("File content is not a valid PDF")
    elif ext == ".png":
        if not data.startswith(_PNG):
            raise ValueError("File content is not a valid PNG image")
    elif ext in {".jpg", ".jpeg"}:
        if not data.startswith(b"\xff\xd8\xff"):
            raise ValueError("File content is not a valid JPEG image")
    elif ext == ".doc":
        if not data.startswith(_OLE):
            raise ValueError("File content is not a valid legacy Word document")
    elif ext == ".docx":
        _validate_docx(data)
    elif ext == ".txt":
        if b"\x00" in data[:8192]:
            raise ValueError("Text file contains binary data")


def _validate_docx(data: bytes) -> None:
    if not data.startswith(b"PK\x03\x04"):
        raise ValueError("File content is not a valid DOCX document")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise ValueError("DOCX archive has too many entries")
            total = 0
            names = set()
            for info in infos:
                name = info.filename
                if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
                    raise ValueError("DOCX archive contains an unsafe path")
                names.add(name)
                if info.file_size > MAX_ZIP_SINGLE_ENTRY:
                    raise ValueError("DOCX archive entry is too large")
                if info.compress_size and info.file_size / info.compress_size > MAX_ZIP_RATIO and info.file_size > 1024 * 1024:
                    raise ValueError("DOCX archive has a suspicious compression ratio")
                total += info.file_size
                if total > MAX_ZIP_TOTAL_UNCOMPRESSED:
                    raise ValueError("DOCX archive expands to too much data")
            if "[Content_Types].xml" not in names or not any(n.startswith("word/") for n in names):
                raise ValueError("File content is not a valid DOCX document")
    except zipfile.BadZipFile as exc:
        raise ValueError("File content is not a valid DOCX document") from exc


# ---------------------------------------------------------------------------
# Log redaction
# ---------------------------------------------------------------------------

_REDACTED = "[REDACTED]"

_REDACTION_RULES: tuple[tuple[re.Pattern, str], ...] = (
    # Authorization headers / bearer tokens
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/\-]{8,}=*"), r"\1 " + _REDACTED),
    # JWT-shaped strings
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]*"), _REDACTED),
    # key=value / "key": "value" for credential-ish keys
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|refresh[_-]?token|access[_-]?token|otp|otp[_-]?code|"
            r"admin[_-]?key|x-admin-key|authorization|client[_-]?secret)\b([\"']?\s*[:=]\s*[\"']?)([^\s,\"'&;}\]]+)"
        ),
        r"\1\2" + _REDACTED,
    ),
    # Provider API keys
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), _REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), _REDACTED),
    # Credentials embedded in URLs: scheme://user:password@host
    (re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^:/@\s]+:)([^@\s]+)(@)"), r"\1" + _REDACTED + r"\3"),
)


def redact_sensitive_text(text: str) -> str:
    """Mask credentials in free text. Best-effort: it reduces the blast radius of an
    accidental ``logger.info(request_body)``; it does not make logging secrets safe."""
    if not text:
        return text
    for pattern, replacement in _REDACTION_RULES:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """logging.Filter that redacts the fully-formatted message of every record."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib signature
        try:
            message = record.getMessage()
        except Exception:  # a broken %-format must not lose the record
            return True
        redacted = redact_sensitive_text(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


# ---------------------------------------------------------------------------
# LLM prompt delimiters
# ---------------------------------------------------------------------------

_DELIMITER_RUN_RE = re.compile(r"(\^{3,}|v{3,}|={3,}|#{3,}|-{5,}|<{3,}|>{3,})", re.IGNORECASE)
_DELIMITER_WORDS_RE = re.compile(r"(?i)\b(END\s+UNTRUSTED\s+CONTENT|UNTRUSTED\s+CONTENT|END\s+TOOL\s+RESULT|TOOL\s+RESULT)\b")


def neutralize_prompt_delimiters(text: str) -> str:
    """Make untrusted text incapable of reproducing this codebase's own prompt delimiters
    (``vvv UNTRUSTED CONTENT ... vvv``, ``^^^ END UNTRUSTED CONTENT ^^^``,
    ``=== END TOOL RESULT ===``).

    Without this, a job description or resume containing the closing marker ends the
    "data only" block early and everything after it is read as trusted instructions.
    Runs of delimiter characters are shortened to two and the marker phrases get a zero-
    width-free visible rewrite, so the model still sees the text but it can no longer
    match a real boundary."""
    if not text:
        return text
    text = _DELIMITER_RUN_RE.sub(lambda m: m.group(0)[0] * 2, text)
    text = _DELIMITER_WORDS_RE.sub(lambda m: m.group(0).replace(" ", "_").lower(), text)
    return text


# ---------------------------------------------------------------------------
# HTTP headers
# ---------------------------------------------------------------------------

API_CSP = "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"


def api_security_headers(*, is_production: bool) -> Mapping[str, str]:
    """Headers for JSON/attachment API responses. A JSON API never needs to load
    scripts, styles or frames, so its CSP is 'none' — much stricter than the browser
    app's own policy (that one lives in frontend/next.config.ts)."""
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
        "Content-Security-Policy": API_CSP,
    }
    if is_production:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers
