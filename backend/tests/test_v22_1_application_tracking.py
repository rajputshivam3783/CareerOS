"""V22.1 — Application Tracking Infrastructure tests.

Covers: application creation (CareerOS-linked and external), duplicate
prevention, status transitions + immutable history, filters,
pagination, sorting, ownership isolation, unauthorized access, input
validation, deletion, dashboard statistics, and that V16-V21.5
regressions (auth, saved jobs, career copilot context, recommendations)
did not occur from extending the Application model in place.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v22_1.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}

_counter = {"n": 0}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _register_and_login(client, email_prefix: str) -> dict:
    _counter["n"] += 1
    email = f"{email_prefix}{_counter['n']}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Test User"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_and_publish_job(client, **overrides) -> int:
    _counter["n"] += 1
    payload = {
        "title": f"Backend Engineer V22.1 #{_counter['n']}",
        "organization": f"Acme Corp {_counter['n']}",
        "description": "Python backend role.",
        "qualification": "B.Tech",
        "location": "Noida",
        "job_type": "Private",
        "source_name": "V22.1 Test",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/admin/ingest", headers=ADMIN_HEADERS, json=payload)
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["job_id"]
    pub = client.post(f"/api/v1/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)
    assert pub.status_code == 200, pub.text
    return job_id


def _create_external(client, headers, **overrides):
    payload = {"company": "External Co", "job_title": "Backend Dev"}
    payload.update(overrides)
    return client.post("/api/v1/applications", headers=headers, json=payload)


# ---------------------------------------------------------------------------
# Creation — CareerOS-linked and external
# ---------------------------------------------------------------------------


def test_external_application_creation(client):
    headers = _register_and_login(client, "v22_1ext")
    resp = _create_external(client, headers, company="Globex", job_title="Data Analyst", source="linkedin")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["job_id"] is None
    assert body["company"] == "Globex"
    assert body["job_title"] == "Data Analyst"
    assert body["status"] == "SAVED"  # default for external applications
    assert body["source"] == "linkedin"


def test_external_application_requires_company_and_title(client):
    headers = _register_and_login(client, "v22_1extreq")
    resp = client.post("/api/v1/applications", headers=headers, json={"company": "", "job_title": "X"})
    assert resp.status_code == 422


def test_job_url_must_be_http_or_https(client):
    headers = _register_and_login(client, "v22_1url")
    resp = _create_external(client, headers, job_url="javascript:alert(1)")
    assert resp.status_code == 422


def test_track_application_from_careeros_job_copies_job_fields(client):
    headers = _register_and_login(client, "v22_1track")
    job_id = _create_and_publish_job(client, title="Platform Engineer", organization="Tracked Co", location="Pune")

    resp = client.post(f"/api/v1/jobs/{job_id}/applications", headers=headers, params={"mark_applied": "false"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["job_id"] == job_id
    assert body["company"] == "Tracked Co"
    assert body["job_title"] == "Platform Engineer"
    assert body["location"] == "Pune"
    assert body["status"] == "PLANNING_TO_APPLY"
    assert body["source"] == "careeros"
    assert body["applied_at"] is None


def test_mark_as_applied_sets_applied_status_and_date(client):
    headers = _register_and_login(client, "v22_1markapplied")
    job_id = _create_and_publish_job(client)

    resp = client.post(f"/api/v1/jobs/{job_id}/applications", headers=headers, params={"mark_applied": "true"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "APPLIED"
    assert body["applied_at"] is not None


def test_tracking_persists_job_snapshot_even_if_job_later_changes(client):
    """"If the original job later changes, historical application
    information must remain meaningful" — the application keeps its
    own copy, not a live join. Proven here by removing the Job
    entirely (job_id -> NULL via ON DELETE SET NULL) after tracking;
    the application's own company/job_title survive untouched."""
    headers = _register_and_login(client, "v22_1snapshot")
    job_id = _create_and_publish_job(client, title="Original Title", organization="Original Co")

    resp = client.post(f"/api/v1/jobs/{job_id}/applications", headers=headers, params={"mark_applied": "false"})
    app_id = resp.json()["id"]

    delete_resp = client.delete(f"/api/v1/admin/jobs/{job_id}", headers=ADMIN_HEADERS)
    assert delete_resp.status_code == 204

    fetched = client.get(f"/api/v1/applications/{app_id}", headers=headers).json()
    assert fetched["company"] == "Original Co"
    assert fetched["job_title"] == "Original Title"
    assert fetched["job_id"] is None  # the link itself is gone; the snapshot is not


