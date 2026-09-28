"""V24.1 — Recruiter Workspace & Hiring Dashboard.

Covers: enriched dashboard statistics/pending-actions/recent-activity,
per-job application_count/is_expired on the Jobs list and preview,
recruiter profile read/update (and that email/role can't be changed
through it), and cross-recruiter isolation of the new endpoints.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v24_1.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}


def _register_recruiter(client, suffix):
    email = f"v24rec{suffix}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Rec"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    rlogin = client.post("/api/v1/auth/recruiter/login", json={"email": email, "password": "password12345!"})
    headers = {"Authorization": f"Bearer {rlogin.json()['access_token']}"}
    return headers, me["id"], email


def _register_candidate(client, suffix):
    email = f"v24cand{suffix}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Cand"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_dashboard_counts_reflect_real_data():
    with TestClient(app) as client:
        r_headers, _, _ = _register_recruiter(client, "a")
        c_headers = _register_candidate(client, "a")

        job = client.post(
            "/api/v1/recruiter/jobs",
            headers=r_headers,
            json={"title": "Backend Engineer", "organization": "Acme", "location": "Remote", "description": "x", "qualification": "x"},
        ).json()
        client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)
        client.post(f"/api/v1/jobs/{job['id']}/apply", headers=c_headers, json={})

        dashboard = client.get("/api/v1/recruiter/dashboard", headers=r_headers).json()
        assert dashboard["jobs_posted"] == 1
        assert dashboard["jobs_published"] == 1
        assert dashboard["total_applicants"] == 1
        assert dashboard["new_applications"] == 1
        assert dashboard["candidates_in_interview"] == 0
        assert dashboard["offers"] == 0
        assert isinstance(dashboard["pending_actions"], list)
        assert isinstance(dashboard["recent_activity"], list)
        assert dashboard["recent_activity"], "publishing a job and receiving an application should produce activity"
        assert dashboard["quick_actions"]["manage_jobs"] is True


def test_job_list_includes_application_count_and_expiry():
    with TestClient(app) as client:
        r_headers, _, _ = _register_recruiter(client, "b")
        c_headers = _register_candidate(client, "b")

        job = client.post(
            "/api/v1/recruiter/jobs",
            headers=r_headers,
            json={
                "title": "Designer", "organization": "Acme", "location": "Remote",
                "description": "x", "qualification": "x", "deadline": "2020-01-01",
            },
        ).json()
        client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)
        client.post(f"/api/v1/jobs/{job['id']}/apply", headers=c_headers, json={})

        listing = client.get("/api/v1/recruiter/jobs", headers=r_headers).json()
        row = next(j for j in listing if j["id"] == job["id"])
        assert row["application_count"] == 1
        assert row["is_expired"] is True  # published + deadline in the past
        assert row["review_status"] == "published"

        preview = client.get(f"/api/v1/recruiter/jobs/{job['id']}", headers=r_headers).json()
        assert preview["application_count"] == 1


def test_recruiter_profile_get_and_update():
    with TestClient(app) as client:
        r_headers, _, email = _register_recruiter(client, "c")

        profile = client.get("/api/v1/recruiter/profile", headers=r_headers).json()
        assert profile["email"] == email
        assert profile["role"] == "recruiter"

        updated = client.patch("/api/v1/recruiter/profile", headers=r_headers, json={"full_name": "New Name"})
        assert updated.status_code == 200
        assert updated.json()["full_name"] == "New Name"
        assert updated.json()["email"] == email  # unchanged

        again = client.get("/api/v1/recruiter/profile", headers=r_headers).json()
        assert again["full_name"] == "New Name"


def test_recruiter_profile_cannot_change_email_or_role():
    with TestClient(app) as client:
        r_headers, _, email = _register_recruiter(client, "d")
        response = client.patch(
            "/api/v1/recruiter/profile", headers=r_headers, json={"email": "hijack@example.com", "role": "admin"}
        )
        assert response.status_code == 200  # extra/unknown fields are ignored, not applied
        profile = client.get("/api/v1/recruiter/profile", headers=r_headers).json()
        assert profile["email"] == email
        assert profile["role"] == "recruiter"


def test_dashboard_and_jobs_are_isolated_across_recruiters():
    with TestClient(app) as client:
        r1_headers, _, _ = _register_recruiter(client, "e1")
        r2_headers, _, _ = _register_recruiter(client, "e2")

        job = client.post(
            "/api/v1/recruiter/jobs",
            headers=r1_headers,
            json={"title": "Analyst", "organization": "Acme", "location": "Remote", "description": "x", "qualification": "x"},
        ).json()

        r2_jobs = client.get("/api/v1/recruiter/jobs", headers=r2_headers).json()
        assert all(j["id"] != job["id"] for j in r2_jobs)

        r2_dashboard = client.get("/api/v1/recruiter/dashboard", headers=r2_headers).json()
        assert r2_dashboard["jobs_posted"] == 0

        # r2 must not be able to preview r1's job directly either.
        forbidden = client.get(f"/api/v1/recruiter/jobs/{job['id']}", headers=r2_headers)
        assert forbidden.status_code == 404
