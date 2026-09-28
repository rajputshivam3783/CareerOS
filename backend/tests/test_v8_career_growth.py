"""V8 Career Growth smoke tests: resume upload -> skill detection ->
resume-JD match -> roadmap, plus admin-curated exam-prep resources."""

import io
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_careeros.db")
os.environ.setdefault("AUTO_VERIFY_EMAIL_IN_TESTS", "true")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"x-admin-key": "change-this-admin-key"}


def _register_and_login(client: TestClient, email: str) -> str:
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "V8 Tester"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    return login.json()["access_token"]


def _publish_job(client: TestClient, title: str, description: str) -> int:
    create = client.post(
        "/api/v1/admin/ingest",
        headers=ADMIN_HEADERS,
        json={"title": title, "organization": "Test Org", "description": description},
    )
    job_id = create.json()["job_id"]
    client.post(f"/api/v1/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)
    return job_id


def test_resume_upload_detects_skills_and_matches_job():
    with TestClient(app) as client:
        token = _register_and_login(client, "v8tester@example.com")
        headers = {"Authorization": f"Bearer {token}"}

        job_id = _publish_job(
            client,
            "Backend Engineer",
            "We need someone strong in Python, SQL, and Docker for our backend team.",
        )

        resume_text = "Experienced engineer skilled in Python, SQL, and Git. Built several Docker-based services."
        files = {"file": ("resume.txt", io.BytesIO(resume_text.encode()), "text/plain")}
        upload = client.post("/api/v1/resume", headers=headers, files=files)
        assert upload.status_code == 201
        body = upload.json()
        assert "python" in body["skills_detected"]
        assert "sql" in body["skills_detected"]

        fetched = client.get("/api/v1/resume", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["filename"] == "resume.txt"

        match = client.get(f"/api/v1/resume-match/{job_id}", headers=headers)
        assert match.status_code == 200
        match_body = match.json()
        assert match_body["score"] > 0
        assert "python" in match_body["matched_skills"]
        assert "roadmap" in match_body

        delete = client.delete("/api/v1/resume", headers=headers)
        assert delete.status_code == 204
        after_delete = client.get("/api/v1/resume", headers=headers)
        assert after_delete.status_code == 404


def test_resume_match_requires_upload_first():
    with TestClient(app) as client:
        token = _register_and_login(client, "v8nomatch@example.com")
        headers = {"Authorization": f"Bearer {token}"}
        job_id = _publish_job(client, "Data Analyst", "Looking for someone skilled in SQL and Excel.")

        response = client.get(f"/api/v1/resume-match/{job_id}", headers=headers)
        assert response.status_code == 404


def test_empty_resume_upload_is_rejected():
    with TestClient(app) as client:
        token = _register_and_login(client, "v8empty@example.com")
        headers = {"Authorization": f"Bearer {token}"}
        files = {"file": ("resume.txt", io.BytesIO(b""), "text/plain")}
        response = client.post("/api/v1/resume", headers=headers, files=files)
        assert response.status_code == 400


def test_admin_can_curate_exam_prep_resources_and_candidate_can_read_them():
    with TestClient(app) as client:
        job_id = _publish_job(client, "SSC CGL Tier 1", "Combined Graduate Level recruitment.")

        create = client.post(
            "/api/v1/admin/exam-prep",
            headers=ADMIN_HEADERS,
            json={
                "organization": "Test Org",
                "exam_name": "SSC CGL",
                "resource_type": "syllabus",
                "title": "Official syllabus PDF",
                "url": "https://example.gov.in/ssc-cgl-syllabus.pdf",
                "job_id": job_id,
            },
        )
        assert create.status_code == 201

        listing = client.get(f"/api/v1/jobs/{job_id}/exam-prep")
        assert listing.status_code == 200
        assert len(listing.json()) == 1
        assert listing.json()[0]["title"] == "Official syllabus PDF"

        admin_listing = client.get("/api/v1/admin/exam-prep", headers=ADMIN_HEADERS)
        assert admin_listing.status_code == 200
        assert len(admin_listing.json()) >= 1
