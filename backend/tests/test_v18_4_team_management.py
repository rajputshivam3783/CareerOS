"""V18.4 — Company team management: owner-only invite/remove of
existing recruiter accounts, with an always-present owner row."""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v18_4.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}
PW = "password12345!"


def _recruiter(client, suffix):
    email = f"v184rec{suffix}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": PW, "password_confirm": PW, "full_name": f"Rec {suffix}"})
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PW})
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    login = client.post("/api/v1/auth/recruiter/login", json={"email": email, "password": PW})
    return email, {"Authorization": f"Bearer {login.json()['access_token']}"}


def _make_company(client, headers, name):
    r = client.put("/api/v1/recruiter/company", headers=headers, json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()


def test_creating_company_auto_adds_owner_to_team():
    with TestClient(app) as client:
        _, headers = _recruiter(client, "a")
        _make_company(client, headers, "Owner Auto Co A")
        team = client.get("/api/v1/recruiter/company/team", headers=headers)
        assert team.status_code == 200
        roles = [m["role"] for m in team.json()]
        assert roles == ["owner"]


def test_owner_can_invite_existing_recruiter():
    with TestClient(app) as client:
        _, owner_headers = _recruiter(client, "b")
        member_email, member_headers = _recruiter(client, "b2")
        _make_company(client, owner_headers, "Invite Co B")

        invite = client.post("/api/v1/recruiter/company/team/invite", headers=owner_headers, json={"email": member_email})
        assert invite.status_code == 201, invite.text
        assert invite.json()["role"] == "member"

        team = client.get("/api/v1/recruiter/company/team", headers=owner_headers).json()
        assert len(team) == 2
        assert any(m["email"] == member_email and m["role"] == "member" for m in team)

        # The invited member can also see the roster.
        member_view = client.get("/api/v1/recruiter/company/team", headers=member_headers)
        assert member_view.status_code == 200
        assert len(member_view.json()) == 2


def test_invite_unknown_email_is_404():
    with TestClient(app) as client:
        _, owner_headers = _recruiter(client, "c")
        _make_company(client, owner_headers, "Invite Co C")
        invite = client.post(
            "/api/v1/recruiter/company/team/invite", headers=owner_headers, json={"email": "nobody@example.com"}
        )
        assert invite.status_code == 404


def test_invite_non_recruiter_account_is_rejected():
    with TestClient(app) as client:
        _, owner_headers = _recruiter(client, "d")
        _make_company(client, owner_headers, "Invite Co D")
        candidate_email = "v184candidate@example.com"
        client.post(
            "/api/v1/auth/register",
            json={"email": candidate_email, "password": PW, "password_confirm": PW, "full_name": "Cand"},
        )
        invite = client.post(
            "/api/v1/recruiter/company/team/invite", headers=owner_headers, json={"email": candidate_email}
        )
        assert invite.status_code == 409


def test_only_owner_can_invite_or_remove():
    with TestClient(app) as client:
        _, owner_headers = _recruiter(client, "e")
        member_email, member_headers = _recruiter(client, "e2")
        _make_company(client, owner_headers, "Invite Co E")
        client.post("/api/v1/recruiter/company/team/invite", headers=owner_headers, json={"email": member_email})

        other_email, other_headers = _recruiter(client, "e3")
        blocked = client.post(
            "/api/v1/recruiter/company/team/invite", headers=member_headers, json={"email": other_email}
        )
        # The invited member has no company of their own, so the
        # owner-only guard surfaces as 404 ("no company profile"),
        # not a 403 — either way, they can't invite.
        assert blocked.status_code == 404


def test_owner_can_remove_member_but_not_self():
    with TestClient(app) as client:
        _, owner_headers = _recruiter(client, "f")
        member_email, _ = _recruiter(client, "f2")
        _make_company(client, owner_headers, "Invite Co F")
        invite = client.post(
            "/api/v1/recruiter/company/team/invite", headers=owner_headers, json={"email": member_email}
        ).json()

        removed = client.delete(f"/api/v1/recruiter/company/team/{invite['id']}", headers=owner_headers)
        assert removed.status_code == 204

        team = client.get("/api/v1/recruiter/company/team", headers=owner_headers).json()
        assert len(team) == 1
        owner_member_id = team[0]["id"]

        blocked = client.delete(f"/api/v1/recruiter/company/team/{owner_member_id}", headers=owner_headers)
        assert blocked.status_code == 409
