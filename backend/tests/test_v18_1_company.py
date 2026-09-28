"""V18.1 — Company module: recruiter-owned company profile, branches,
and the public directory/detail view."""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v18_1.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}
PW = "password12345!"


def _recruiter_headers(client, suffix):
    email = f"v18company{suffix}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PW, "password_confirm": PW, "full_name": "Rec"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PW})
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    login = client.post("/api/v1/auth/recruiter/login", json={"email": email, "password": PW})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_no_company_yet_returns_404():
    with TestClient(app) as client:
        headers = _recruiter_headers(client, "a")
        response = client.get("/api/v1/recruiter/company", headers=headers)
        assert response.status_code == 404


def test_create_and_fetch_company_profile():
    with TestClient(app) as client:
        headers = _recruiter_headers(client, "b")
        create = client.put(
            "/api/v1/recruiter/company",
            headers=headers,
            json={
                "name": "Acme Robotics B",
                "website": "https://acme.example.com",
                "industry": "Robotics",
                "company_size": "51-200",
                "founded_year": 2015,
                "location": "Bengaluru, India",
            },
        )
        assert create.status_code == 200, create.text
        body = create.json()
        assert body["name"] == "Acme Robotics B"
        assert body["slug"]
        assert body["verification_status"] == "unverified"

        fetched = client.get("/api/v1/recruiter/company", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["slug"] == body["slug"]


def test_put_is_upsert_not_duplicate():
    with TestClient(app) as client:
        headers = _recruiter_headers(client, "c")
        first = client.put("/api/v1/recruiter/company", headers=headers, json={"name": "Acme Robotics C"})
        org_id = first.json()["id"]
        second = client.put(
            "/api/v1/recruiter/company", headers=headers, json={"name": "Acme Robotics C", "industry": "Software"}
        )
        assert second.json()["id"] == org_id
        assert second.json()["industry"] == "Software"


def test_duplicate_company_name_across_recruiters_is_rejected():
    with TestClient(app) as client:
        headers_a = _recruiter_headers(client, "d1")
        headers_b = _recruiter_headers(client, "d2")
        client.put("/api/v1/recruiter/company", headers=headers_a, json={"name": "Shared Name Co"})
        clash = client.put("/api/v1/recruiter/company", headers=headers_b, json={"name": "Shared Name Co"})
        assert clash.status_code == 409


def test_material_edit_after_verification_resets_to_pending():
    with TestClient(app) as client:
        headers = _recruiter_headers(client, "e")
        org = client.put("/api/v1/recruiter/company", headers=headers, json={"name": "Acme Robotics E"}).json()
        client.post(f"/api/v1/admin/companies/{org['id']}/verify", headers=ADMIN_HEADERS)
        confirmed = client.get("/api/v1/recruiter/company", headers=headers).json()
        assert confirmed["verification_status"] == "verified"

        edited = client.put(
            "/api/v1/recruiter/company", headers=headers, json={"name": "Acme Robotics E", "industry": "Fintech"}
        )
        assert edited.json()["verification_status"] == "pending"


def test_branches_crud_and_ownership():
    with TestClient(app) as client:
        headers = _recruiter_headers(client, "f")
        client.put("/api/v1/recruiter/company", headers=headers, json={"name": "Acme Robotics F"})

        created = client.post(
            "/api/v1/recruiter/company/branches",
            headers=headers,
            json={"branch_name": "HQ", "location": "Mumbai", "is_headquarters": True},
        )
        assert created.status_code == 201
        branch_id = created.json()["id"]

        listed = client.get("/api/v1/recruiter/company/branches", headers=headers)
        assert len(listed.json()) == 1

        other_headers = _recruiter_headers(client, "f2")
        client.put("/api/v1/recruiter/company", headers=other_headers, json={"name": "Other Co F"})
        forbidden = client.delete(f"/api/v1/recruiter/company/branches/{branch_id}", headers=other_headers)
        assert forbidden.status_code == 404

        deleted = client.delete(f"/api/v1/recruiter/company/branches/{branch_id}", headers=headers)
        assert deleted.status_code == 204


def test_public_directory_and_detail():
    with TestClient(app) as client:
        headers = _recruiter_headers(client, "g")
        client.put(
            "/api/v1/recruiter/company",
            headers=headers,
            json={"name": "Acme Robotics G Public", "industry": "Robotics"},
        )
        org = client.get("/api/v1/recruiter/company", headers=headers).json()

        directory = client.get("/api/v1/companies", params={"q": "Acme Robotics G"})
        assert directory.status_code == 200
        assert any(c["slug"] == org["slug"] for c in directory.json())

        detail = client.get(f"/api/v1/companies/{org['slug']}")
        assert detail.status_code == 200
        assert detail.json()["company"]["name"] == "Acme Robotics G Public"
        assert detail.json()["branches"] == []

        missing = client.get("/api/v1/companies/not-a-real-slug")
        assert missing.status_code == 404


def test_admin_verify_and_reject_require_admin_key():
    with TestClient(app) as client:
        headers = _recruiter_headers(client, "h")
        org = client.put("/api/v1/recruiter/company", headers=headers, json={"name": "Acme Robotics H"}).json()

        unauthorized = client.post(f"/api/v1/admin/companies/{org['id']}/verify")
        assert unauthorized.status_code == 401

        rejected = client.post(f"/api/v1/admin/companies/{org['id']}/reject", headers=ADMIN_HEADERS)
        assert rejected.status_code == 200
        assert client.get("/api/v1/recruiter/company", headers=headers).json()["verification_status"] == "rejected"
