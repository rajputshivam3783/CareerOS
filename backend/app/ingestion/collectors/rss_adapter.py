"""Generic RSS/Atom adapter.

Many official sources (press-release feeds, some state portals, PIB,
etc.) publish a real RSS/Atom feed for notices. This adapter is
source-agnostic: point it at a feed URL and it emits one JobRecord per
entry. Uses the standard-library XML parser only, so there's no new
dependency to trust with untrusted remote XML.

This does NOT invent a feed for a specific department — an operator
must supply a feed URL they've confirmed is official and currently
live (see app/ingestion/sources.py).
"""

import logging
from xml.etree import ElementTree

from app.ingestion.adapters.base import BaseJobAdapter
from app.ingestion.collectors.http_client import fetch_text
from app.ingestion.models.job_record import JobRecord

logger = logging.getLogger("careeros.ingestion.rss")

_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class RSSAdapter(BaseJobAdapter):
    """Fetches an RSS 2.0 or Atom feed and maps each entry to a
    JobRecord. Fields not present in the feed fall back to JobRecord's
    own defaults (e.g. qualification="See official notification")."""

    def __init__(
        self,
        source_name: str,
        feed_url: str,
        organization: str | None = None,
        job_type: str = "Government",
        govt_level: str | None = None,
        category: str | None = None,
    ):
        self.source_name = source_name
        self.feed_url = feed_url
        self.organization = organization or source_name
        self.job_type = job_type
        self.govt_level = govt_level
        self.category = category

    def fetch(self) -> list[JobRecord]:
        xml_text = fetch_text(self.feed_url)
        if not xml_text:
            return []

        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            logger.warning("Could not parse feed XML from %s", self.feed_url)
            return []

        items = root.findall(".//item") or root.findall(f".//{_ATOM_NS}entry")
        records: list[JobRecord] = []

        for item in items:
            title = self._text(item, "title") or self._text(item, f"{_ATOM_NS}title")
            link = self._text(item, "link") or self._atom_link(item)
            description = (
                self._text(item, "description")
                or self._text(item, "summary")
                or self._text(item, f"{_ATOM_NS}summary")
            )
            if not title:
                continue

            records.append(
                JobRecord(
                    source_name=self.source_name,
                    source_reference=link or title,
                    official_url=link,
                    notification_url=link,
                    title=title,
                    organization=self.organization,
                    job_type=self.job_type,
                    govt_level=self.govt_level,
                    category=self.category,
                    description=description or "See official notification",
                )
            )

        return records

    @staticmethod
    def _text(item: ElementTree.Element, tag: str) -> str | None:
        node = item.find(tag)
        if node is None or node.text is None:
            return None
        return node.text.strip() or None

    @staticmethod
    def _atom_link(item: ElementTree.Element) -> str | None:
        node = item.find(f"{_ATOM_NS}link")
        if node is None:
            return None
        return node.get("href")
