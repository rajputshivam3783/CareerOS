"""V19.3 — Government Portal: the 4 new lifecycle sections
(medical-examination/final-selection/cancelled-recruitments/archive),
/government/filters, /government/search, and sort/advanced-search
params on /government/sections/{section}. Same self-contained (own
sqlite file, shared X-Admin-Key) pattern as test_v16c_government_hub.py
and test_v19_1_government_core.py — doesn't modify or depend on
either."""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v19_3.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from datetime import date  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.domain import Job  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}


def _published_govt_job(client, suffix, **extra):
    job = client.post(
        "/api/v1/admin/ingest",
        headers=ADMIN_HEADERS,
        json={
            "title": f"Test Recruitment {suffix}",
            "organization": f"Test Board {suffix}",
            "job_type": "Government",
            "source_reference": f"v19-3-src-{suffix}",
            **extra,
        },
    ).json()
    job_id = job["job_id"]
    client.post(f"/api/v1/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)
    return job_id


def _set_job_fields(job_id: int, **fields):
    with TestClient(app):
        db = SessionLocal()
        try:
            job = db.get(Job, job_id)
            for k, v in fields.items():
                setattr(job, k, v)
            db.commit()
        finally:
            db.close()


# --- New lifecycle sections ---------------------------------------------

def test_medical_examination_section():
    with TestClient(app) as client:
        job_id = _published_govt_job(client, "medical")
        created = client.post(
            f"/api/v1/admin/jobs/{job_id}/updates", headers=ADMIN_HEADERS,
            json={"update_type": "medical", "title": "Medical examination schedule released"},
        )
        assert created.status_code == 201
        section = client.get("/api/v1/government/sections/medical-examination")
        assert section.status_code == 200
        assert any(row["job"]["id"] == job_id for row in section.json())


def test_final_selection_section():
    with TestClient(app) as client:
        job_id = _published_govt_job(client, "final-sel")
        client.post(
            f"/api/v1/admin/jobs/{job_id}/updates", headers=ADMIN_HEADERS,
            json={"update_type": "final_selection", "title": "Final selection list published"},
        )
        section = client.get("/api/v1/government/sections/final-selection")
        assert section.status_code == 200
        assert any(row["job"]["id"] == job_id for row in section.json())


def test_cancelled_recruitments_section():
    with TestClient(app) as client:
        job_id = _published_govt_job(client, "cancelled")
        client.post(
            f"/api/v1/admin/jobs/{job_id}/updates", headers=ADMIN_HEADERS,
            json={"update_type": "cancelled", "title": "Recruitment cancelled"},
        )
        section = client.get("/api/v1/government/sections/cancelled-recruitments")
        assert section.status_code == 200
        assert any(row["job"]["id"] == job_id for row in section.json())


def test_archive_section_reflects_job_status_not_update_type():
    with TestClient(app) as client:
        job_id = _published_govt_job(client, "archive")
        # Not in the archive section while still published/active.
        before = client.get("/api/v1/government/sections/archive")
        assert not any(j["id"] == job_id for j in before.json())

        _set_job_fields(job_id, status="archived")

        after = client.get("/api/v1/government/sections/archive")
        assert after.status_code == 200
        assert any(j["id"] == job_id for j in after.json())


def test_unknown_section_still_404s():
    with TestClient(app) as client:
        resp = client.get("/api/v1/government/sections/not-a-real-section")
        assert resp.status_code == 404


# --- Filters ---------------------------------------------------------------

def test_filters_reflect_real_ingested_data_only():
    with TestClient(app) as client:
        job_id = _published_govt_job(client, "filters-a", location="Mumbai")
        _set_job_fields(job_id, govt_level="Central", category="Banking")
        resp = client.get("/api/v1/government/filters")
        assert resp.status_code == 200
        body = resp.json()
        assert "Central" in body["govt_levels"]
        assert "Banking" in body["categories"]
        assert "Test Board filters-a" in body["organizations"]
        # No fabricated facet values outside what was actually ingested.
        assert "SomeFakeLevelThatWasNeverIngested" not in body["govt_levels"]


# --- Advanced search ---------------------------------------------------------

def test_advanced_search_by_ad_number():
    with TestClient(app) as client:
        job_id = _published_govt_job(client, "adnum")
        _set_job_fields(job_id, ad_number="ADVT-2026-042")

        resp = client.get("/api/v1/government/search", params={"ad_number": "2026-042"})
        assert resp.status_code == 200
        assert any(j["id"] == job_id for j in resp.json())


def test_advanced_search_by_qualification_and_location():
    with TestClient(app) as client:
        job_id = _published_govt_job(client, "qual", qualification="B.Tech in Computer Science", location="Bengaluru")
        resp = client.get("/api/v1/government/search", params={"qualification": "Computer Science", "location": "Bengaluru"})
        assert resp.status_code == 200
        assert any(j["id"] == job_id for j in resp.json())


def test_advanced_search_returns_total_count_header():
    with TestClient(app) as client:
        _published_govt_job(client, "count-a")
        resp = client.get("/api/v1/government/search")
        assert resp.status_code == 200
        assert "X-Total-Count" in resp.headers


def test_advanced_search_exam_matches_title_or_category():
    with TestClient(app) as client:
        job_id = _published_govt_job(client, "exam-match")
        _set_job_fields(job_id, category="Banking Recruitment Exam")
        resp = client.get("/api/v1/government/search", params={"exam": "Banking Recruitment"})
        assert resp.status_code == 200
        assert any(j["id"] == job_id for j in resp.json())


# --- Sorting -----------------------------------------------------------------

def test_sections_sort_by_deadline():
    with TestClient(app) as client:
        far_id = _published_govt_job(client, "sort-far")
        near_id = _published_govt_job(client, "sort-near")
        _set_job_fields(far_id, deadline=date(2027, 1, 1))
        _set_job_fields(near_id, deadline=date(2026, 9, 1))

        resp = client.get("/api/v1/government/sections/latest-jobs", params={"sort": "deadline", "limit": 100})
        ids = [j["id"] for j in resp.json()]
        assert ids.index(near_id) < ids.index(far_id)


def test_invalid_sort_value_rejected():
    with TestClient(app) as client:
        resp = client.get("/api/v1/government/sections/latest-jobs", params={"sort": "not-a-real-sort"})
        assert resp.status_code == 422


# --- Existing V16/V19.1 behavior untouched -----------------------------------

def test_existing_scholarship_section_still_works():
    with TestClient(app) as client:
        job_id = _published_govt_job(client, "scholarship-check")
        _set_job_fields(job_id, category="Scholarship")
        resp = client.get("/api/v1/government/sections/scholarships")
        assert resp.status_code == 200
        assert any(j["id"] == job_id for j in resp.json())


def test_home_counts_include_new_sections():
    with TestClient(app) as client:
        resp = client.get("/api/v1/government/home")
        assert resp.status_code == 200
        counts = resp.json()["counts"]
        for key in ("medical_examination", "final_selection", "cancelled_recruitments", "archive"):
            assert key in counts
