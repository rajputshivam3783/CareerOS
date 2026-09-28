"""Generic JSON API collector — V19.2 JSON API source type.

A small but growing number of official/PSU sources expose a genuine
JSON endpoint (as opposed to an HTML page meant for browsers). This
adapter is source-agnostic, the same way RSSAdapter is for feeds:
point it at a URL and a dotted "list path" describing where the array
of postings lives in the response, plus a field-name mapping, and it
emits one JobRecord per item.

Like every other V2/V19.2 collector, this does NOT invent an endpoint
for a specific organization — an operator supplies a URL they've
confirmed is a real, current, unauthenticated JSON endpoint (see
app.ingestion.adapters.configured / SourceRegistry.config).
"""

import json
import logging

from app.ingestion.adapters.base import BaseJobAdapter
from app.ingestion.collectors.http_client import fetch_text
from app.ingestion.models.job_record import JobRecord

logger = logging.getLogger("careeros.ingestion.json_api")


def _dig(obj, dotted_path: str):
    """Walk a dotted path ('data.items') through nested dicts/lists.
    Empty path returns obj unchanged. Missing keys return None rather
    than raising, so one malformed record can't crash the whole run."""
    if not dotted_path:
        return obj
    current = obj
    for part in dotted_path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if 0 <= idx < len(current) else None
        else:
            return None
    return current


class JSONAPIAdapter(BaseJobAdapter):
    def __init__(
        self,
        source_name: str,
        endpoint_url: str,
        list_path: str = "",
        field_map: dict[str, str] | None = None,
        organization: str | None = None,
        govt_level: str | None = None,
        category: str | None = None,
        max_records: int = 100,
    ):
        self.source_name = source_name
        self.endpoint_url = endpoint_url
        self.list_path = list_path
        # Maps JobRecord field name -> key name within each item, e.g.
        # {"title": "postTitle", "official_url": "detailUrl"}. "title"
        # defaults to "title" and is the only required mapped field.
        self.field_map = field_map or {}
        self.organization = organization or source_name
        self.govt_level = govt_level
        self.category = category
        self.max_records = max_records

    def fetch(self) -> list[JobRecord]:
        raw = fetch_text(self.endpoint_url)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Could not parse JSON from %s", self.endpoint_url)
            return []

        items = _dig(data, self.list_path)
        if not isinstance(items, list):
            logger.warning(
                "list_path '%s' did not resolve to a list for %s — endpoint shape may have changed",
                self.list_path, self.endpoint_url,
            )
            return []

        title_key = self.field_map.get("title", "title")
        url_key = self.field_map.get("official_url", self.field_map.get("url", "url"))
        ref_key = self.field_map.get("source_reference", self.field_map.get("id", "id"))
        desc_key = self.field_map.get("description", "description")

        records: list[JobRecord] = []
        for item in items[: self.max_records]:
            if not isinstance(item, dict):
                continue
            title = item.get(title_key)
            if not title:
                continue
            url = item.get(url_key)
            records.append(
                JobRecord(
                    source_name=self.source_name,
                    source_reference=str(item.get(ref_key)) if item.get(ref_key) is not None else url or title,
                    official_url=url,
                    notification_url=url,
                    title=str(title)[:220],
                    organization=self.organization,
                    job_type="Government",
                    govt_level=self.govt_level,
                    category=self.category,
                    description=str(item.get(desc_key)) if item.get(desc_key) else "See official notification",
                )
            )
        return records
