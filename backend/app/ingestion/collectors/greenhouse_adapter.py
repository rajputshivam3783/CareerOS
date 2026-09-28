"""Greenhouse Job Board API adapter.

Greenhouse's job-board API (`boards-api.greenhouse.io`) is a public,
documented, unauthenticated endpoint that companies using Greenhouse
explicitly expose so their open roles can be read by career sites and
aggregators — this is not scraping a page against its owner's wishes,
it's consuming an API built for exactly this purpose.

Reference: https://developers.greenhouse.io/job-board.html

Usage: point this at a company's own board token (visible in their
public careers page URL, e.g. boards.greenhouse.io/<token>).
"""

import logging

import httpx

from app.core.config import settings
from app.ingestion.adapters.base import BaseJobAdapter
from app.ingestion.models.job_record import JobRecord

logger = logging.getLogger("careeros.ingestion.greenhouse")


class GreenhouseAdapter(BaseJobAdapter):
    def __init__(self, board_token: str, organization: str | None = None, job_type: str = "Private"):
        self.board_token = board_token
        self.source_name = f"Greenhouse: {board_token}"
        self.organization = organization or board_token
        self.job_type = job_type

    def fetch(self) -> list[JobRecord]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.board_token}/jobs?content=true"
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": settings.ingestion_user_agent},
                timeout=settings.ingestion_request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning("Greenhouse fetch failed for board '%s': %s", self.board_token, exc)
            return []

        records: list[JobRecord] = []
        for item in payload.get("jobs", []):
            location = (item.get("location") or {}).get("name") or "India"
            records.append(
                JobRecord(
                    source_name=self.source_name,
                    source_reference=str(item.get("id")),
                    official_url=item.get("absolute_url"),
                    apply_url=item.get("absolute_url"),
                    title=item.get("title", "Untitled role"),
                    organization=self.organization,
                    job_type=self.job_type,
                    location=location,
                    qualification="See job description",
                    description=_strip_html(item.get("content")) or "See job description",
                )
            )
        return records


def _strip_html(html: str | None) -> str | None:
    """Greenhouse returns the description as HTML; strip tags for a
    plain-text summary rather than storing raw markup."""
    if not html:
        return None
    from bs4 import BeautifulSoup

    text = BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    return text[:4000] if text else None
