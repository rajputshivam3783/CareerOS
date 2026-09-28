"""Generic HTML notification-list adapter.

Most Indian government recruitment sites (SSC, UPSC, RRB, and most state
PSCs) don't expose a feed or API — they publish an HTML page listing
notifications, each with a title and a link (often to a PDF). This
adapter is deliberately generic and *configured*, not hardcoded per
site: you give it CSS selectors describing "one row" and "the title/
link/date within a row", and it does the fetch + parse + map to
JobRecord.

Why configuration instead of a baked-in selector per official site:
government page markup changes without notice, and a wrong selector
fails differently depending on the site (empty results vs. wrong
data). Centralizing the *logic* here while keeping the *selectors* in
app/ingestion/sources.py means updating a source after a layout change
is a one-line config edit, not a code change — and it's honest about
the fact that nobody can guarantee today's selector still matches
tomorrow's page without checking.
"""

import logging
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.ingestion.adapters.base import BaseJobAdapter
from app.ingestion.collectors.http_client import fetch_text
from app.ingestion.models.job_record import JobRecord

logger = logging.getLogger("careeros.ingestion.html")


@dataclass
class HTMLListSelectors:
    """CSS selectors describing where to find each field on the
    listing page. ``title_selector``/``link_selector`` are relative to
    each element matched by ``row_selector``. Leave optional selectors
    as None if the listing page doesn't expose that field."""

    row_selector: str
    title_selector: str | None = None
    link_selector: str | None = None
    date_selector: str | None = None


class HTMLListAdapter(BaseJobAdapter):
    def __init__(
        self,
        source_name: str,
        listing_url: str,
        selectors: HTMLListSelectors,
        organization: str | None = None,
        job_type: str = "Government",
        govt_level: str | None = None,
        category: str | None = None,
        max_records: int = 50,
    ):
        self.source_name = source_name
        self.listing_url = listing_url
        self.selectors = selectors
        self.organization = organization or source_name
        self.job_type = job_type
        self.govt_level = govt_level
        self.category = category
        self.max_records = max_records

    def fetch(self) -> list[JobRecord]:
        html = fetch_text(self.listing_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select(self.selectors.row_selector)[: self.max_records]
        if not rows:
            logger.warning(
                "'%s' row_selector matched nothing on %s — the page layout may have "
                "changed; selectors in sources.py need re-validating.",
                self.source_name,
                self.listing_url,
            )

        records: list[JobRecord] = []
        for row in rows:
            title = self._extract_text(row, self.selectors.title_selector)
            link = self._extract_link(row, self.selectors.link_selector)
            date_text = self._extract_text(row, self.selectors.date_selector)

            if not title:
                continue

            records.append(
                JobRecord(
                    source_name=self.source_name,
                    source_reference=link or title,
                    official_url=self.listing_url,
                    notification_url=link,
                    title=title,
                    organization=self.organization,
                    job_type=self.job_type,
                    govt_level=self.govt_level,
                    category=self.category,
                    description=(
                        f"Notification dated {date_text}" if date_text else "See official notification"
                    ),
                )
            )

        return records

    def _extract_text(self, row, selector: str | None) -> str | None:
        if not selector:
            return row.get_text(strip=True) or None
        node = row.select_one(selector)
        return node.get_text(strip=True) if node else None

    def _extract_link(self, row, selector: str | None) -> str | None:
        node = row.select_one(selector) if selector else row.select_one("a")
        if not node or not node.get("href"):
            return None
        return urljoin(self.listing_url, node["href"])
