"""V19.2 — Official Source Adapter Framework.

Self-contained (own sqlite file, shared X-Admin-Key), same pattern as
test_v19_1_government_core.py — doesn't modify or depend on that
file. Network-touching adapter fetch() calls are stubbed with
monkeypatch rather than hitting real government sites, exactly like a
CI environment with no outbound network would need.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v19_2.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from datetime import datetime, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.ingestion.adapters.configured import ConfiguredSourceAdapter  # noqa: E402
from app.ingestion.adapters.interface import AdapterMetadata, SourceAdapter  # noqa: E402
from app.ingestion.models.job_record import JobRecord  # noqa: E402
from app.ingestion.services import health as health_service  # noqa: E402
from app.ingestion.services.change_detection import apply_change, detect_change  # noqa: E402
from app.ingestion.services.errors import circuit_is_open, record_circuit_result, retry_with_backoff  # noqa: E402
from app.ingestion.orchestrator import run_source  # noqa: E402
from app.ingestion.scheduler import due_sources, is_due  # noqa: E402
from app.models.domain import IngestionRun, SourceRegistry  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}


def _make_record(suffix: str, **extra) -> JobRecord:
    return JobRecord(
        source_name=f"Test Source {suffix}",
        source_reference=f"ref-{suffix}",
        title=f"Test Recruitment {suffix}",
        organization="Test Commission",
        job_type="Government",
        **extra,
    )


# --- SourceAdapter interface -------------------------------------------------

class _StubAdapter(SourceAdapter):
    """A minimal adapter — only fetch() and metadata() supplied — to
    prove the default normalize/deduplicate/save/health/validate
    methods work without any adapter-specific override."""

    source_name = "Stub Org"

    def __init__(self, records):
        self._records = records

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            source_name=self.source_name, organization="Stub Org",
            source_type="official_html", official_url="https://stub.example.gov.in",
        )

    def fetch(self):
        return self._records


def test_minimal_adapter_gets_full_lifecycle_for_free():
    adapter = _StubAdapter([_make_record("stub-1")])
    ok, reason = adapter.validate()
    assert ok and reason is None

    fetched = adapter.fetch()
    normalized = adapter.normalize(fetched)
    assert len(normalized) == 1

    with TestClient(app):
        db = SessionLocal()
        try:
            fresh = adapter.deduplicate(db, normalized)
            assert len(fresh) == 1
            saved = adapter.save(db, fresh)
            assert len(saved) == 1
            # Second pass: same record is now a duplicate.
            assert adapter.deduplicate(db, normalized) == []
        finally:
            db.close()


def test_validate_rejects_malformed_official_url():
    class BadURLAdapter(_StubAdapter):
        def metadata(self):
            return AdapterMetadata(source_name="Bad", organization="Bad", source_type="official_html",
                                    official_url="not-a-url")

    ok, reason = BadURLAdapter([]).validate()
    assert not ok and "not a valid" in reason


# --- ConfiguredSourceAdapter (the plugin factory) ----------------------------

def test_configured_adapter_validate_requires_row_selector_for_html_list():
    adapter = ConfiguredSourceAdapter(
        source_name="X", official_url="https://example.gov.in", collector_type="html_list", config={},
    )
    ok, reason = adapter.validate()
    assert not ok and "row_selector" in reason


def test_configured_adapter_validate_requires_url_contains_for_sitemap():
    adapter = ConfiguredSourceAdapter(
        source_name="X", official_url="https://example.gov.in/sitemap.xml", collector_type="sitemap", config={},
    )
    ok, reason = adapter.validate()
    assert not ok and "url_contains" in reason


def test_configured_adapter_rejects_placeholder_collector_types():
    for placeholder in ("selenium", "playwright"):
        adapter = ConfiguredSourceAdapter(
            source_name="X", official_url="https://example.gov.in", collector_type=placeholder,
        )
        ok, reason = adapter.validate()
        assert not ok and "registry-only placeholder" in reason


def test_configured_adapter_valid_official_html():
    adapter = ConfiguredSourceAdapter(
        source_name="UPSC Test", official_url="https://upsc.gov.in", collector_type="official_html",
    )
    ok, reason = adapter.validate()
    assert ok and reason is None
    assert adapter.metadata().source_type == "official_html"


def test_configured_adapter_config_from_json_string():
    adapter = ConfiguredSourceAdapter(
        source_name="X", official_url="https://example.gov.in", collector_type="sitemap",
        config='{"url_contains": "recruitment"}',
    )
    ok, reason = adapter.validate()
    assert ok and reason is None


# --- Change detection ---------------------------------------------------------

def test_change_detection_new_recruitment_then_result_published():
    with TestClient(app):
        db = SessionLocal()
        try:
            from app.ingestion.services.normalize import normalize_job
            from app.ingestion.services.publisher import publish_to_review

            base = _make_record("cd-1", official_url="https://example.gov.in/cd-1")
            result = detect_change(db, base)
            assert result.change_type == "new_recruitment"

            created, job = publish_to_review(db=db, record=normalize_job(base))
            assert created and job is not None

            updated = _make_record(
                "cd-1", official_url="https://example.gov.in/cd-1",
                result_url="https://example.gov.in/cd-1/result",
            )
            change = detect_change(db, updated)
            assert change.change_type == "result_published"
            update_row = apply_change(db, change)
            assert update_row is not None
            assert update_row.update_type == "result"
            assert update_row.job_id == job.id
        finally:
            db.close()


def test_change_detection_cancelled_recruitment():
    with TestClient(app):
        db = SessionLocal()
        try:
            from app.ingestion.services.normalize import normalize_job
            from app.ingestion.services.publisher import publish_to_review

            base = _make_record("cd-2", official_url="https://example.gov.in/cd-2")
            publish_to_review(db=db, record=normalize_job(base))

            cancelled = _make_record(
                "cd-2 - RECRUITMENT CANCELLED", official_url="https://example.gov.in/cd-2",
            )
            change = detect_change(db, cancelled)
            assert change.change_type == "cancelled_recruitment"
        finally:
            db.close()


def test_change_detection_no_change_is_a_noop():
    with TestClient(app):
        db = SessionLocal()
        try:
            result = detect_change(db, _make_record("cd-new-only"))
            assert apply_change(db, result) is None
        finally:
            db.close()


# --- Health + circuit breaker + retry ------------------------------------------

def test_retry_with_backoff_succeeds_on_third_attempt():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("temporary failure")
        return "ok"

    result, exc, attempts = retry_with_backoff(flaky, max_attempts=3, base_delay_seconds=0, sleep=lambda s: None)
    assert result == "ok" and exc is None and attempts == 3


def test_retry_with_backoff_exhausts_and_returns_exception():
    def always_fails():
        raise RuntimeError("nope")

    result, exc, attempts = retry_with_backoff(always_fails, max_attempts=2, base_delay_seconds=0, sleep=lambda s: None)
    assert result is None and isinstance(exc, RuntimeError) and attempts == 2


def test_circuit_breaker_opens_after_threshold_and_closes_on_success():
    with TestClient(app):
        db = SessionLocal()
        try:
            row = SourceRegistry(source_name="Circuit Test Source", collector_type="official_html", status="active")
            db.add(row)
            db.commit()
            db.refresh(row)

            for _ in range(3):
                row.consecutive_failures += 1
                record_circuit_result(db, row, success=False)
            assert row.circuit_state == "open"
            assert circuit_is_open(row)

            record_circuit_result(db, row, success=True)
            assert row.circuit_state == "closed"
            assert not circuit_is_open(row)
        finally:
            db.close()


def test_health_tracking_records_latency_and_availability():
    with TestClient(app):
        db = SessionLocal()
        try:
            db.add(SourceRegistry(source_name="Health Test Source", collector_type="official_html", status="active"))
            db.add(IngestionRun(source_name="Health Test Source", status="success"))
            db.commit()

            health_service.record_run_outcome(db, "Health Test Source", success=True, latency_ms=250)
            snapshot = health_service.get_health(db, "Health Test Source")
            assert snapshot["registered"] is True
            assert snapshot["last_latency_ms"] == 250
            assert snapshot["availability_pct"] == 100.0
        finally:
            db.close()


def test_health_for_unregistered_source():
    with TestClient(app):
        db = SessionLocal()
        try:
            snapshot = health_service.get_health(db, "Nonexistent Source XYZ")
            assert snapshot["registered"] is False
        finally:
            db.close()


# --- Scheduler ------------------------------------------------------------------

def test_scheduler_is_due_respects_cadence_and_status():
    now = datetime.utcnow()
    never_run = SourceRegistry(source_name="A", collector_type="official_html", status="active", schedule="daily")
    assert is_due(never_run, now)

    recently_run = SourceRegistry(
        source_name="B", collector_type="official_html", status="active", schedule="daily",
        last_run_at=now - timedelta(hours=1),
    )
    assert not is_due(recently_run, now)

    overdue_daily = SourceRegistry(
        source_name="C", collector_type="official_html", status="active", schedule="daily",
        last_run_at=now - timedelta(days=2),
    )
    assert is_due(overdue_daily, now)

    manual_only = SourceRegistry(source_name="D", collector_type="official_html", status="active", schedule="manual")
    assert not is_due(manual_only, now)

    disabled = SourceRegistry(source_name="E", collector_type="official_html", status="disabled", schedule="hourly")
    assert not is_due(disabled, now)


def test_scheduler_due_sources_orders_by_priority():
    with TestClient(app):
        db = SessionLocal()
        try:
            db.add_all([
                SourceRegistry(source_name="Low Priority Due", collector_type="official_html", status="active",
                                schedule="hourly", priority=200),
                SourceRegistry(source_name="High Priority Due", collector_type="official_html", status="active",
                                schedule="hourly", priority=10),
            ])
            db.commit()
            due = due_sources(db)
            names = [s.source_name for s in due if s.source_name in ("Low Priority Due", "High Priority Due")]
            assert names == ["High Priority Due", "Low Priority Due"]
        finally:
            db.close()


# --- Orchestrator (fetch stubbed — no real network) ------------------------------

def test_orchestrator_run_source_success_path(monkeypatch):
    with TestClient(app):
        db = SessionLocal()
        try:
            row = SourceRegistry(
                source_name="Orchestrator Test Source", official_url="https://example.gov.in",
                collector_type="official_html", status="active",
            )
            db.add(row)
            db.commit()
            db.refresh(row)

            monkeypatch.setattr(
                ConfiguredSourceAdapter, "fetch",
                lambda self: [_make_record("orc-1", official_url="https://example.gov.in/orc-1")],
            )

            result = run_source(db, row)
            assert result["status"] == "success"
            assert result["created"] == 1
            db.refresh(row)
            assert row.last_success_at is not None
            assert row.circuit_state == "closed"
        finally:
            db.close()


def test_orchestrator_run_source_records_failure_and_dead_letters(monkeypatch):
    with TestClient(app):
        db = SessionLocal()
        try:
            row = SourceRegistry(
                source_name="Orchestrator Fail Source", official_url="https://example.gov.in",
                collector_type="official_html", status="active",
            )
            db.add(row)
            db.commit()
            db.refresh(row)

            def always_raise(self):
                raise RuntimeError("site unreachable")

            monkeypatch.setattr(ConfiguredSourceAdapter, "fetch", always_raise)

            result = run_source(db, row)
            assert result["status"] == "failed"
            db.refresh(row)
            assert row.consecutive_failures >= 1
        finally:
            db.close()


def test_orchestrator_skips_disabled_source():
    with TestClient(app):
        db = SessionLocal()
        try:
            row = SourceRegistry(source_name="Disabled Source", collector_type="official_html", status="disabled")
            db.add(row)
            db.commit()
            db.refresh(row)
            result = run_source(db, row)
            assert result["status"] == "skipped"
        finally:
            db.close()


# --- Admin API ------------------------------------------------------------------

def test_register_source_with_v19_2_fields_roundtrips():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/government/sources",
            headers=ADMIN_HEADERS,
            json={
                "source_name": "API Test Source",
                "official_url": "https://example.gov.in/notices",
                "collector_type": "sitemap",
                "organization": "Example Org",
                "govt_level": "Central",
                "category": "Testing",
                "config": {"url_contains": "recruitment"},
                "priority": 5,
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["organization"] == "Example Org"
        assert body["priority"] == 5


def test_adapter_types_endpoint_requires_admin():
    with TestClient(app) as client:
        resp = client.get("/api/v1/government/adapters/types")
        assert resp.status_code in (401, 403)

        resp = client.get("/api/v1/government/adapters/types", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert "official_html" in resp.json()["collector_types"]
        assert "json_api" in resp.json()["collector_types"]


def test_validate_endpoint_flags_bad_config():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/government/sources",
            headers=ADMIN_HEADERS,
            json={"source_name": "Validate Test Source", "collector_type": "html_list",
                  "official_url": "https://example.gov.in"},
        )
        source_id = created.json()["id"]
        resp = client.post(f"/api/v1/government/sources/{source_id}/validate", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["valid"] is False


def test_manual_run_endpoint(monkeypatch):
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/government/sources",
            headers=ADMIN_HEADERS,
            json={"source_name": "Manual Run API Source", "collector_type": "official_html",
                  "official_url": "https://example.gov.in", "status": "active"},
        )
        source_id = created.json()["id"]

        monkeypatch.setattr(ConfiguredSourceAdapter, "fetch", lambda self: [])

        resp = client.post(f"/api/v1/government/sources/{source_id}/run", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

        health_resp = client.get(f"/api/v1/government/sources/{source_id}/health", headers=ADMIN_HEADERS)
        assert health_resp.json()["registered"] is True

        runs_resp = client.get(f"/api/v1/government/sources/{source_id}/runs", headers=ADMIN_HEADERS)
        assert runs_resp.json()["total"] >= 1

        logs_resp = client.get(f"/api/v1/government/sources/{source_id}/logs", headers=ADMIN_HEADERS)
        assert len(logs_resp.json()["logs"]) >= 1


def test_statistics_endpoint():
    with TestClient(app) as client:
        resp = client.get("/api/v1/government/sources/statistics", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert "total_sources" in body and "sources_by_status" in body


def test_framework_catalog_preview_and_seed_idempotent():
    with TestClient(app) as client:
        preview = client.get("/api/v1/government/sources/framework-catalog", headers=ADMIN_HEADERS)
        assert preview.status_code == 200
        assert len(preview.json()["organizations"]) >= 20

        first = client.post("/api/v1/government/sources/seed-framework", headers=ADMIN_HEADERS)
        assert first.status_code == 201
        first_created = len(first.json()["created"])
        assert first_created >= 20

        second = client.post("/api/v1/government/sources/seed-framework", headers=ADMIN_HEADERS)
        assert second.json()["created"] == []  # idempotent — nothing new the second time


def test_scheduler_endpoints():
    with TestClient(app) as client:
        due_resp = client.get("/api/v1/government/scheduler/due", headers=ADMIN_HEADERS)
        assert due_resp.status_code == 200

        run_resp = client.post("/api/v1/government/scheduler/run-due", headers=ADMIN_HEADERS)
        assert run_resp.status_code == 200
        assert run_resp.json()["ran"] >= 0
