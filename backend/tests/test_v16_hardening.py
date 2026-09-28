"""V16 — backend hardening: request IDs, metrics, audit actor
tracking, dual-mode admin auth, and the new permission layer."""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v16.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.core.rbac import has_permission, permissions_for_role  # noqa: E402
from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}


def _register_and_login(client, email, role=None):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "V16 Tester"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    token = login.json()["access_token"]
    if role:
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        client.post(f"/api/v1/admin/users/{me.json()['id']}/role", headers=ADMIN_HEADERS, json={"role": role})
    return token


def test_live_and_metrics_endpoints():
    with TestClient(app) as client:
        live = client.get("/live")
        assert live.status_code == 200
        assert live.json() == {"status": "alive"}

        # Hit something first so at least one series exists.
        client.get("/health")
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "careeros_http_requests_total" in metrics.text
        assert "careeros_process_uptime_seconds" in metrics.text


def test_request_id_is_generated_and_echoed():
    with TestClient(app) as client:
        response = client.get("/health")
        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) > 0


def test_request_id_is_propagated_when_provided():
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
        assert response.headers["X-Request-ID"] == "trace-abc-123"


def test_admin_key_still_works_and_is_rate_limited():
    from app.core.config import settings

    # tests/conftest.py raises AUTH_RATE_LIMIT_ATTEMPTS to 1000
    # process-wide so other files' fixture-heavy setup doesn't trip
    # unrelated limits — which would otherwise make this test's own
    # 15 wrong-key attempts never actually reach a real limit. Patch a
    # real, small value locally for just this test.
    original = settings.auth_rate_limit_attempts
    settings.auth_rate_limit_attempts = 10
    try:
        with TestClient(app) as client:
            ok = client.get("/api/v1/admin/review", headers=ADMIN_HEADERS)
            assert ok.status_code == 200

            # Wrong key is rejected...
            bad = client.get("/api/v1/admin/review", headers={"X-Admin-Key": "wrong"})
            assert bad.status_code == 401

            # ...and enough wrong attempts get rate-limited (V16 closes the
            # previously-unlimited brute-force gap on the shared admin key).
            last_status = None
            for _ in range(15):
                last_status = client.get("/api/v1/admin/review", headers={"X-Admin-Key": "wrong"}).status_code
            assert last_status == 429
    finally:
        settings.auth_rate_limit_attempts = original


def test_admin_jwt_path_grants_access_and_records_actor():
    with TestClient(app) as client:
        token = _register_and_login(client, "v16admin@example.com", role="admin")
        headers = {"Authorization": f"Bearer {token}"}

        via_jwt = client.get("/api/v1/admin/review", headers=headers)
        assert via_jwt.status_code == 200

        # A non-admin bearer token must not work on admin routes.
        candidate_token = _register_and_login(client, "v16candidate@example.com")
        denied = client.get(
            "/api/v1/admin/review", headers={"Authorization": f"Bearer {candidate_token}"}
        )
        assert denied.status_code == 403


def test_audit_log_endpoint_records_actor_for_admin_jwt_actions():
    with TestClient(app) as client:
        token = _register_and_login(client, "v16auditor@example.com", role="admin")
        headers = {"Authorization": f"Bearer {token}"}
        me = client.get("/api/v1/auth/me", headers=headers).json()

        # Trigger a real audited admin action via the JWT path.
        role_change = client.post(f"/api/v1/admin/users/{me['id']}/role", headers=headers, json={"role": "admin"})
        assert role_change.status_code == 200

        logs = client.get("/api/v1/admin/audit-logs", headers=ADMIN_HEADERS, params={"action": "set_user_role"})
        assert logs.status_code == 200
        body = logs.json()
        assert body["total"] >= 1
        row = body["results"][0]
        assert row["actor_type"] == "user"
        assert row["request_id"]


def test_failed_login_is_audited():
    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/register",
            json={"email": "v16faillogin@example.com", "password": "password12345!", "password_confirm": "password12345!", "full_name": "Test"},
        )
        client.post(
            "/api/v1/auth/login",
            json={"email": "v16faillogin@example.com", "password": "wrong-password"},
        )
        logs = client.get(
            "/api/v1/admin/audit-logs",
            headers=ADMIN_HEADERS,
            params={"action": "login_failed"},
        )
        assert logs.status_code == 200
        assert logs.json()["total"] >= 1


def test_rbac_permission_layer():
    assert "jobs:publish" in permissions_for_role("admin")
    assert "jobs:publish" not in permissions_for_role("candidate")
    assert "jobs:publish" not in permissions_for_role("recruiter")

    class _FakeUser:
        role = "recruiter"

    assert has_permission(_FakeUser(), "jobs:manage_own") is True
    assert has_permission(_FakeUser(), "users:manage_roles") is False
