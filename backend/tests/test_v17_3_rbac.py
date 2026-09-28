"""V17.3 — Enterprise RBAC, Session Management & Admin Controls.

Follows the same env-var-at-import-time pattern as
test_v17_2_security_hardening.py — see that file's docstring for why
(and run this file on its own if in doubt: `pytest
tests/test_v17_3_rbac.py`).
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v17_3.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"
os.environ["AUTH_RATE_LIMIT_ATTEMPTS"] = "1000"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}
PW = "correct-horse-battery-1"


def _register_candidate(client, email, password=PW):
    return client.post(
        "/api/v1/auth/candidate/register",
        json={"email": email, "password": password, "password_confirm": password, "full_name": "V17.3 Tester"},
    )


def _login_candidate(client, email, password=PW):
    return client.post("/api/v1/auth/candidate/login", json={"email": email, "password": password})


def _user_id(email):
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.domain import User

    db = SessionLocal()
    try:
        return db.scalar(select(User).where(User.email == email)).id
    finally:
        db.close()


def _set_role(email, role):
    """Test-only helper: promote a user directly via the DB, mirroring
    what POST /admin/users/{id}/role does, without depending on that
    endpoint's own request/response shape here."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.domain import User

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        user.role = role
        db.commit()
    finally:
        db.close()


# --------------------------- Roles & permissions -----------------------------

def test_permission_catalog_is_reachable_with_admin_key():
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/rbac/permissions", headers=ADMIN_HEADERS)
        assert response.status_code == 200
        permissions = {row["permission"] for row in response.json()}
        # A representative sample from the brief's exact list.
        for expected in ("jobs.create", "jobs.publish", "users.read", "recruiters.approve", "admin.audit.read"):
            assert expected in permissions


def test_rbac_endpoints_reject_missing_auth():
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/rbac/roles")
        assert response.status_code == 401


def test_rbac_endpoints_reject_a_jwt_without_the_required_permission():
    with TestClient(app) as client:
        email = "v17-3-candidate@example.com"
        _register_candidate(client, email)
        login = _login_candidate(client, email)
        token = login.json()["access_token"]

        response = client.get("/api/v1/admin/rbac/roles", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403


def test_roles_listing_includes_new_v17_3_roles_in_hierarchy_order():
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/rbac/roles", headers=ADMIN_HEADERS)
        assert response.status_code == 200
        roles = [row["role"] for row in response.json()]
        assert roles == [
            "candidate", "recruiter", "recruiter_manager", "recruiter_admin",
            "support_admin", "system_admin", "super_admin",
        ]


def test_grant_and_revoke_role_permission_takes_effect_immediately():
    with TestClient(app) as client:
        # "recruiter" has no dot-namespaced permissions by default.
        before = client.get("/api/v1/admin/rbac/roles", headers=ADMIN_HEADERS).json()
        recruiter_row = next(r for r in before if r["role"] == "recruiter")
        assert "analytics.read" not in recruiter_row["permissions"]

        grant = client.post(
            "/api/v1/admin/rbac/roles/recruiter/grant",
            headers=ADMIN_HEADERS,
            json={"permission": "analytics.read"},
        )
        assert grant.status_code == 200
        assert "analytics.read" in grant.json()["permissions"]

        after_grant = client.get("/api/v1/admin/rbac/roles", headers=ADMIN_HEADERS).json()
        recruiter_row = next(r for r in after_grant if r["role"] == "recruiter")
        assert "analytics.read" in recruiter_row["permissions"]

        revoke = client.post(
            "/api/v1/admin/rbac/roles/recruiter/revoke",
            headers=ADMIN_HEADERS,
            json={"permission": "analytics.read"},
        )
        assert revoke.status_code == 200
        assert "analytics.read" not in revoke.json()["permissions"]


def test_granting_an_unknown_permission_is_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/admin/rbac/roles/recruiter/grant",
            headers=ADMIN_HEADERS,
            json={"permission": "not.a.real.permission"},
        )
        assert response.status_code == 400


def test_a_jwt_gains_a_granted_permission_without_relogging_in():
    """The whole point of DB-backed overrides: a grant takes effect for
    an already-issued token on its very next request, no re-login."""
    with TestClient(app) as client:
        email = "v17-3-system-admin@example.com"
        _register_candidate(client, email)
        login = _login_candidate(client, email)
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        _set_role(email, "system_admin")
        # system_admin already has roles.manage by default (see DOT_ROLE_PERMISSIONS).
        response = client.get("/api/v1/admin/rbac/roles", headers=headers)
        assert response.status_code == 200


# --------------------------------- Sessions -----------------------------------

