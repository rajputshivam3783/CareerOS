"""V18.6 — team-shared job/applicant access: a recruiter on the same
company team as a job's creator can now see and manage it too, not just
the creator themselves. See app.core.team_access.team_owner_ids."""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v18_6.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}
PW = "password12345!"


def _recruiter(client, suffix):
    email = f"v18team{suffix}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PW, "password_confirm": PW, "full_name": f"Rec {suffix}"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PW})
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    login = client.post("/api/v1/auth/recruiter/login", json={"email": email, "password": PW})
    return email, {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_teammate_can_see_and_manage_owners_job():
    with TestClient(app) as client:
        owner_email, owner_headers = _recruiter(client, "owner")
        member_email, member_headers = _recruiter(client, "member")

        client.put("/api/v1/recruiter/company", headers=owner_headers, json={"name": "Acme Team Co"})
        invite = client.post(
            "/api/v1/recruiter/company/team/invite", headers=owner_headers, json={"email": member_email}
        )
        assert invite.status_code == 201, invite.text

        job = client.post(
            "/api/v1/recruiter/jobs",
            headers=owner_headers,
            json={"title": "Backend Engineer", "organization": "Acme", "location": "Remote",
                  "description": "x", "qualification": "x", "save_as_draft": True},
        ).json()

        # Teammate can fetch it directly...
        fetched = client.get(f"/api/v1/recruiter/jobs/{job['id']}", headers=member_headers)
        assert fetched.status_code == 200, fetched.text

        # ...and it shows up in the teammate's own job list.
        listed = client.get("/api/v1/recruiter/jobs", headers=member_headers)
        assert any(j["id"] == job["id"] for j in listed.json())

        # ...and the teammate's dashboard/analytics counts include it.
        dashboard = client.get("/api/v1/recruiter/dashboard", headers=member_headers).json()
        assert dashboard["jobs_posted"] >= 1
        analytics = client.get("/api/v1/recruiter/analytics", headers=member_headers).json()
        assert analytics["jobs"] >= 1

        # ...and the teammate can act on it (e.g. edit).
        edited = client.put(
            f"/api/v1/recruiter/jobs/{job['id']}", headers=member_headers,
            json={"title": "Senior Backend Engineer", "organization": "Acme", "location": "Remote",
                  "description": "x", "qualification": "x"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["title"] == "Senior Backend Engineer"


def test_non_teammate_still_gets_404():
    with TestClient(app) as client:
        owner_email, owner_headers = _recruiter(client, "owner2")
        _stranger_email, stranger_headers = _recruiter(client, "stranger2")

        client.put("/api/v1/recruiter/company", headers=owner_headers, json={"name": "Acme Team Co 2"})
        job = client.post(
            "/api/v1/recruiter/jobs",
            headers=owner_headers,
            json={"title": "Frontend Engineer", "organization": "Acme", "location": "Remote",
                  "description": "x", "qualification": "x", "save_as_draft": True},
        ).json()

        fetched = client.get(f"/api/v1/recruiter/jobs/{job['id']}", headers=stranger_headers)
        assert fetched.status_code == 404

        listed = client.get("/api/v1/recruiter/jobs", headers=stranger_headers)
        assert all(j["id"] != job["id"] for j in listed.json())


def test_solo_recruiter_with_no_company_unaffected():
    with TestClient(app) as client:
        _email, headers = _recruiter(client, "solo")
        job = client.post(
            "/api/v1/recruiter/jobs",
            headers=headers,
            json={"title": "Solo Role", "organization": "Acme", "location": "Remote",
                  "description": "x", "qualification": "x", "save_as_draft": True},
        ).json()
        fetched = client.get(f"/api/v1/recruiter/jobs/{job['id']}", headers=headers)
        assert fetched.status_code == 200
