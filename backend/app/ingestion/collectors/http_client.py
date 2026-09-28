import logging
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.core.config import settings

logger = logging.getLogger("careeros.ingestion.http")

_robots_cache: dict[str, RobotFileParser | None] = {}


def _robots_allows(url: str) -> bool:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    parser = _robots_cache.get(origin)

    if parser is None and origin not in _robots_cache:
        parser = RobotFileParser()
        parser.set_url(urljoin(origin, "/robots.txt"))

        try:
            parser.read()
        except Exception:
            logger.warning(
                "Could not read robots.txt for %s — proceeding cautiously",
                origin,
            )
            parser = None

        _robots_cache[origin] = parser

    if parser is None:
        return True

    return parser.can_fetch(
        settings.ingestion_user_agent,
        url,
    )


def fetch_bytes(
    url: str,
    max_bytes: int = 15_000_000,
    respect_robots: bool = True,
) -> bytes | None:

    if respect_robots and not _robots_allows(url):
        logger.info(
            "Skipping %s — disallowed by robots.txt",
            url,
        )
        return None

    headers = {
        "User-Agent": settings.ingestion_user_agent
    }

    try:
        response = httpx.get(
            url,
            headers=headers,
            timeout=settings.ingestion_request_timeout_seconds,
            follow_redirects=True,
        )

        response.raise_for_status()

        if len(response.content) > max_bytes:
            logger.warning(
                "Skipping %s — response exceeds %d bytes",
                url,
                max_bytes,
            )
            return None

        return response.content

    except Exception as exc:
        logger.warning(
            "Byte fetch failed for %s: %s",
            url,
            exc,
        )
        return None


def fetch_text(
    url: str,
    respect_robots: bool = True,
) -> str | None:

    if respect_robots and not _robots_allows(url):
        logger.info(
            "Skipping %s — disallowed by robots.txt",
            url,
        )
        return None

    headers = {
        "User-Agent": settings.ingestion_user_agent
    }

    try:
        response = httpx.get(
            url,
            headers=headers,
            timeout=settings.ingestion_request_timeout_seconds,
            follow_redirects=True,
        )

        response.raise_for_status()

        return response.text

    except Exception as exc:
        logger.warning(
            "Fetch failed for %s: %s",
            url,
            exc,
        )
        return None