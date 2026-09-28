"""Generic XML collector — V19.2 XML source type.

For official sources that publish structured XML that isn't RSS/Atom
(e.g. a custom notices.xml). Unlike RSSAdapter (which assumes
<item>/<entry> with title/link/description), this adapter is
configured with an explicit item path and per-field tag names, using
only the standard-library XML parser (no new dependency to trust with
untrusted remote XML).
"""

import logging
from xml.etree import ElementTree

from app.ingestion.adapters.base import BaseJobAdapter
from app.ingestion.collectors.http_client import fetch_text
from app.ingestion.models.job_record import JobRecord

logger = logging.getLogger("careeros.ingestion.xml")


class XMLFeedAdapter(BaseJobAdapter):
    def __init__(
        self,
        source_name: str,
        feed_url: str,
        item_path: str = ".//item",
        title_tag: str = "title",
        link_tag: str = "link",
        link_attr: str | None = None,  # e.g. "href" if the link is an attribute, not text
        description_tag: str | None = "description",
        organization: str | None = None,
        govt_level: str | None = None,
        category: str | None = None,
        max_records: int = 100,
    ):
        self.source_name = source_name
        self.feed_url = feed_url
        self.item_path = item_path
        self.title_tag = title_tag
        self.link_tag = link_tag
        self.link_attr = link_attr
        self.description_tag = description_tag
        self.organization = organization or source_name
        self.govt_level = govt_level
        self.category = category
        self.max_records = max_records

    def fetch(self) -> list[JobRecord]:
        xml_text = fetch_text(self.feed_url)
        if not xml_text:
            return []
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            logger.warning("Could not parse XML from %s", self.feed_url)
            return []

        items = root.findall(self.item_path)
        if not items:
            logger.warning(
                "item_path '%s' matched nothing in %s — feed shape may have changed",
                self.item_path, self.feed_url,
            )

        records: list[JobRecord] = []
        for item in items[: self.max_records]:
            title_node = item.find(self.title_tag)
            title = (title_node.text or "").strip() if title_node is not None else None
            if not title:
                continue

            link_node = item.find(self.link_tag)
            link = None
            if link_node is not None:
                link = link_node.get(self.link_attr) if self.link_attr else (link_node.text or "").strip()

            description = None
            if self.description_tag:
                desc_node = item.find(self.description_tag)
                description = (desc_node.text or "").strip() if desc_node is not None else None

            records.append(
                JobRecord(
                    source_name=self.source_name,
                    source_reference=link or title,
                    official_url=link,
                    notification_url=link,
                    title=title[:220],
                    organization=self.organization,
                    job_type="Government",
                    govt_level=self.govt_level,
                    category=self.category,
                    description=description or "See official notification",
                )
            )
        return records
