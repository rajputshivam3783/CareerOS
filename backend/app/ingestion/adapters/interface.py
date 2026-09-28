"""V19.2 — Official Source Adapter Framework: the plugin interface.

Every organization-specific integration is an instance that satisfies
``SourceAdapter``. This is deliberately an *extension* of the existing
V2 ``BaseJobAdapter`` (app.ingestion.adapters.base) — ``fetch()`` keeps
its exact V2 signature and every adapter written for V2-V19.1
(UPSCAdapter, SSCAdapter, RRBAdapter, GenericMetadataAdapter, the V2
collectors) is automatically already a valid, if minimal, SourceAdapter
via the default method bodies below. Nothing about V2/V19.1 ingestion
changes; this only adds the extra lifecycle hooks an enterprise
plugin framework needs on top.

Required methods (per the V19.2 spec):
    metadata()    -> static description of the adapter (name, org,
                     collector type, source type) for the admin UI.
    validate()    -> cheap, no-network sanity check that the adapter
                     is configured correctly (e.g. a URL is present
                     and well-formed) before it's ever scheduled.
    fetch()       -> unchanged V2 contract: hit the source, return
                     JobRecord objects. May raise; callers (the
                     orchestrator) are responsible for retry/backoff/
                     circuit-breaking, not the adapter itself.
    normalize()   -> map raw fetch() output through the existing V2
                     normalize_job() pipeline. Adapters needing
                     source-specific normalization can override this;
                     the default is intentionally the same function
                     the V2 pipeline has always used, so behavior for
                     every pre-V19.2 adapter is unchanged.
    deduplicate() -> filter out records that already exist, reusing
                     the existing V2 is_duplicate() check. Returns the
                     subset of records that are new-or-changed.
    save()        -> persist via the existing V2 publish_to_review()
                     pipeline (never auto-publishes — everything still
                     lands in the review queue, unchanged since V2).
    health()      -> a point-in-time health snapshot for this source,
                     read from SourceRegistry (see
                     app.ingestion.services.health).

None of these defaults touch Authentication, ATS, ingest.py's
run_ingestion()/run_all_enabled_sources(), or any existing adapter's
behavior — they're additive convenience methods layered on top.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.ingestion.adapters.base import BaseJobAdapter
from app.ingestion.models.job_record import JobRecord


@dataclass(frozen=True)
class AdapterMetadata:
    """Static description of an adapter, for the admin UI and API —
    never persisted directly (SourceRegistry is the persisted catalog;
    this is just what an adapter *reports about itself* at runtime)."""

    source_name: str
    organization: str
    source_type: str  # html | rss | xml | json_api | pdf_metadata | sitemap | browser_automation
    govt_level: str | None = None
    category: str | None = None
    official_url: str | None = None
    notes: str = ""
    supported_change_types: list[str] = field(default_factory=list)


class SourceAdapter(BaseJobAdapter, ABC):
    """Base class for every V19.2 organization adapter.

    Subclasses MUST implement ``fetch()`` (inherited requirement from
    BaseJobAdapter) and SHOULD implement ``metadata()``. Every other
    method has a working default built from existing V2/V19.1
    services, so a minimal adapter only needs to supply fetch() +
    metadata() to be fully usable by the scheduler, admin API, and
    health/change-detection pipeline.
    """

    # --- required identity -------------------------------------------------

    @abstractmethod
    def metadata(self) -> AdapterMetadata:
        """Return this adapter's static description."""
        raise NotImplementedError

    # --- lifecycle hooks with sensible, additive defaults -------------------

    def validate(self) -> tuple[bool, str | None]:
        """Cheap, no-network configuration check. Returns
        (is_valid, reason_if_invalid). Default: if metadata() reports
        an official_url, require it to be a well-formed http(s) URL;
        adapters with no fixed URL (e.g. a partner-submission feed)
        pass trivially."""
        meta = self.metadata()
        if not meta.official_url:
            return True, None
        parsed = urlparse(meta.official_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False, f"official_url '{meta.official_url}' is not a valid http(s) URL"
        return True, None

    @abstractmethod
    def fetch(self) -> list[JobRecord]:
        """Unchanged V2 contract — hit the source, return JobRecords."""
        raise NotImplementedError

    def normalize(self, records: list[JobRecord]) -> list[JobRecord]:
        """Default: run every record through the existing V2
        normalize_job(). Override only if a source needs bespoke
        cleanup beyond the shared normalizer."""
        from app.ingestion.services.normalize import normalize_job

        return [normalize_job(r) for r in records]

    def deduplicate(self, db, records: list[JobRecord]) -> list[JobRecord]:
        """Default: reuse the existing V2 is_duplicate() check to
        drop records that already exist. Returns only new-or-changed
        records; does not write anything."""
        from app.ingestion.services.deduplicate import is_duplicate

        return [r for r in records if not is_duplicate(db, r)]

    def save(self, db, records: list[JobRecord]) -> list:
        """Default: persist via the existing V2 publish_to_review()
        pipeline — still review-queue-only, never auto-published."""
        from app.ingestion.services.publisher import publish_to_review

        saved = []
        for record in records:
            created, job = publish_to_review(db=db, record=record)
            if created and job is not None:
                saved.append(job)
        return saved

    def health(self, db):
        """Default: read this adapter's row from SourceRegistry (see
        app.ingestion.services.health.get_health)."""
        from app.ingestion.services.health import get_health

        return get_health(db, self.source_name)
