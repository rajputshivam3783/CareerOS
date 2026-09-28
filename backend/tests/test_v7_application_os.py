"""V7 Application OS smoke test: publishing a job, updating its
deadline, saving it as a candidate, and confirming a deadline
notification is created — then that it doesn't duplicate on a second
scan (idempotency)."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_careeros.db")
os.environ.setdefault("AUTO_VERIFY_EMAIL_IN_TESTS", "true")

from datetime import date, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"x-admin-key": "change-this-admin-key"}


def _register_and_login(client: TestClient, email: str) -> str:
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "V7 Tester"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    return login.json()["access_token"]


def test_deadline_notification_created_for_saved_job_and_not_duplicated():
    with TestClient(app) as client:
        token = _register_and_login(client, "v7tester@example.com")
        auth_headers = {"Authorization": f"Bearer {token}"}

        create = client.post(
            "/api/v1/admin/ingest",
            headers=ADMIN_HEADERS,
            json={"title": "V7 Test Recruitment", "organization": "Test Department"},
        )
        assert create.status_code == 201
        job_id = create.json()["job_id"]

        publish = client.post(f"/api/v1/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)
        assert publish.status_code == 200

        near_deadline = (date.today() + timedelta(days=1)).isoformat()
        patch = client.patch(
            f"/api/v1/admin/jobs/{job_id}",
            headers=ADMIN_HEADERS,
            json={"deadline": near_deadline},
        )
        assert patch.status_code == 200

        save = client.post(f"/api/v1/saved-jobs/{job_id}", headers=auth_headers)
        assert save.status_code == 201

        scan_1 = client.post("/api/v1/admin/notifications/scan", headers=ADMIN_HEADERS)
        assert scan_1.status_code == 200
        assert scan_1.json()["notifications_created"] >= 1

        notifications = client.get("/api/v1/notifications", headers=auth_headers)
        assert notifications.status_code == 200
        # V23.5 fix: GET /notifications now correctly resolves to
        # app.api.notifications' V23.1 implementation — `{"items": [...],
        # "total": ..., ...}`, with each item keyed "type" rather than
        # "notification_type" — instead of app.api.platform's old
        # shadowing V7 duplicate (a confirmed bug, removed; see
        # docs/V23_BUG_REPORT.md). Same fix as test_mark_notification_read
        # above.
        deadline_notifications = [n for n in notifications.json()["items"] if n["type"] == "deadline"]
        assert len(deadline_notifications) == 1
        assert deadline_notifications[0]["job_id"] == job_id

        # Running the scan again must not create a duplicate for the same user+job+type.
        scan_2 = client.post("/api/v1/admin/notifications/scan", headers=ADMIN_HEADERS)
        assert scan_2.status_code == 200

        notifications_again = client.get("/api/v1/notifications", headers=auth_headers)
        deadline_notifications_again = [
            n for n in notifications_again.json()["items"] if n["type"] == "deadline" and n["job_id"] == job_id
        ]
        assert len(deadline_notifications_again) == 1


def test_mark_notification_read():
    with TestClient(app) as client:
        token = _register_and_login(client, "v7reader@example.com")
        auth_headers = {"Authorization": f"Bearer {token}"}

        create = client.post(
            "/api/v1/admin/ingest",
            headers=ADMIN_HEADERS,
            json={"title": "V7 Read Test Recruitment", "organization": "Test Department"},
        )
        job_id = create.json()["job_id"]
        client.post(f"/api/v1/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)
        client.patch(
            f"/api/v1/admin/jobs/{job_id}",
            headers=ADMIN_HEADERS,
            json={"deadline": (date.today() + timedelta(days=2)).isoformat()},
        )
        client.post(f"/api/v1/saved-jobs/{job_id}", headers=auth_headers)
        client.post("/api/v1/admin/notifications/scan", headers=ADMIN_HEADERS)

        unread_before = client.get("/api/v1/notifications/unread-count", headers=auth_headers).json()
        # V23.5 fix: this test previously asserted the "unread" key,
        # which only matched app.api.platform's old V7 GET
        # /notifications/unread-count. That route was a shadowing
        # duplicate of app.api.notifications' V23.1 version (same path,
        # registered earlier, silently winning every request — a
        # confirmed bug, see docs/V23_BUG_REPORT.md) and has been
        # removed; the canonical route (and the frontend, which was
        # always built against it) uses "unread_count".
        assert unread_before["unread_count"] >= 1

        mark_all = client.post("/api/v1/notifications/read-all", headers=auth_headers)
        assert mark_all.status_code == 200

        unread_after = client.get("/api/v1/notifications/unread-count", headers=auth_headers).json()
        assert unread_after["unread_count"] == 0
