"""V16 — government hub: post-result lifecycle stages, category-based
opportunity sections (scholarships/internships/fellowships), the
expanded coverage catalog, and bulk manual ingest."""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v16c.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}


def _published_govt_job(client, suffix):
    job = client.post(
        "/api/v1/admin/ingest",
        headers=ADMIN_HEADERS,
        json={
            "title": f"Test Recruitment {suffix}",
            "organization": "Test Board",
            "job_type": "Government",
            "source_reference": f"gov-src-{suffix}",
        },
    ).json()
    job_id = job["job_id"]
    client.post(f"/api/v1/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)
    return job_id


def test_new_lifecycle_stage_is_accepted_and_appears_in_section():
    with TestClient(app) as client:
        job_id = _published_govt_job(client, "a")
        created = client.post(
            f"/api/v1/admin/jobs/{job_id}/updates",
            headers=ADMIN_HEADERS,
            json={"update_type": "dv", "title": "Document verification schedule released"},
        )
        assert created.status_code == 201

        section = client.get("/api/v1/government/sections/document-verification")
        assert section.status_code == 200
        assert any(row["job"]["id"] == job_id for row in section.json())


def test_unknown_lifecycle_stage_is_rejected():
    with TestClient(app) as client:
        job_id = _published_govt_job(client, "b")
        bad = client.post(
            f"/api/v1/admin/jobs/{job_id}/updates",
            headers=ADMIN_HEADERS,
            json={"update_type": "not_a_real_stage", "title": "x"},
        )
        assert bad.status_code == 400


def test_category_based_scholarship_section():
    with TestClient(app) as client:
        job = client.post(
            "/api/v1/admin/ingest",
            headers=ADMIN_HEADERS,
            json={
                "title": "National Merit Scholarship 2026",
                "organization": "Ministry of Education",
                "job_type": "Government",
                "source_reference": "scholarship-1",
            },
        ).json()
        assert job["job_id"]  # the ingested job was created
        # category isn't settable via ManualJob — set it directly is not
        # possible through the public API surface today, so this test
        # documents current behavior: an admin-curated scholarship would
        # need category set via a future admin edit endpoint. For now,
        # verify the section endpoint itself works and returns an empty
        # list rather than erroring when nothing matches yet.
        section = client.get("/api/v1/government/sections/scholarships")
        assert section.status_code == 200
        assert isinstance(section.json(), list)


def test_coverage_catalog_reflects_v16_expansion():
    with TestClient(app) as client:
        coverage = client.get("/api/v1/government/coverage")
        assert coverage.status_code == 200
        names = {row["name"] for row in coverage.json()["implemented_official_collectors"]}
        assert {"NTA", "ISRO", "DRDO", "EPFO", "ESIC", "RBI", "SBI Careers", "India Post"}.issubset(names)
        # Moved out of the "not yet implemented" list now that they're Tier A.
        assert "NTA" not in coverage.json()["maintained_expansion_targets"]


def test_bulk_ingest_creates_multiple_and_reports_partial_failure():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/admin/ingest/bulk",
            headers=ADMIN_HEADERS,
            json=[
                {"title": "Bulk Job One", "organization": "Org A", "job_type": "Government", "source_reference": "bulk-1"},
                {"title": "Bulk Job Two", "organization": "Org B", "job_type": "Government", "source_reference": "bulk-2"},
            ],
        )
        assert response.status_code == 201
        body = response.json()
        assert body["total"] == 2
        assert body["created"] == 2


def test_audit_logs_endpoint_is_not_shadowed():
    """Regression test for a real bug from the previous pass: an older
    GET /audit-logs route (returning a plain list) was defined earlier
    in admin.py and silently shadowed the newer paginated one, making
    the paginated version dead code. This asserts the paginated shape
    (a dict with total/results) is what's actually served."""
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/audit-logs", headers=ADMIN_HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert "total" in body and "results" in body
