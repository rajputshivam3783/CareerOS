"""V18.5 — Recruiter email templates: seeded defaults, edit, reset,
and preview rendering."""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v18_5.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}
PW = "password12345!"


def _recruiter_with_company(client, suffix):
    email = f"v18email{suffix}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PW, "password_confirm": PW, "full_name": "Rec"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PW})
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    login = client.post("/api/v1/auth/recruiter/login", json={"email": email, "password": PW})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.put("/api/v1/recruiter/company", headers=headers, json={"name": f"Acme Email {suffix}"})
    return headers


def test_no_company_yet_returns_404():
    with TestClient(app) as client:
        email = "v18emailnocorp@example.com"
        client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": PW, "password_confirm": PW, "full_name": "Rec"},
        )
        login = client.post("/api/v1/auth/login", json={"email": email, "password": PW})
        me = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
        ).json()
        client.post(f"/api/v1/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
        login = client.post("/api/v1/auth/recruiter/login", json={"email": email, "password": PW})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = client.get("/api/v1/recruiter/company/email-templates", headers=headers)
        assert response.status_code == 404


def test_list_seeds_all_five_defaults():
    with TestClient(app) as client:
        headers = _recruiter_with_company(client, "a")
        response = client.get("/api/v1/recruiter/company/email-templates", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 5
        types = {t["template_type"] for t in body}
        assert types == {
            "application_received", "interview_invitation", "interview_reminder", "offer", "rejection",
        }
        assert all(t["is_custom"] is False for t in body)
        assert all("{{" in t["subject"] or "{{" in t["body"] for t in body)


def test_unknown_type_404s():
    with TestClient(app) as client:
        headers = _recruiter_with_company(client, "b")
        response = client.get("/api/v1/recruiter/company/email-templates/not_a_type", headers=headers)
        assert response.status_code == 404


def test_update_then_reset():
    with TestClient(app) as client:
        headers = _recruiter_with_company(client, "c")
        updated = client.put(
            "/api/v1/recruiter/company/email-templates/offer",
            headers=headers,
            json={"subject": "Custom offer subject", "body": "Custom body for {{candidate_name}}"},
        )
        assert updated.status_code == 200, updated.text
        body = updated.json()
        assert body["is_custom"] is True
        assert body["subject"] == "Custom offer subject"

        fetched = client.get("/api/v1/recruiter/company/email-templates/offer", headers=headers)
        assert fetched.json()["subject"] == "Custom offer subject"

        reset = client.post("/api/v1/recruiter/company/email-templates/offer/reset", headers=headers)
        assert reset.status_code == 200
        reset_body = reset.json()
        assert reset_body["is_custom"] is False
        assert "{{job_title}}" in reset_body["subject"]


def test_preview_renders_sample_values():
    with TestClient(app) as client:
        headers = _recruiter_with_company(client, "d")
        response = client.post(
            "/api/v1/recruiter/company/email-templates/interview_invitation/preview",
            headers=headers,
            json={
                "subject": "Interview for {{job_title}} at {{company_name}}",
                "body": "Hi {{candidate_name}}, see you {{interview_date}} at {{interview_time}}.",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "{{" not in body["subject"]
        assert "{{" not in body["body"]
        assert "Priya Sharma" in body["body"]


def test_preview_allows_value_overrides():
    with TestClient(app) as client:
        headers = _recruiter_with_company(client, "e")
        response = client.post(
            "/api/v1/recruiter/company/email-templates/rejection/preview",
            headers=headers,
            json={
                "subject": "Update for {{candidate_name}}",
                "body": "Hi {{candidate_name}}",
                "values": {"candidate_name": "Arjun Mehta"},
            },
        )
        assert response.status_code == 200
        assert response.json()["subject"] == "Update for Arjun Mehta"


def test_variables_endpoint():
    with TestClient(app) as client:
        headers = _recruiter_with_company(client, "f")
        response = client.get("/api/v1/recruiter/company/email-templates-meta/variables", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert "candidate_name" in body["variables"]
        assert "job_title" in body["sample_values"]
