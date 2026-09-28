"""Centralized logging setup.

Kept deliberately simple (stdlib only) so it works the same in local
SQLite mode and in a container, without adding a new dependency.
"""

import logging
import sys

from app.core.config import settings
from app.core.hardening import RedactingFilter


def configure_logging() -> None:
    """Configure root logging once, at process startup."""
    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g. re-imported under pytest) — skip.
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    # V25.6: mask bearer tokens, passwords, OTPs, API keys and URL credentials that end up
    # in a log message by accident. Best-effort; never log secrets on purpose.
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # Quiet noisy third-party loggers unless we're actively debugging.
    if settings.log_level.upper() != "DEBUG":
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
