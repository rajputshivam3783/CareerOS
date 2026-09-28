"""V19.1 — Government Recruitment Core: government_organizations CRUD,
new lifecycle stages, ad_number/answer_key_url on Job, duplicate
detection, the government-scoped moderation queue, source registry,
and the dashboard extension. Follows the same self-contained
(own sqlite file, shared X-Admin-Key) pattern as
test_v16c_government_hub.py — it does not modify or depend on that
file, so both suites can run independently or together."""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v19_1.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}


def _ingest_govt_job(client, suffix, **extra):
    payload = {
        "title": f"Test Recruitment {suffix}",
        "organization": "Test Commission",
        "job_type": "Government",
        "source_reference": f"v19-1-src-{suffix}",
        **extra,
    }
    return client.post("/api/v1/admin/ingest", headers=ADMIN_HEADERS, json=payload).json()


# --- Organizations -------------------------------------------------------

def test_create_and_fetch_organization():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/government/organizations",
            headers=ADMIN_HEADERS,
            json={
                "name": "Staff Selection Commission",
                "short_name": "SSC",
                "govt_level": "Central",
                "official_website": "https://ssc.gov.in",
            },
        )
        assert created.status_code == 201
        org = created.json()
        assert org["short_name"] == "SSC"
        assert org["status"] == "active"

        fetched = client.get(f"/api/v1/government/organizations/{org['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "Staff Selection Commission"


def test_organization_requires_admin_key():
    with TestClient(app) as client:
        resp = client.post("/api/v1/government/organizations", json={"name": "No Auth Board"})
        assert resp.status_code in (401, 403)


def test_invalid_govt_level_rejected():
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/government/organizations",
            headers=ADMIN_HEADERS,
            json={"name": "Bad Level Board", "govt_level": "Not A Real Level"},
        )
        assert resp.status_code == 400


def test_organization_list_filters_by_status_default_active():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/government/organizations",
            headers=ADMIN_HEADERS,
            json={"name": "Archivable Board"},
        ).json()
        client.delete(f"/api/v1/government/organizations/{created['id']}", headers=ADMIN_HEADERS)

        listing = client.get("/api/v1/government/organizations", params={"search": "Archivable"})
        assert all(row["id"] != created["id"] for row in listing.json())

        listing_inactive = client.get(
            "/api/v1/government/organizations", params={"search": "Archivable", "status": "inactive"}
        )
        assert any(row["id"] == created["id"] for row in listing_inactive.json())


def test_job_can_link_to_organization_via_organization_id():
    with TestClient(app) as client:
        org = client.post(
            "/api/v1/government/organizations", headers=ADMIN_HEADERS, json={"name": "Linked Board"}
        ).json()
        result = _ingest_govt_job(client, "link", organization_id=org["id"], ad_number="12/2026")
        assert result["created"] is True


# --- ad_number / answer_key_url on Job ------------------------------------

