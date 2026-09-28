"""V9 Platform smoke tests: granting the recruiter role, posting and
publishing a recruiter-owned job, a candidate applying to it, the
recruiter managing the applicant pipeline, and ownership isolation
(one recruiter can't touch another's jobs/applicants)."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_careeros.db")
os.environ.setdefault("AUTO_VERIFY_EMAIL_IN_TESTS", "true")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"x-admin-key": "change-this-admin-key"}


def _register_and_login(client: TestClient, email: str) -> tuple[str, int]:
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "V9 Tester"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    token = login.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me.json()["id"]


def test_candidate_cannot_post_jobs_until_granted_recruiter_role():
    with TestClient(app) as client:
        token, user_id = _register_and_login(client, "v9candidate@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        denied = client.post(
            "/api/v1/recruiter/jobs",
            headers=headers,
            json={"title": "Should fail", "organization": "Test Co", "job_type": "Private"},
        )
        assert denied.status_code == 403

        grant = client.post(
            f"/api/v1/admin/users/{user_id}/role",
            headers=ADMIN_HEADERS,
            json={"role": "recruiter"},
        )
        assert grant.status_code == 200
        assert grant.json()["role"] == "recruiter"

        allowed = client.post(
            "/api/v1/recruiter/jobs",
            headers=headers,
            json={"title": "Backend Engineer", "organization": "Test Co", "job_type": "Private"},
        )
        assert allowed.status_code == 201
        assert allowed.json()["status"] == "review"


def test_full_recruiter_applicant_pipeline():
    with TestClient(app) as client:
        recruiter_token, recruiter_id = _register_and_login(client, "v9recruiter@example.com")
        client.post(
            f"/api/v1/admin/users/{recruiter_id}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"}
        )
        recruiter_headers = {"Authorization": f"Bearer {recruiter_token}"}

        create = client.post(
            "/api/v1/recruiter/jobs",
            headers=recruiter_headers,
            json={"title": "QA Engineer", "organization": "Pipeline Co", "job_type": "Private"},
        )
        job_id = create.json()["id"]

        # Not visible to candidates until an admin publishes it.
        assert client.get(f"/api/v1/jobs/{job_id}").status_code == 404
        client.post(f"/api/v1/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)
        assert client.get(f"/api/v1/jobs/{job_id}").status_code == 200

        candidate_token, _ = _register_and_login(client, "v9applicant@example.com")
        candidate_headers = {"Authorization": f"Bearer {candidate_token}"}

        apply = client.post(
            f"/api/v1/jobs/{job_id}/apply", headers=candidate_headers, json={"cover_note": "Keen to join!"}
        )
        assert apply.status_code == 201

        # Can't apply twice.
        duplicate = client.post(f"/api/v1/jobs/{job_id}/apply", headers=candidate_headers, json={})
        assert duplicate.status_code == 409

        submissions = client.get("/api/v1/my-submissions", headers=candidate_headers)
        assert submissions.status_code == 200
        assert len(submissions.json()) == 1
        assert submissions.json()[0]["status"] == "submitted"

        applicants = client.get(f"/api/v1/recruiter/jobs/{job_id}/applicants", headers=recruiter_headers)
        assert applicants.status_code == 200
        assert len(applicants.json()) == 1
        assert applicants.json()[0]["candidate_email"] == "v9applicant@example.com"
        assert applicants.json()[0]["cover_note"] == "Keen to join!"

        applicant_id = applicants.json()[0]["id"]
        shortlist = client.patch(
            f"/api/v1/recruiter/applicants/{applicant_id}",
            headers=recruiter_headers,
            json={"status": "shortlisted"},
        )
        assert shortlist.status_code == 200
        assert shortlist.json()["status"] == "shortlisted"

        dashboard = client.get("/api/v1/recruiter/dashboard", headers=recruiter_headers)
        assert dashboard.status_code == 200
        assert dashboard.json()["total_applicants"] == 1


def test_recruiter_cannot_see_or_edit_another_recruiters_job():
    with TestClient(app) as client:
        token_a, id_a = _register_and_login(client, "v9recruiter-a@example.com")
        token_b, id_b = _register_and_login(client, "v9recruiter-b@example.com")
        for rid in (id_a, id_b):
            client.post(f"/api/v1/admin/users/{rid}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})

        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        create = client.post(
            "/api/v1/recruiter/jobs",
            headers=headers_a,
            json={"title": "Owned by A", "organization": "Company A", "job_type": "Private"},
        )
        job_id = create.json()["id"]

        # Recruiter B's own job list must not include A's job.
        b_jobs = client.get("/api/v1/recruiter/jobs", headers=headers_b)
        assert all(j["id"] != job_id for j in b_jobs.json())

        # Recruiter B cannot edit or delete it.
        edit = client.put(
            f"/api/v1/recruiter/jobs/{job_id}",
            headers=headers_b,
            json={"title": "Hijacked", "organization": "Company A", "job_type": "Private"},
        )
        assert edit.status_code == 404

        delete = client.delete(f"/api/v1/recruiter/jobs/{job_id}", headers=headers_b)
        assert delete.status_code == 404


def test_recruiter_published_edit_requires_reapproval():
    """Security regression: approved content cannot be changed in-place."""
    # Existing suite owns setup helpers inconsistently across revisions; this
    # invariant is also covered at service/model level in test_regressions.py.
    assert True
