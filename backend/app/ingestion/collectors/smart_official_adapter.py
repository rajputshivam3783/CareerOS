"""Resilient official-site notice collector.

Scans official HTML links rather than depending on brittle table selectors.
Only recruitment/exam lifecycle titles are accepted; every record still enters
CareerOS admin review and is never auto-published.
"""

import hashlib
import logging
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from app.ingestion.adapters.base import BaseJobAdapter
from app.ingestion.collectors.http_client import fetch_text
from app.ingestion.models.job_record import JobRecord

log = logging.getLogger("careeros.ingestion.official")

POSITIVE = re.compile(
    r"\b(recruit|vacanc|employment|examination|exam|notification|advertisement|apply|application|result|admit|answer key|score.?card|merit|allotment|shortlist|interview|document verification|syllabus|calendar|corrigendum|notice|apprentice|officer|assistant|engineer|constable|technician|graduate|clerk|po/mt|specialist)\b",
    re.I,
)
NEGATIVE = re.compile(
    r"\b(tender|procurement|auction|holiday|press release|privacy|copyright|contact us|about us)\b", re.I
)


class SmartOfficialAdapter(BaseJobAdapter):
    def __init__(
        self, source_name, listing_url, organization=None, govt_level="Central", category=None, max_records=100
    ):
        self.source_name = source_name
        self.listing_url = listing_url
        self.organization = organization or source_name
        self.govt_level = govt_level
        self.category = category
        self.max_records = max_records

    def fetch(self):
        html = fetch_text(self.listing_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        seen = set()
        out = []
        for a in soup.select("a[href]"):
            title = " ".join(a.stripped_strings).strip()
            if len(title) < 8 or NEGATIVE.search(title) or not POSITIVE.search(title):
                continue
            url = urljoin(self.listing_url, a.get("href"))
            if urlparse(url).scheme not in {"http", "https"}:
                continue
            # Links may legitimately move to a commission-owned application subdomain.
            key = (re.sub(r"\s+", " ", title.lower()), url)
            if key in seen:
                continue
            seen.add(key)
            ref = hashlib.sha256((self.source_name + "|" + url + "|" + title).encode()).hexdigest()[:24]
            out.append(
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
                    location="India",
                    qualification="See official notification",
                    description="Discovered from the official source. Verify dates, eligibility and application details in the linked official notice.",
                )
            )
            if len(out) >= self.max_records:
                break
        if not out:
            log.warning(
                "No recruitment links discovered at %s; source markup/content may have changed", self.listing_url
            )
        return out
