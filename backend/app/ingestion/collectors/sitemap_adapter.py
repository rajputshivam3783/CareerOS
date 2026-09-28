"""Sitemap collector — V19.2 sitemap source type.

Some official sites don't publish a notices feed at all, but do
publish a standard sitemap.xml that includes recruitment-notice pages
as their own URLs (e.g. .../recruitment/advt-2026-03). This adapter
parses a sitemap (or a sitemap index, one level deep) and keeps URLs
whose path matches a configured substring/pattern, deriving a
best-effort title from the URL slug. It's intentionally the lowest-
fidelity collector in the framework — a starting point for discovery,
not a substitute for a real feed/HTML/JSON source when one exists.
"""

import logging
import re
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree

from app.ingestion.adapters.base import BaseJobAdapter
from app.ingestion.collectors.http_client import fetch_text
from app.ingestion.models.job_record import JobRecord

logger = logging.getLogger("careeros.ingestion.sitemap")

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def _slug_to_title(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    slug = unquote(path.rsplit("/", 1)[-1])
    slug = re.sub(r"\.(html?|php|aspx?)$", "", slug, flags=re.I)
    slug = re.sub(r"[-_]+", " ", slug).strip()
    return slug.title() if slug else url


class SitemapAdapter(BaseJobAdapter):
    def __init__(
        self,
        source_name: str,
        sitemap_url: str,
        url_contains: str,
        organization: str | None = None,
        govt_level: str | None = None,
        category: str | None = None,
        max_records: int = 100,
    ):
        self.source_name = source_name
        self.sitemap_url = sitemap_url
        self.url_contains = url_contains.lower()
        self.organization = organization or source_name
        self.govt_level = govt_level
        self.category = category
        self.max_records = max_records

    def _urls_from(self, xml_text: str) -> tuple[list[str], list[str]]:
        """Returns (page_urls, nested_sitemap_urls)."""
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            return [], []
        locs = [loc.text.strip() for loc in root.findall(f".//{_SITEMAP_NS}loc") if loc.text]
        if root.tag.endswith("sitemapindex"):
            return [], locs
        return locs, []

    def fetch(self) -> list[JobRecord]:
        top_xml = fetch_text(self.sitemap_url)
        if not top_xml:
            return []

        page_urls, nested = self._urls_from(top_xml)
        # A sitemap index — descend exactly one level so this stays a
        # bounded number of requests rather than crawling recursively.
        for nested_url in nested[:5]:
            nested_xml = fetch_text(nested_url)
            if nested_xml:
                more_pages, _ = self._urls_from(nested_xml)
                page_urls.extend(more_pages)

        matched = [u for u in page_urls if self.url_contains in u.lower()]
        if not matched:
            logger.warning(
                "No sitemap URLs matched '%s' in %s — pattern or sitemap structure may have changed",
                self.url_contains, self.sitemap_url,
            )

        records: list[JobRecord] = []
        for url in matched[: self.max_records]:
            records.append(
                JobRecord(
                    source_name=self.source_name,
                    source_reference=url,
                    official_url=url,
                    notification_url=url,
                    title=_slug_to_title(url)[:220],
                    organization=self.organization,
                    job_type="Government",
                    govt_level=self.govt_level,
                    category=self.category,
                    description="Discovered via sitemap. Verify dates, eligibility and application details on the linked page.",
                )
            )
        return records
