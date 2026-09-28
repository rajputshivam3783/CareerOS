"""Smoke tests: the app boots, health checks respond, and the core
auth flow (register -> login -> me) works end-to-end against a
throwaway SQLite database."""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_health_and_ready():
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200


def test_public_jobs_endpoint_returns_list():
    with TestClient(app) as client:
        response = client.get("/api/v1/jobs")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
        assert "X-Total-Count" in response.headers


def test_register_login_and_me():
    with TestClient(app) as client:
        register_response = client.post(
            "/api/v1/auth/register",
            json={"email": "test@example.com", "password": "password12345!", "password_confirm": "password12345!", "full_name": "Test User"},
        )
        assert register_response.status_code in (201, 409)

        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "password12345!"},
        )
        assert login_response.status_code == 200

        token = login_response.json()["access_token"]
        me_response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_response.status_code == 200
        assert me_response.json()["email"] == "test@example.com"


def test_login_with_wrong_password_is_rejected():
    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/register",
            json={"email": "wrongpass@example.com", "password": "password12345!", "password_confirm": "password12345!", "full_name": "Test User"},
        )
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "wrongpass@example.com", "password": "not-the-password"},
        )
        assert response.status_code == 401


def test_admin_endpoint_requires_key():
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/stats")
        assert response.status_code == 401


def test_ingest_sources_requires_key_and_lists_registry():
    with TestClient(app) as client:
        unauthenticated = client.get("/api/v1/admin/ingest/sources")
        assert unauthenticated.status_code == 401

        authenticated = client.get(
            "/api/v1/admin/ingest/sources",
            headers={"x-admin-key": "change-this-admin-key"},
        )
        assert authenticated.status_code == 200
        sources = authenticated.json()
        assert isinstance(sources, list)
        # At least one verified official source may be enabled; registry must expose booleans.
        assert all(isinstance(s["enabled"], bool) for s in sources)


def test_v3_partner_can_submit_a_private_job():
    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/admin/partners",
            headers={"x-admin-key": "change-this-admin-key"},
            json={"name": "Test Startup Pvt Ltd", "contact_email": "hr@teststartup.example"},
        )
        assert create_response.status_code == 201
        partner = create_response.json()

        submit_response = client.post(
            "/api/v1/partners/jobs",
            headers={"X-Partner-Id": str(partner["id"]), "X-Partner-Key": partner["api_key"]},
            json={
                "title": "Backend Engineer Intern",
                "job_type": "Internship",
                "employment_type": "Internship",
                "work_mode": "Remote",
                "stipend": "₹20,000/month",
                "duration": "3 months",
            },
        )
        assert submit_response.status_code == 201
        assert submit_response.json()["created"] == 1  # run_ingestion reports a count, not a bool — see app/ingestion/ingest.py

        # Wrong key must be rejected.
        rejected = client.post(
            "/api/v1/partners/jobs",
            headers={"X-Partner-Id": str(partner["id"]), "X-Partner-Key": "wrong-key"},
            json={"title": "Should not be created"},
        )
        assert rejected.status_code == 401