def test_manual_ingest_accepts_ad_number_and_answer_key_url():
    with TestClient(app) as client:
        result = _ingest_govt_job(
            client, "adnum", ad_number="CR-04/2026", answer_key_url="https://example.gov.in/answer-key"
        )
        assert result["created"] is True
        job_id = result["job_id"]
        client.post(f"/api/v1/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)
        fetched = client.get(f"/api/v1/jobs/{job_id}")
        assert fetched.json()["ad_number"] == "CR-04/2026"
        assert fetched.json()["answer_key_url"] == "https://example.gov.in/answer-key"


# --- Duplicate detection ---------------------------------------------------

def test_duplicate_check_flags_same_org_and_ad_number():
    with TestClient(app) as client:
        _ingest_govt_job(client, "dup1", organization="Duplicate Test Board", ad_number="99/2026")

        dup = client.post(
            "/api/v1/government/duplicate-check",
            headers=ADMIN_HEADERS,
            json={
                "title": "A totally different title",
                "organization": "Duplicate Test Board",
                "ad_number": "99/2026",
            },
        )
        assert dup.status_code == 200
        assert dup.json()["duplicate"] is True


def test_duplicate_check_false_for_distinct_ad_number():
    with TestClient(app) as client:
        _ingest_govt_job(client, "dup2", organization="Another Board", ad_number="1/2026")

        not_dup = client.post(
            "/api/v1/government/duplicate-check",
            headers=ADMIN_HEADERS,
            json={"title": "New Recruitment", "organization": "Another Board", "ad_number": "2/2026"},
        )
        assert not_dup.json()["duplicate"] is False


def test_second_ingest_with_same_ad_number_is_skipped_as_duplicate():
    with TestClient(app) as client:
        first = _ingest_govt_job(client, "dup3", organization="Repeat Board", ad_number="7/2026")
        assert first["created"] is True

        second = _ingest_govt_job(client, "dup3b", organization="Repeat Board", ad_number="7/2026")
        assert second["created"] is False


# --- New lifecycle stages --------------------------------------------------

def test_new_v19_1_lifecycle_stages_are_accepted():
    with TestClient(app) as client:
        result = _ingest_govt_job(client, "lifecycle")
        job_id = result["job_id"]
        client.post(f"/api/v1/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)

        for stage in ["notification", "correction_window", "city_intimation", "objection_window",
                      "final_answer_key", "score_card", "medical", "final_selection", "completed"]:
            resp = client.post(
                f"/api/v1/admin/jobs/{job_id}/updates",
                headers=ADMIN_HEADERS,
                json={"update_type": stage, "title": f"{stage} event"},
            )
            assert resp.status_code == 201, f"{stage} should be accepted, got {resp.text}"


# --- Moderation queue -------------------------------------------------------

def test_moderation_queue_lists_only_pending_government_jobs():
    with TestClient(app) as client:
        pending = _ingest_govt_job(client, "modq")  # status="review", not published

        queue = client.get("/api/v1/government/moderation/queue", headers=ADMIN_HEADERS)
        assert queue.status_code == 200
        body = queue.json()
        assert body["total"] >= 1
        assert any(j["id"] == pending["job_id"] for j in body["jobs"])


def test_moderation_queue_requires_admin_key():
    with TestClient(app) as client:
        resp = client.get("/api/v1/government/moderation/queue")
        assert resp.status_code in (401, 403)


# --- Source registry --------------------------------------------------------

def test_register_and_update_source():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/government/sources",
            headers=ADMIN_HEADERS,
            json={"source_name": "UPSC Test Source", "official_url": "https://upsc.gov.in", "collector_type": "official_html"},
        )
        assert created.status_code == 201
        source = created.json()
        assert source["status"] == "disabled"

        updated = client.patch(
            f"/api/v1/government/sources/{source['id']}", headers=ADMIN_HEADERS, json={"status": "active"}
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == "active"


def test_duplicate_source_name_rejected():
    with TestClient(app) as client:
        client.post(
            "/api/v1/government/sources", headers=ADMIN_HEADERS, json={"source_name": "SSC Test Source"}
        )
        dup = client.post(
            "/api/v1/government/sources", headers=ADMIN_HEADERS, json={"source_name": "SSC Test Source"}
        )
        assert dup.status_code == 409


def test_invalid_collector_type_rejected():
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/government/sources",
            headers=ADMIN_HEADERS,
            json={"source_name": "Bad Collector Source", "collector_type": "carrier_pigeon"},
        )
        assert resp.status_code == 400


# --- Dashboard extension -----------------------------------------------------

def test_dashboard_extended_returns_latest_results_and_admit_cards():
    with TestClient(app) as client:
        result_job = _ingest_govt_job(client, "dashres")
        job_id = result_job["job_id"]
        client.post(f"/api/v1/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)
        client.post(
            f"/api/v1/admin/jobs/{job_id}/updates",
            headers=ADMIN_HEADERS,
            json={"update_type": "result", "title": "Final result declared"},
        )

        dashboard = client.get("/api/v1/government/dashboard/extended")
        assert dashboard.status_code == 200
        body = dashboard.json()
        assert "latest_results" in body and "latest_admit_cards" in body
        assert any(row["job"]["id"] == job_id for row in body["latest_results"])


# --- Backward compatibility --------------------------------------------------

def test_v16c_style_ingest_without_new_fields_still_works():
    """A caller that never heard of ad_number/answer_key_url/
    organization_id (e.g. an existing integration) must keep working
    exactly as before V19.1."""
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/admin/ingest",
            headers=ADMIN_HEADERS,
            json={
                "title": "Legacy Style Recruitment",
                "organization": "Legacy Board",
                "job_type": "Government",
                "source_reference": "legacy-v19-1",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["created"] is True
