"""V25.5 — Platform Scale, Observability & Reliability.

Covers the new durable dead-letter tracking (app.reliability), the
GET /admin/observability aggregate dashboard, and a V25.4 regression
check (Career Agent must still work unchanged).
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v25_5.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.reliability import dead_letter  # noqa: E402
from app.scheduler import _with_retry  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}
PW = "password12345!"
API = "/api/v1"


def _register(client, suffix, role="candidate"):
    email = f"v255{suffix}@example.com"
    client.post(
        f"{API}/auth/register",
        json={"email": email, "password": PW, "password_confirm": PW, "full_name": f"User {suffix}"},
    )
    login = client.post(f"{API}/auth/login", json={"email": email, "password": PW})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Dead-letter durability
# ---------------------------------------------------------------------------


class TestDeadLetter:
    def test_transient_failure_then_success_marks_recovered(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("transient boom")
            return "ok"

        with TestClient(app):
            _with_retry("v255_flaky_job", flaky, retries=3, backoff_seconds=0)
            db = SessionLocal()
            try:
                summary = dead_letter.summarize(db)
            finally:
                db.close()

        assert summary["counts_by_status"].get("recovered", 0) >= 1
        assert "v255_flaky_job" not in summary["open_counts_by_job"]

    def test_permanent_failure_stays_open_with_correct_retry_count(self):
        def always_fails():
            raise RuntimeError("permanent boom")

        with TestClient(app):
            _with_retry("v255_perm_fail_job", always_fails, retries=2, backoff_seconds=0)
            db = SessionLocal()
            try:
                summary = dead_letter.summarize(db)
            finally:
                db.close()

        assert summary["open_counts_by_job"].get("v255_perm_fail_job") == 1
        matching = [r for r in summary["recent_failures"] if r["job_name"] == "v255_perm_fail_job"]
        assert len(matching) == 1
        assert matching[0]["status"] == "failed"
        assert matching[0]["retry_count"] == 2
        assert matching[0]["next_retry_at"] is None

    def test_idempotency_key_scopes_failures_to_distinct_work_items(self):
        db = SessionLocal()
        try:
            dead_letter.record_failure(db, job_name="v255_ingest", error="boom A", idempotency_key="source_a")
            dead_letter.record_failure(db, job_name="v255_ingest", error="boom B", idempotency_key="source_b")
            summary = dead_letter.summarize(db)
        finally:
            db.close()
        # Two distinct idempotency keys under the same job_name must
        # not collapse into a single row — each failing source stays
        # independently visible (spec section 27: "one broken source
        # must not stop all ingestion" implies it must also not hide
        # the others' failures).
        assert summary["open_counts_by_job"].get("v255_ingest") == 2

    def test_repeated_failure_same_key_upserts_not_duplicates(self):
        db = SessionLocal()
        try:
            dead_letter.record_failure(db, job_name="v255_retry_same", error="first", idempotency_key="x")
            dead_letter.record_failure(db, job_name="v255_retry_same", error="second", idempotency_key="x")
            summary = dead_letter.summarize(db)
        finally:
            db.close()
        assert summary["open_counts_by_job"].get("v255_retry_same") == 1
        matching = [r for r in summary["recent_failures"] if r["job_name"] == "v255_retry_same"]
        assert matching[0]["retry_count"] == 2


# ---------------------------------------------------------------------------
# GET /admin/observability
# ---------------------------------------------------------------------------


class TestObservabilityDashboard:
    def test_requires_platform_admin(self):
        with TestClient(app) as client:
            headers = _register(client, "obsuser")
            resp = client.get(f"{API}/admin/observability", headers=headers)
        assert resp.status_code == 403

    def test_admin_key_gets_full_shape(self):
        with TestClient(app) as client:
            resp = client.get(f"{API}/admin/observability", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        for key in ("api", "system_health", "background_jobs", "database"):
            assert key in body
        assert "dead_letter" in body["background_jobs"]
        assert "status" in body["system_health"]

    def test_never_exposes_admin_key_or_secrets(self):
        with TestClient(app) as client:
            resp = client.get(f"{API}/admin/observability", headers=ADMIN_HEADERS)
        assert "change-this-admin-key" not in resp.text
        assert "jwt_secret" not in resp.text.lower()

    def test_since_hours_window_is_respected(self):
        with TestClient(app) as client:
            resp = client.get(f"{API}/admin/observability?since_hours=1", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["window_hours"] == 1


# ---------------------------------------------------------------------------
# V25.4 regression — Career Agent must still work unchanged
# ---------------------------------------------------------------------------


class TestRegression:
    def test_career_agent_chat_endpoint_still_reachable(self):
        with TestClient(app) as client:
            headers = _register(client, "regression")
            convo = client.post(f"{API}/career-agent/conversations", headers=headers, json={})
            assert convo.status_code in (200, 201)
            conversation_id = convo.json()["id"]
            resp = client.post(
                f"{API}/career-agent/conversations/{conversation_id}/messages",
                headers=headers,
                json={"message": "hello"},
            )
        # V25.4 behavior preserved: either a normal 200 (grounded reply)
        # or a 503 if no AI provider is configured in this environment —
        # never a 500, and never blocked by anything V25.5 added.
        assert resp.status_code in (200, 503)