def test_sessions_endpoint_reports_device_browser_os_and_current_flag():
    with TestClient(app) as client:
        email = "v17-3-sessions@example.com"
        _register_candidate(client, email)
        chrome_ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        login = client.post(
            "/api/v1/auth/candidate/login",
            json={"email": email, "password": PW},
            headers={"User-Agent": chrome_ua},
        )
        token = login.json()["access_token"]

        response = client.get("/api/v1/auth/sessions", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        sessions = response.json()
        assert len(sessions) >= 1
        current = next(s for s in sessions if s["is_current"])
        assert current["browser"] == "Chrome"
        assert current["os"] == "Windows"
        assert current["country"] is None  # no geo-IP lookup is performed — see docstring


def test_admin_can_list_all_sessions_system_wide():
    with TestClient(app) as client:
        email = "v17-3-allsessions@example.com"
        _register_candidate(client, email)
        _login_candidate(client, email)

        response = client.get("/api/v1/admin/rbac/sessions", headers=ADMIN_HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert "results" in body and "total" in body
        assert any(r["user_email"] == email for r in body["results"])


def test_admin_force_logout_revokes_every_session_for_a_user():
    with TestClient(app) as client:
        email = "v17-3-forcelogout@example.com"
        _register_candidate(client, email)
        login = _login_candidate(client, email)
        token = login.json()["access_token"]
        uid = _user_id(email)

        force = client.post(f"/api/v1/admin/rbac/users/{uid}/force-logout", headers=ADMIN_HEADERS)
        assert force.status_code == 200
        assert force.json()["sessions_revoked"] >= 1

        # V25.6 behaviour change: force-logout revokes the UserSession row AND, because every
        # authenticated request now checks that the token's `sid` session is still active
        # (app.core.security.access_token_session_is_active), the already-issued access token
        # stops working immediately instead of surviving until it expires (<= 15 minutes).
        # Before V25.6 this test asserted the opposite (token still authenticates).
        me = client.get("/api/v1/auth/sessions", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 401


# ------------------------------ User management --------------------------------

def test_suspend_blocks_login_and_unsuspend_restores_it():
    with TestClient(app) as client:
        email = "v17-3-suspend@example.com"
        _register_candidate(client, email)
        uid = _user_id(email)

        suspend = client.post(
            f"/api/v1/admin/rbac/users/{uid}/suspend",
            headers=ADMIN_HEADERS,
            json={"reason": "policy review"},
        )
        assert suspend.status_code == 200

        blocked_login = _login_candidate(client, email)
        assert blocked_login.status_code in (401, 403)

        unsuspend = client.post(f"/api/v1/admin/rbac/users/{uid}/unsuspend", headers=ADMIN_HEADERS)
        assert unsuspend.status_code == 200
        assert unsuspend.json()["was_suspended"] is True

        restored_login = _login_candidate(client, email)
        assert restored_login.status_code == 200


def test_suspend_requires_a_reason():
    with TestClient(app) as client:
        email = "v17-3-suspend-noreason@example.com"
        _register_candidate(client, email)
        uid = _user_id(email)

        response = client.post(f"/api/v1/admin/rbac/users/{uid}/suspend", headers=ADMIN_HEADERS, json={"reason": ""})
        assert response.status_code == 422


def test_admin_reset_password_issues_an_otp_without_revealing_or_setting_a_password():
    with TestClient(app) as client:
        email = "v17-3-resetpw@example.com"
        _register_candidate(client, email)
        uid = _user_id(email)

        response = client.post(f"/api/v1/admin/rbac/users/{uid}/reset-password", headers=ADMIN_HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body == {"user_id": uid, "reset_email_sent": True}  # no password/temp-password value returned

        from sqlalchemy import select

        from app.db.session import SessionLocal
        from app.models.domain import EmailVerification

        db = SessionLocal()
        try:
            row = db.scalar(
                select(EmailVerification)
                .where(EmailVerification.user_id == uid, EmailVerification.purpose == "reset_password")
                .order_by(EmailVerification.id.desc())
            )
            assert row is not None
            assert row.consumed is False
        finally:
            db.close()


# -------------------------------- Audit log export ------------------------------

def test_audit_log_export_json_and_csv():
    with TestClient(app) as client:
        email = "v17-3-audit@example.com"
        _register_candidate(client, email)
        uid = _user_id(email)
        client.post(f"/api/v1/admin/rbac/users/{uid}/suspend", headers=ADMIN_HEADERS, json={"reason": "test"})

        json_response = client.get("/api/v1/admin/rbac/audit-logs/export", headers=ADMIN_HEADERS)
        assert json_response.status_code == 200
        rows = json_response.json()
        assert any(r["action"] == "admin_suspend_user" for r in rows)

        csv_response = client.get(
            "/api/v1/admin/rbac/audit-logs/export", headers=ADMIN_HEADERS, params={"format": "csv"}
        )
        assert csv_response.status_code == 200
        assert csv_response.headers["content-type"].startswith("text/csv")
        assert "admin_suspend_user" in csv_response.text


def test_audit_log_export_search_filter():
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/admin/rbac/audit-logs/export",
            headers=ADMIN_HEADERS,
            params={"search": "this-should-match-nothing-xyz"},
        )
        assert response.status_code == 200
        assert response.json() == []
