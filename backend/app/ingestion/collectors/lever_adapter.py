"""Lever public Postings API adapter.

Lever's postings API (`api.lever.co/v0/postings/<site>`) is a public,
documented, unauthenticated endpoint companies using Lever expose so
their open roles can be read externally — the same "built to be
consumed" category as Greenhouse's board API.

Reference: https://github.com/lever/postings-api

Usage: point this at a company's own Lever site slug (visible in
their public careers page URL, e.g. jobs.lever.co/<slug>).
"""

import logging

import httpx

from app.core.config import settings
from app.ingestion.adapters.base import BaseJobAdapter
from app.ingestion.models.job_record import JobRecord

logger = logging.getLogger("careeros.ingestion.lever")


class LeverAdapter(BaseJobAdapter):
    def __init__(self, site_slug: str, organization: str | None = None, job_type: str = "Private"):
        self.site_slug = site_slug
        self.source_name = f"Lever: {site_slug}"
        self.organization = organization or site_slug
        self.job_type = job_type

    def fetch(self) -> list[JobRecord]:
        url = f"https://api.lever.co/v0/postings/{self.site_slug}?mode=json"
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": settings.ingestion_user_agent},
                timeout=settings.ingestion_request_timeout_seconds,
            )
            response.raise_for_status()
            postings = response.json()
        except Exception as exc:
            logger.warning("Lever fetch failed for site '%s': %s", self.site_slug, exc)
            return []

        records: list[JobRecord] = []
        for item in postings:
            categories = item.get("categories") or {}
            records.append(
                JobRecord(
                    source_name=self.source_name,
                    source_reference=item.get("id"),
                    official_url=item.get("hostedUrl"),
                    apply_url=item.get("applyUrl") or item.get("hostedUrl"),
                    title=item.get("text", "Untitled role"),
                    organization=self.organization,
                    job_type=self.job_type,
                    category=categories.get("team"),
                    employment_type=categories.get("commitment"),
                    location=categories.get("location") or "India",
                    qualification="See job description",
                    description=(item.get("descriptionPlain") or item.get("description") or "See job description")[
                        :4000
                    ],
                )
            )
        return records
