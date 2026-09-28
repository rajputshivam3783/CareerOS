"""V23.1 — Notification Infrastructure & Event System tests.

Covers: event-triggered notification creation (application created/
status changed, interview scheduled/updated), the new /notifications
list + /notifications/unread-count + /notifications/{id}/unread
endpoints, that the existing V19.4 /notifications/{id}/read,
/notifications/read-all, and DELETE /notifications/{id} endpoints
still work unmodified, ownership isolation, idempotency/dedup, and —
the most important one — that a notification-layer failure never
breaks the application/interview operation that triggered it.
"""

import os
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v23_1.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

_counter = {"n": 0}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _register_and_login(client, email_prefix: str) -> dict:
    _counter["n"] += 1
    email = f"{email_prefix}{_counter['n']}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Test User"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_application(client, headers, **overrides):
    payload = {"company": "Acme", "job_title": "Engineer", "status": "APPLIED"}
    payload.update(overrides)
    resp = client.post("/api/v1/applications", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _notifications_for(client, headers, **params):
    resp = client.get("/api/v1/notifications", headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Event-triggered creation
# ---------------------------------------------------------------------------


def test_application_created_triggers_notification(client):
    headers = _register_and_login(client, "v23_1appcreate")
    a = _create_application(client, headers)

    data = _notifications_for(client, headers, category="APPLICATION")
    matches = [n for n in data["items"] if n["type"] == "application_created"]
    assert len(matches) == 1
    assert matches[0]["action_url"] == f"/applications/{a['id']}"
    assert matches[0]["category"] == "APPLICATION"
    assert matches[0]["read"] is False


def test_application_status_changed_triggers_notification(client):
    headers = _register_and_login(client, "v23_1statuschange")
    a = _create_application(client, headers, status="APPLIED")
    resp = client.post(f"/api/v1/applications/{a['id']}/status", headers=headers, json={"status": "INTERVIEW"})
    assert resp.status_code == 200, resp.text

    data = _notifications_for(client, headers, category="APPLICATION")
    matches = [n for n in data["items"] if n["type"] == "application_status_changed"]
    assert len(matches) == 1
    assert matches[0]["priority"] == "HIGH"  # INTERVIEW is a HIGH-priority transition
    assert matches[0]["metadata"]["new_status"] == "INTERVIEW"


def test_application_creation_does_not_double_notify_with_status_change_notification(client):
    """The creation-time history row (old_status=None) must not also
    produce an application_status_changed notification — only
    application_created."""
    headers = _register_and_login(client, "v23_1nodup")
    _create_application(client, headers, status="APPLIED")

    data = _notifications_for(client, headers)
    status_changed = [n for n in data["items"] if n["type"] == "application_status_changed"]
    assert status_changed == []


def test_interview_scheduled_and_updated_trigger_notifications(client):
    headers = _register_and_login(client, "v23_1interview")
    a = _create_application(client, headers, status="INTERVIEW")
    soon = (datetime.utcnow() + timedelta(days=1)).isoformat()
    iv = client.post(
        f"/api/v1/applications/{a['id']}/interviews", headers=headers, json={"interview_type": "technical", "scheduled_at": soon}
    ).json()

    data = _notifications_for(client, headers, category="INTERVIEW")
    scheduled = [n for n in data["items"] if n["type"] == "interview_scheduled"]
    assert len(scheduled) == 1
    assert scheduled[0]["priority"] == "HIGH"
    assert scheduled[0]["action_url"] == f"/applications/{a['id']}"

    client.patch(f"/api/v1/applications/{a['id']}/interviews/{iv['id']}", headers=headers, json={"result": "completed"})

    data2 = _notifications_for(client, headers, category="INTERVIEW")
    updated = [n for n in data2["items"] if n["type"] == "interview_updated"]
    assert len(updated) == 1
    assert updated[0]["metadata"]["result"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Listing / filtering / pagination
# ---------------------------------------------------------------------------


def test_list_notifications_unread_filter_and_pagination(client):
    headers = _register_and_login(client, "v23_1list")
    for i in range(3):
        _create_application(client, headers, company=f"Company{i}")

    all_data = _notifications_for(client, headers, limit=2, offset=0)
    assert len(all_data["items"]) == 2
    assert all_data["total"] >= 3
    assert all_data["has_more"] is True

    unread_data = _notifications_for(client, headers, unread_only=True)
    assert all(n["read"] is False for n in unread_data["items"])


def test_list_notifications_invalid_category_rejected(client):
    headers = _register_and_login(client, "v23_1badcat")
    resp = client.get("/api/v1/notifications", headers=headers, params={"category": "NOT_A_CATEGORY"})
    assert resp.status_code == 422


def test_unread_count_endpoint_matches_list(client):
    headers = _register_and_login(client, "v23_1unreadcount")
    _create_application(client, headers)
    _create_application(client, headers, company="Other Co")

    count_resp = client.get("/api/v1/notifications/unread-count", headers=headers)
    assert count_resp.status_code == 200
    list_resp = _notifications_for(client, headers, unread_only=True)
    assert count_resp.json()["unread_count"] == list_resp["total"]


# ---------------------------------------------------------------------------
# Read / unread / read-all / delete — new + reused V19.4 endpoints
# ---------------------------------------------------------------------------


def test_mark_read_then_unread_round_trip(client):
    headers = _register_and_login(client, "v23_1readtrip")
    _create_application(client, headers)
    n = _notifications_for(client, headers)["items"][0]
    nid = n["id"]

    read_resp = client.post(f"/api/v1/notifications/{nid}/read", headers=headers)  # existing V19.4 endpoint, reused as-is
    assert read_resp.status_code == 200
    assert read_resp.json()["read"] is True

    unread_resp = client.post(f"/api/v1/notifications/{nid}/unread", headers=headers)  # new V23.1 endpoint
    assert unread_resp.status_code == 200
    assert unread_resp.json()["read"] is False
    assert unread_resp.json()["read_at"] is None


def test_mark_all_read_existing_endpoint_still_works(client):
    headers = _register_and_login(client, "v23_1readall")
    _create_application(client, headers)
    _create_application(client, headers, company="Second Co")

    resp = client.post("/api/v1/notifications/read-all", headers=headers)  # existing V19.4 endpoint
    assert resp.status_code == 200
    assert resp.json()["marked_read"] >= 2

    unread = _notifications_for(client, headers, unread_only=True)
    assert unread["total"] == 0


def test_delete_notification_existing_endpoint_still_works(client):
    headers = _register_and_login(client, "v23_1delete")
    _create_application(client, headers)
    n = _notifications_for(client, headers)["items"][0]

    resp = client.delete(f"/api/v1/notifications/{n['id']}", headers=headers)  # existing V19.4 endpoint
    assert resp.status_code == 204

    remaining_ids = [x["id"] for x in _notifications_for(client, headers)["items"]]
    assert n["id"] not in remaining_ids


# ---------------------------------------------------------------------------
# Ownership isolation (IDOR)
# ---------------------------------------------------------------------------


def test_notifications_are_isolated_across_users(client):
    headers_a = _register_and_login(client, "v23_1owner_a")
    headers_b = _register_and_login(client, "v23_1owner_b")
    _create_application(client, headers_a)
    n = _notifications_for(client, headers_a)["items"][0]

    cross_list = _notifications_for(client, headers_b)
    assert n["id"] not in [x["id"] for x in cross_list["items"]]

    assert client.post(f"/api/v1/notifications/{n['id']}/read", headers=headers_b).status_code == 404
    assert client.post(f"/api/v1/notifications/{n['id']}/unread", headers=headers_b).status_code == 404
    assert client.delete(f"/api/v1/notifications/{n['id']}", headers=headers_b).status_code == 404


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_duplicate_dedupe_key_does_not_create_a_second_notification(client):
    from app.db.session import SessionLocal
    from app.notifications import service as notification_service

    headers = _register_and_login(client, "v23_1dedupe")
    me = client.get("/api/v1/auth/me", headers=headers).json()
    user_id = me["id"]

    db = SessionLocal()
    try:
        first = notification_service.create_notification(
            db, user_id, notification_type="test_event", title="Test", message="Test message",
            category="SYSTEM", dedupe_key="test_event:dedupe_case",
        )
        second = notification_service.create_notification(
            db, user_id, notification_type="test_event", title="Test (duplicate attempt)", message="Should not be created",
            category="SYSTEM", dedupe_key="test_event:dedupe_case",
        )
        assert first is not None
        assert second is None  # idempotent no-op, not a duplicate row or an error
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Failure isolation — the most important property this version adds
# ---------------------------------------------------------------------------


def test_application_creation_succeeds_even_if_notification_creation_fails(client, monkeypatch):
    from app.notifications import service as notification_service

    headers = _register_and_login(client, "v23_1failsafe")

    def boom(db, *args, **kwargs):
        raise RuntimeError("simulated notification infrastructure failure")

    monkeypatch.setattr(notification_service, "create_notification", boom)

    resp = client.post("/api/v1/applications", headers=headers, json={"company": "Acme", "job_title": "Engineer", "status": "APPLIED"})
    assert resp.status_code == 201, resp.text  # the application itself must still be created successfully


def test_status_change_succeeds_even_if_notification_creation_fails(client, monkeypatch):
    from app.notifications import service as notification_service

    headers = _register_and_login(client, "v23_1failsafe2")
    a = _create_application(client, headers, status="APPLIED")

    def boom(db, *args, **kwargs):
        raise RuntimeError("simulated notification infrastructure failure")

    monkeypatch.setattr(notification_service, "create_notification", boom)

    resp = client.post(f"/api/v1/applications/{a['id']}/status", headers=headers, json={"status": "INTERVIEW"})
    assert resp.status_code == 200, resp.text  # the status change itself must still succeed
    assert resp.json()["status"] == "INTERVIEW"
