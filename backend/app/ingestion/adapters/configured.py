"""V19.2 — the adapter plugin factory.

This is the core of "every organization has its own adapter, no
monolithic scraper": rather than one Python class per organization
(which is what a monolithic-scraper anti-pattern actually looks like
at 300+ organizations), each organization is a *row* in
``source_registry`` — name, official_url, collector_type, and a small
JSON ``config`` blob — and ``ConfiguredSourceAdapter`` turns that row
into an isolated, independently runnable ``SourceAdapter`` instance by
delegating to the right collector class from
``app.ingestion.collectors``. Adding organization #301 is a database
row (via the existing V19.1 ``POST /government/sources`` endpoint or
the admin dashboard), never a code change — which is also what makes
per-organization enable/disable, health tracking, and scheduling work
uniformly across every organization without an if/elif ladder.

``config`` shapes by collector_type (all keys optional unless noted):

    official_html  {}                                             (SmartOfficialAdapter)
    html_list      {"row_selector": "...", "title_selector": "...",
                     "link_selector": "...", "date_selector": "..."} (row_selector required)
    rss            {}                                              (RSSAdapter)
    xml            {"item_path": "...", "title_tag": "...",
                     "link_tag": "...", "link_attr": "...",
                     "description_tag": "..."}
    json_api       {"list_path": "...", "field_map": {...}}
    pdf_metadata   {"max_pdf_downloads": 10}                       (PDFMetadataAdapter)
    sitemap        {"url_contains": "..."}                        (url_contains required)

A malformed/incompatible config raises ValueError from validate(),
not from fetch() — so a bad config is caught before it's ever
scheduled, not mid-run.
"""

from __future__ import annotations

import json

from app.ingestion.adapters.interface import AdapterMetadata, SourceAdapter
from app.ingestion.collectors.html_list_adapter import HTMLListAdapter, HTMLListSelectors
from app.ingestion.collectors.json_api_adapter import JSONAPIAdapter
from app.ingestion.collectors.pdf_metadata_adapter import PDFMetadataAdapter
from app.ingestion.collectors.rss_adapter import RSSAdapter
from app.ingestion.collectors.sitemap_adapter import SitemapAdapter
from app.ingestion.collectors.smart_official_adapter import SmartOfficialAdapter
from app.ingestion.collectors.xml_feed_adapter import XMLFeedAdapter
from app.ingestion.models.job_record import JobRecord


class ConfiguredSourceAdapter(SourceAdapter):
    """Wraps one ``SourceRegistry`` row as a runnable SourceAdapter."""

    def __init__(
        self,
        source_name: str,
        official_url: str | None,
        collector_type: str,
        organization: str | None = None,
        govt_level: str | None = None,
        category: str | None = None,
        config: dict | str | None = None,
    ):
        self.source_name = source_name
        self.official_url = official_url
        self.collector_type = collector_type
        self.organization = organization or source_name
        self.govt_level = govt_level
        self.category = category
        if isinstance(config, str):
            try:
                config = json.loads(config) if config else {}
            except json.JSONDecodeError:
                config = {}
        self.config: dict = config or {}

    @classmethod
    def from_registry_row(cls, row) -> "ConfiguredSourceAdapter":
        """Build from a SourceRegistry ORM row."""
        return cls(
            source_name=row.source_name,
            official_url=row.official_url,
            collector_type=row.collector_type,
            organization=getattr(row, "organization", None),
            govt_level=getattr(row, "govt_level", None),
            category=getattr(row, "category", None),
            config=getattr(row, "config", None),
        )

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            source_name=self.source_name,
            organization=self.organization,
            source_type=self.collector_type,
            govt_level=self.govt_level,
            category=self.category,
            official_url=self.official_url,
            supported_change_types=[
                "new_recruitment", "updated_recruitment", "cancelled_recruitment",
                "deadline_extended", "result_published", "admit_card_published",
                "answer_key_published",
            ],
        )

    def validate(self) -> tuple[bool, str | None]:
        ok, reason = super().validate()
        if not ok:
            return ok, reason
        if self.collector_type == "html_list" and not self.config.get("row_selector"):
            return False, "html_list adapters require config.row_selector"
        if self.collector_type == "sitemap" and not self.config.get("url_contains"):
            return False, "sitemap adapters require config.url_contains"
        if self.collector_type in {"selenium", "playwright"}:
            return False, f"'{self.collector_type}' is a registry-only placeholder — no collector is implemented yet"
        if not self.official_url and self.collector_type != "json_api":
            return False, "official_url is required for this collector_type"
        if self.collector_type == "json_api" and not self.official_url:
            return False, "official_url (the JSON endpoint) is required"
        return True, None

    def _build_collector(self):
        c = self.collector_type
        cfg = self.config
        common = dict(organization=self.organization, govt_level=self.govt_level, category=self.category)

        if c == "official_html":
            return SmartOfficialAdapter(self.source_name, self.official_url, **common)
        if c == "html_list":
            selectors = HTMLListSelectors(
                row_selector=cfg["row_selector"],
                title_selector=cfg.get("title_selector"),
                link_selector=cfg.get("link_selector"),
                date_selector=cfg.get("date_selector"),
            )
            return HTMLListAdapter(self.source_name, self.official_url, selectors, **common)
        if c == "rss":
            return RSSAdapter(self.source_name, self.official_url, **common)
        if c == "xml":
            return XMLFeedAdapter(
                self.source_name, self.official_url,
                item_path=cfg.get("item_path", ".//item"),
                title_tag=cfg.get("title_tag", "title"),
                link_tag=cfg.get("link_tag", "link"),
                link_attr=cfg.get("link_attr"),
                description_tag=cfg.get("description_tag", "description"),
                **common,
            )
        if c == "json_api":
            return JSONAPIAdapter(
                self.source_name, self.official_url,
                list_path=cfg.get("list_path", ""),
                field_map=cfg.get("field_map"),
                **common,
            )
        if c == "pdf_metadata":
            return PDFMetadataAdapter(
                self.source_name, self.official_url,
                max_pdf_downloads=cfg.get("max_pdf_downloads", 10),
                **common,
            )
        if c == "sitemap":
            return SitemapAdapter(self.source_name, self.official_url, cfg["url_contains"], **common)
        raise ValueError(f"Unsupported collector_type '{c}'")

    def fetch(self) -> list[JobRecord]:
        ok, reason = self.validate()
        if not ok:
            raise ValueError(f"Adapter '{self.source_name}' is not runnable: {reason}")
        return self._build_collector().fetch()
