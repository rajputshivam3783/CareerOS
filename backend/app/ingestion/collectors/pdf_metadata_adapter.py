"""PDF-metadata collector — V19.2 PDF Metadata source type.

Many official notice boards are literally a page of links to PDF
notifications, with no feed. This adapter scans a listing page for
links ending in .pdf (reusing the same recruitment-keyword filter as
SmartOfficialAdapter, so it doesn't pick up tenders/holiday-lists/etc.)
and, best-effort, downloads each PDF and runs the existing V5
heuristic extractor (app.ingestion.services.pdf_parser) to fill in
qualification/age_limit/vacancies/fee/deadline/exam_date where the
text extraction succeeds. Every extracted field is exactly as
confident as pdf_parser already documents itself to be — nothing here
is auto-published, it all still flows through the standard review
queue.

PDF downloads are capped (``max_pdf_downloads``) so a listing page
with a hundred links doesn't turn one scheduled run into a hundred
multi-megabyte downloads; the remaining links still get a record
using the link text as the title.
"""

import hashlib
import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.ingestion.adapters.base import BaseJobAdapter
from app.ingestion.collectors.http_client import fetch_bytes, fetch_text
from app.ingestion.models.job_record import JobRecord
from app.ingestion.services.pdf_parser import parse_notification_fields

logger = logging.getLogger("careeros.ingestion.pdf_metadata")

POSITIVE = re.compile(
    r"\b(recruit|vacanc|employment|examination|exam|notification|advertisement|apply|"
    r"application|result|admit|answer key|score.?card|merit|corrigendum|notice)\b", re.I,
)
NEGATIVE = re.compile(r"\b(tender|procurement|auction|holiday|press release|privacy)\b", re.I)


class PDFMetadataAdapter(BaseJobAdapter):
    def __init__(
        self,
        source_name: str,
        listing_url: str,
        organization: str | None = None,
        govt_level: str | None = None,
        category: str | None = None,
        max_records: int = 60,
        max_pdf_downloads: int = 10,
    ):
        self.source_name = source_name
        self.listing_url = listing_url
        self.organization = organization or source_name
        self.govt_level = govt_level
        self.category = category
        self.max_records = max_records
        self.max_pdf_downloads = max_pdf_downloads

    def fetch(self) -> list[JobRecord]:
        html = fetch_text(self.listing_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        records: list[JobRecord] = []
        downloads_used = 0

        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not href.lower().split("?")[0].endswith(".pdf"):
                continue
            title = " ".join(a.stripped_strings).strip()
            if len(title) < 6 or NEGATIVE.search(title) or not POSITIVE.search(title):
                continue
            url = urljoin(self.listing_url, href)
            if urlparse(url).scheme not in {"http", "https"} or url in seen:
                continue
            seen.add(url)

            extra: dict = {}
            if downloads_used < self.max_pdf_downloads:
                pdf_bytes = fetch_bytes(url)
                downloads_used += 1
                if pdf_bytes:
                    fields = parse_notification_fields(pdf_bytes)
                    extra = {
                        "qualification": fields.get("qualification"),
                        "age_limit": fields.get("age_limit"),
                        "vacancies": fields.get("vacancies"),
                        "application_fee": fields.get("application_fee"),
                        "deadline": fields.get("deadline"),
                        "exam_date": fields.get("exam_date"),
                    }

            ref = hashlib.sha256((self.source_name + "|" + url).encode()).hexdigest()[:24]
            records.append(
                JobRecord(
                    source_name=self.source_name,
                    source_reference=ref,
                    official_url=self.listing_url,
                    notification_url=url,
                    title=title[:220],
                    organization=self.organization,
                    job_type="Government",
                    govt_level=self.govt_level,
                    category=self.category,
                    qualification=extra.get("qualification") or "See official notification",
                    age_limit=extra.get("age_limit"),
                    vacancies=extra.get("vacancies"),
                    application_fee=extra.get("application_fee"),
                    deadline=extra.get("deadline"),
                    exam_date=extra.get("exam_date"),
                    description=(
                        "Extracted from the linked PDF notification — verify every field against "
                        "the source document before publishing."
                        if extra else "See official PDF notification."
                    ),
                )
            )
            if len(records) >= self.max_records:
                break

        if not records:
            logger.warning("No PDF notices discovered at %s — page markup may have changed", self.listing_url)
        return records