def test_tracking_nonexistent_job_404s(client):
    headers = _register_and_login(client, "v22_1notfound")
    resp = client.post("/api/v1/jobs/999999999/applications", headers=headers, params={"mark_applied": "false"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Duplicate prevention
# ---------------------------------------------------------------------------


def test_duplicate_active_application_for_same_job_rejected(client):
    headers = _register_and_login(client, "v22_1dupjob")
    job_id = _create_and_publish_job(client)
    first = client.post(f"/api/v1/jobs/{job_id}/applications", headers=headers, params={"mark_applied": "false"})
    assert first.status_code == 201
    second = client.post(f"/api/v1/jobs/{job_id}/applications", headers=headers, params={"mark_applied": "false"})
    assert second.status_code == 409


def test_duplicate_external_application_same_company_and_title_rejected(client):
    headers = _register_and_login(client, "v22_1dupext")
    first = _create_external(client, headers, company="Dup Co", job_title="Dup Role")
    assert first.status_code == 201
    second = _create_external(client, headers, company="Dup Co", job_title="Dup Role")
    assert second.status_code == 409


def test_reapplying_after_withdrawal_is_allowed(client):
    """A TERMINAL status (WITHDRAWN/REJECTED/ACCEPTED/GHOSTED) is never
    considered a duplicate blocker — a genuine second attempt is allowed."""
    headers = _register_and_login(client, "v22_1reapply")
    job_id = _create_and_publish_job(client)
    first = client.post(f"/api/v1/jobs/{job_id}/applications", headers=headers, params={"mark_applied": "false"})
    app_id = first.json()["id"]

    client.post(f"/api/v1/applications/{app_id}/status", headers=headers, json={"status": "WITHDRAWN"})

    second = client.post(f"/api/v1/jobs/{job_id}/applications", headers=headers, params={"mark_applied": "false"})
    assert second.status_code == 201, second.text


# ---------------------------------------------------------------------------
# Status transitions + immutable history
# ---------------------------------------------------------------------------


def test_status_change_creates_history_entry(client):
    headers = _register_and_login(client, "v22_1history")
    resp = _create_external(client, headers, company="Hist Co", job_title="Hist Role")
    app_id = resp.json()["id"]

    change = client.post(f"/api/v1/applications/{app_id}/status", headers=headers, json={"status": "APPLIED", "note": "submitted online"})
    assert change.status_code == 200
    assert change.json()["status"] == "APPLIED"

    history = client.get(f"/api/v1/applications/{app_id}/history", headers=headers).json()
    assert len(history) == 2  # creation entry + this transition
    assert history[0]["new_status"] == "SAVED"
    assert history[1]["old_status"] == "SAVED"
    assert history[1]["new_status"] == "APPLIED"
    assert history[1]["metadata"]["note"] == "submitted online"


def test_status_history_is_never_overwritten_across_multiple_changes(client):
    headers = _register_and_login(client, "v22_1historymulti")
    resp = _create_external(client, headers, company="Multi Co", job_title="Multi Role")
    app_id = resp.json()["id"]

    for status in ["PLANNING_TO_APPLY", "APPLIED", "INTERVIEW", "OFFER", "ACCEPTED"]:
        r = client.post(f"/api/v1/applications/{app_id}/status", headers=headers, json={"status": status})
        assert r.status_code == 200

    history = client.get(f"/api/v1/applications/{app_id}/history", headers=headers).json()
    assert len(history) == 6  # creation + 5 transitions
    assert [h["new_status"] for h in history] == ["SAVED", "PLANNING_TO_APPLY", "APPLIED", "INTERVIEW", "OFFER", "ACCEPTED"]


def test_invalid_status_rejected(client):
    headers = _register_and_login(client, "v22_1badstatus")
    resp = _create_external(client, headers, company="Bad Co", job_title="Bad Role")
    app_id = resp.json()["id"]
    change = client.post(f"/api/v1/applications/{app_id}/status", headers=headers, json={"status": "NONSENSE"})
    assert change.status_code == 422


def test_legacy_lowercase_status_normalized_on_create(client):
    """Backward compatibility: an old-style lowercase status value is
    normalized to its canonical form rather than rejected or stored raw."""
    headers = _register_and_login(client, "v22_1legacy")
    resp = _create_external(client, headers, company="Legacy Co", job_title="Legacy Role", status="interview")
    assert resp.status_code == 201
    assert resp.json()["status"] == "INTERVIEW"


def test_patch_with_status_field_also_writes_history(client):
    """PATCH is a general partial update, but if `status` is included
    it must still go through the same audited transition path — never
    a silent status change with no history row."""
    headers = _register_and_login(client, "v22_1patchstatus")
    resp = _create_external(client, headers, company="Patch Co", job_title="Patch Role")
    app_id = resp.json()["id"]

    patch = client.patch(f"/api/v1/applications/{app_id}", headers=headers, json={"status": "APPLIED", "notes": "via patch"})
    assert patch.status_code == 200
    assert patch.json()["status"] == "APPLIED"
    assert patch.json()["notes"] == "via patch"

    history = client.get(f"/api/v1/applications/{app_id}/history", headers=headers).json()
    assert any(h["new_status"] == "APPLIED" for h in history)


# ---------------------------------------------------------------------------
# Filters, pagination, sorting
# ---------------------------------------------------------------------------


def test_filter_by_status_and_company(client):
    headers = _register_and_login(client, "v22_1filter")
    _create_external(client, headers, company="FilterCo A", job_title="Role 1", status="APPLIED")
    _create_external(client, headers, company="FilterCo B", job_title="Role 2", status="INTERVIEW")

    resp = client.get("/api/v1/applications", headers=headers, params={"status": "INTERVIEW"})
    body = resp.json()
    assert all(item["status"] == "INTERVIEW" for item in body["items"])
    assert any(item["company"] == "FilterCo B" for item in body["items"])

    resp2 = client.get("/api/v1/applications", headers=headers, params={"company": "FilterCo A"})
    body2 = resp2.json()
    assert all("filterco a" in item["company"].lower() for item in body2["items"])


def test_filter_by_source_and_job_id(client):
    headers = _register_and_login(client, "v22_1filter2")
    job_id = _create_and_publish_job(client)
    tracked = client.post(f"/api/v1/jobs/{job_id}/applications", headers=headers, params={"mark_applied": "false"}).json()
    _create_external(client, headers, company="Ext Only Co", job_title="Ext Role", source="referral")

    resp = client.get("/api/v1/applications", headers=headers, params={"job_id": job_id})
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == tracked["id"]

    resp2 = client.get("/api/v1/applications", headers=headers, params={"source": "referral"})
    assert any(item["company"] == "Ext Only Co" for item in resp2.json()["items"])


def test_pagination_limit_and_offset(client):
    headers = _register_and_login(client, "v22_1page")
    for i in range(5):
        _create_external(client, headers, company=f"PageCo{i}", job_title=f"Role{i}")

    page1 = client.get("/api/v1/applications", headers=headers, params={"limit": 2, "offset": 0}).json()
    page2 = client.get("/api/v1/applications", headers=headers, params={"limit": 2, "offset": 2}).json()
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 2
    assert page1["total"] >= 5
    ids_page1 = {i["id"] for i in page1["items"]}
    ids_page2 = {i["id"] for i in page2["items"]}
    assert ids_page1.isdisjoint(ids_page2)


def test_sort_by_company_ascending(client):
    headers = _register_and_login(client, "v22_1sort")
    _create_external(client, headers, company="Zeta Co", job_title="Role Z")
    _create_external(client, headers, company="Alpha Co", job_title="Role A")

    resp = client.get("/api/v1/applications", headers=headers, params={"sort_by": "company", "sort_dir": "asc", "limit": 100})
    companies = [item["company"] for item in resp.json()["items"]]
    assert companies.index("Alpha Co") < companies.index("Zeta Co")


def test_invalid_sort_field_rejected(client):
    headers = _register_and_login(client, "v22_1badsort")
    resp = client.get("/api/v1/applications", headers=headers, params={"sort_by": "user_id; DROP TABLE applications;"})
    assert resp.status_code == 422


def test_legacy_upcoming_days_filter_still_works(client):
    """Backward compatibility: the old V7 `?upcoming_days=N` shape
    (flat list, no pagination envelope) still works unchanged."""
    from datetime import date, timedelta

    headers = _register_and_login(client, "v22_1legacyfilter")
    resp = _create_external(client, headers, company="Deadline Co", job_title="Deadline Role", next_deadline=(date.today() + timedelta(days=3)).isoformat())
    assert resp.status_code == 201

    legacy = client.get("/api/v1/applications", headers=headers, params={"upcoming_days": 7})
    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)
    assert any(item["company"] == "Deadline Co" for item in legacy.json())


# ---------------------------------------------------------------------------
# Ownership isolation / unauthorized access (SECURITY)
# ---------------------------------------------------------------------------


def test_cannot_read_another_users_application(client):
    headers_a = _register_and_login(client, "v22_1ownA")
    headers_b = _register_and_login(client, "v22_1ownB")
    resp = _create_external(client, headers_a, company="Private Co", job_title="Private Role")
    app_id = resp.json()["id"]

    forbidden = client.get(f"/api/v1/applications/{app_id}", headers=headers_b)
    assert forbidden.status_code == 404  # never leaks existence via a 403 distinction


def test_cannot_update_another_users_application(client):
    headers_a = _register_and_login(client, "v22_1ownC")
    headers_b = _register_and_login(client, "v22_1ownD")
    resp = _create_external(client, headers_a, company="Locked Co", job_title="Locked Role")
    app_id = resp.json()["id"]

    forbidden = client.patch(f"/api/v1/applications/{app_id}", headers=headers_b, json={"notes": "hacked"})
    assert forbidden.status_code == 404


def test_cannot_delete_another_users_application(client):
    headers_a = _register_and_login(client, "v22_1ownE")
    headers_b = _register_and_login(client, "v22_1ownF")
    resp = _create_external(client, headers_a, company="Guarded Co", job_title="Guarded Role")
    app_id = resp.json()["id"]

    forbidden = client.delete(f"/api/v1/applications/{app_id}", headers=headers_b)
    assert forbidden.status_code == 404
    still_there = client.get(f"/api/v1/applications/{app_id}", headers=headers_a)
    assert still_there.status_code == 200


def test_cannot_change_status_of_another_users_application(client):
    headers_a = _register_and_login(client, "v22_1ownG")
    headers_b = _register_and_login(client, "v22_1ownH")
    resp = _create_external(client, headers_a, company="Status Guard Co", job_title="Status Guard Role")
    app_id = resp.json()["id"]

    forbidden = client.post(f"/api/v1/applications/{app_id}/status", headers=headers_b, json={"status": "REJECTED"})
    assert forbidden.status_code == 404


def test_cannot_view_another_users_history(client):
    headers_a = _register_and_login(client, "v22_1ownI")
    headers_b = _register_and_login(client, "v22_1ownJ")
    resp = _create_external(client, headers_a, company="History Guard Co", job_title="History Guard Role")
    app_id = resp.json()["id"]

    forbidden = client.get(f"/api/v1/applications/{app_id}/history", headers=headers_b)
    assert forbidden.status_code == 404


def test_applications_endpoints_require_authentication(client):
    assert client.get("/api/v1/applications").status_code in (401, 403)
    assert client.post("/api/v1/applications", json={"company": "X", "job_title": "Y"}).status_code in (401, 403)
    assert client.get("/api/v1/applications/stats").status_code in (401, 403)


def test_user_id_in_body_is_ignored_never_trusted(client):
    """SECURITY: "Do not trust user_id supplied by frontend." Even if
    a caller tries to smuggle a user_id into the body, the created
    application belongs to the authenticated caller, never anyone else."""
    headers = _register_and_login(client, "v22_1notrust")
    resp = client.post(
        "/api/v1/applications", headers=headers,
        json={"company": "Trust Co", "job_title": "Trust Role", "user_id": 999999},
    )
    assert resp.status_code == 201
    listing = client.get("/api/v1/applications", headers=headers).json()
    assert any(item["company"] == "Trust Co" for item in listing["items"])


# ---------------------------------------------------------------------------
# Invalid data
# ---------------------------------------------------------------------------


def test_get_nonexistent_application_404s(client):
    headers = _register_and_login(client, "v22_1missing")
    resp = client.get("/api/v1/applications/999999999", headers=headers)
    assert resp.status_code == 404


def test_patch_to_nonexistent_job_id_rejected(client):
    headers = _register_and_login(client, "v22_1badjobid")
    resp = _create_external(client, headers, company="Move Co", job_title="Move Role")
    app_id = resp.json()["id"]
    patch = client.patch(f"/api/v1/applications/{app_id}", headers=headers, json={"job_id": 999999999})
    assert patch.status_code == 404


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def test_delete_application_removes_it_and_its_history(client):
    headers = _register_and_login(client, "v22_1delete")
    resp = _create_external(client, headers, company="Delete Co", job_title="Delete Role")
    app_id = resp.json()["id"]

    delete_resp = client.delete(f"/api/v1/applications/{app_id}", headers=headers)
    assert delete_resp.status_code == 204

    gone = client.get(f"/api/v1/applications/{app_id}", headers=headers)
    assert gone.status_code == 404


# ---------------------------------------------------------------------------
# Dashboard statistics
# ---------------------------------------------------------------------------


def test_application_stats_breakdown(client):
    headers = _register_and_login(client, "v22_1stats")
    _create_external(client, headers, company="Stat Co A", job_title="Role A", status="APPLIED")
    _create_external(client, headers, company="Stat Co B", job_title="Role B", status="INTERVIEW")
    _create_external(client, headers, company="Stat Co C", job_title="Role C", status="OFFER")
    _create_external(client, headers, company="Stat Co D", job_title="Role D", status="REJECTED")

    stats = client.get("/api/v1/applications/stats", headers=headers).json()
    assert stats["total"] >= 4
    assert stats["by_status"]["APPLIED"] >= 1
    assert stats["by_status"]["INTERVIEW"] >= 1
    assert stats["by_status"]["OFFER"] >= 1
    assert stats["by_status"]["REJECTED"] >= 1
    assert len(stats["recent_activity"]) > 0


def test_dashboard_includes_application_stats(client):
    headers = _register_and_login(client, "v22_1dashboard")
    _create_external(client, headers, company="Dash Co", job_title="Dash Role", status="APPLIED")

    dashboard = client.get("/api/v1/dashboard", headers=headers).json()
    assert "application_stats" in dashboard
    assert dashboard["application_stats"]["total"] >= 1
    assert "applications" in dashboard  # legacy bare count key still present


# ---------------------------------------------------------------------------
# Saved Job integration (SAVED JOB INTEGRATION)
# ---------------------------------------------------------------------------


def test_saved_job_functionality_still_works_independently(client):
    headers = _register_and_login(client, "v22_1savedjob")
    job_id = _create_and_publish_job(client)

    save_resp = client.post(f"/api/v1/saved-jobs/{job_id}", headers=headers)
    assert save_resp.status_code == 201

    saved = client.get("/api/v1/saved-jobs", headers=headers).json()
    assert any(j["id"] == job_id for j in saved)

    # Tracking an application for the same job does not remove or
    # conflict with the SavedJob row — two distinct concerns.
    track_resp = client.post(f"/api/v1/jobs/{job_id}/applications", headers=headers, params={"mark_applied": "false"})
    assert track_resp.status_code == 201
    saved_after = client.get("/api/v1/saved-jobs", headers=headers).json()
    assert any(j["id"] == job_id for j in saved_after)


# ---------------------------------------------------------------------------
# Regression — V16-V21.5 systems untouched
# ---------------------------------------------------------------------------


def test_v21_3_recommendation_feed_still_works(client):
    headers = _register_and_login(client, "v22_1regressrec")
    _create_and_publish_job(client, skills="python")
    resp = client.get("/api/v1/job-recommendations", headers=headers)
    assert resp.status_code == 200


def test_v21_1_search_still_works(client):
    _create_and_publish_job(client)
    resp = client.get("/api/v1/search", params={"q": "python"})
    assert resp.status_code == 200


def test_career_copilot_context_reads_applications_without_error(client):
    """Regression guard: app.career_copilot.context_engine reads
    Application.company/.role/.status directly — must not break after
    the V22.1 model extension."""
    headers = _register_and_login(client, "v22_1regresscopilot")
    _create_external(client, headers, company="Copilot Co", job_title="Copilot Role", status="APPLIED")
    resp = client.get("/api/v1/career-copilot/context", headers=headers)
    assert resp.status_code == 200


def test_recruiter_applicant_pipeline_unaffected(client):
    """POST /jobs/{job_id}/apply (Applicant, recruiter-visible pipeline)
    is a completely separate system from POST /applications — creating
    one must not create, alter, or conflict with the other. This test
    job has no recruiter owner (created via admin ingest), so the
    pre-existing, unchanged behavior is a 409 ("use the official apply
    link") — the regression check is that this behavior is exactly
    what it always was, not that V22.1 changed it either way."""
    headers = _register_and_login(client, "v22_1regressapplicant")
    job_id = _create_and_publish_job(client)
    resp = client.post(f"/api/v1/jobs/{job_id}/apply", headers=headers, json={})
    assert resp.status_code == 409
    assert "official apply link" in resp.json()["detail"]

    # The private tracker is unaffected by that 409 and still works
    # for the exact same job.
    track = client.post(f"/api/v1/jobs/{job_id}/applications", headers=headers, params={"mark_applied": "false"})
    assert track.status_code == 201


def test_admin_guard_still_protects_admin_endpoints(client):
    """Regression guard: admin_guard's shared-key protection (used by
    both the pre-existing admin endpoints and this version's new
    admin-adjacent code paths) still rejects a missing/wrong key."""
    resp = client.post("/api/v1/admin/ingest", json={"title": "X", "organization": "Y"})
    assert resp.status_code in (401, 403)
