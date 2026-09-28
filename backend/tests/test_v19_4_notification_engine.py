"""V19.4 — Government Automation & Notification Engine: subscriptions,
preferences, the notification channel abstraction (in-app + email
fully implemented; push/sms/whatsapp registered as not_implemented),
the automation engine's subscription-matching + lifecycle-event
fan-out, the reminder engine, the notification center, and the admin
tooling (queue/retry/stats/logs/templates/manual run/health).

Follows the same self-contained (own sqlite file) pattern as every
other V19.x test file, and stays under 10 total admin-key calls in one
module-scoped fixture for the same reason
test_v19_3_government_portal.py does (see that file / app/core/
rate_limit.py's in-memory "admin-key" bucket: 10 calls/60s/IP).
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v19_4.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.notification_channels import CHANNELS  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}


def _register_and_login(client, email, name):
    client.post("/api/v1/auth/register", json={
        "email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": name,
    })
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def seeded():
    """Five admin-key calls total in the fixture (a 6th, the template
    PUT, is exercised by its own test instead — see
    test_admin_template_upsert_took_effect — keeping the whole file at
    exactly 10, the in-memory "admin-key" bucket's per-60s ceiling):

    1. ingest job A (SSC, published) — candidate subscribes to organization "SSC" first
    2. publish A
    3. ingest job B (UPSC, published) — candidate saves this one directly (no subscription)
    4. publish B
    5. POST /admin/automation/run — fires the automation scan for both jobs

    Everything else (auth, subscriptions, saved-jobs, reminders,
    notification-center actions) is free (non-admin-key) traffic.
    """
    with TestClient(app) as client:
        candidate = _register_and_login(client, "v194-candidate@example.com", "V194 Candidate")

        client.post("/api/v1/subscriptions", headers=candidate, json={"subscription_type": "organization", "value": "SSC"})

        a = client.post("/api/v1/admin/ingest", headers=ADMIN_HEADERS, json={
            "title": "SSC CGL 2026", "organization": "SSC", "job_type": "Government", "source_reference": "v19-4-a",
        }).json()["job_id"]
        client.post(f"/api/v1/admin/jobs/{a}/publish", headers=ADMIN_HEADERS)

        b = client.post("/api/v1/admin/ingest", headers=ADMIN_HEADERS, json={
            "title": "UPSC Civil Services 2026", "organization": "UPSC", "job_type": "Government",
            "deadline": "2099-01-01", "source_reference": "v19-4-b",
        }).json()["job_id"]
        client.post(f"/api/v1/admin/jobs/{b}/publish", headers=ADMIN_HEADERS)
        client.post(f"/api/v1/saved-jobs/{b}", headers=candidate)

        run = client.post("/api/v1/admin/automation/run", headers=ADMIN_HEADERS)

        yield {"client": client, "candidate": candidate, "a": a, "b": b, "automation_result": run.json()}


# --- Channel abstraction -----------------------------------------------------

def test_channel_registry_has_all_five_with_correct_implemented_flags():
    assert set(CHANNELS) == {"in_app", "email", "push", "sms", "whatsapp"}
    assert CHANNELS["in_app"].implemented is True
    assert CHANNELS["email"].implemented is True
    assert CHANNELS["push"].implemented is False
    assert CHANNELS["sms"].implemented is False
    assert CHANNELS["whatsapp"].implemented is False


def test_unimplemented_channels_report_not_implemented_without_raising(seeded):
    from app.models.domain import User
    with TestClient(app) as _:
        pass  # no extra admin calls needed; reuse seeded's own session context implicitly via ORM-free check
    # Constructing a bare deliver() call needs a user + db session; use the
    # already-seeded candidate's user row via a fresh session-free check
    # instead: PushChannel/SMSChannel/WhatsAppChannel are pure functions of
    # their inputs and never touch the DB before returning, so a None db
    # is safe here.
    result = CHANNELS["push"].deliver(None, User(id=1, email="x@example.com", password_hash="x", full_name="X"), title="t", body="b")
    assert result.status == "not_implemented"


# --- Subscriptions ------------------------------------------------------------

def test_subscription_created_and_listed(seeded):
    resp = seeded["client"].get("/api/v1/subscriptions", headers=seeded["candidate"])
    assert resp.status_code == 200
    subs = resp.json()
    assert any(s["subscription_type"] == "organization" and s["value"] == "SSC" for s in subs)


def test_subscription_requires_value_for_non_recruitment_types(seeded):
    resp = seeded["client"].post("/api/v1/subscriptions", headers=seeded["candidate"],
                                  json={"subscription_type": "organization"})
    assert resp.status_code == 422


# --- Preferences ---------------------------------------------------------------

def test_preferences_default_to_everything_on(seeded):
    resp = seeded["client"].get("/api/v1/notifications/preferences", headers=seeded["candidate"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["email_enabled"] is True
    assert body["in_app_enabled"] is True
    assert body["digest_mode"] == "instant"


def test_preferences_update_persists(seeded):
    resp = seeded["client"].put("/api/v1/notifications/preferences", headers=seeded["candidate"],
                                json={"email_enabled": False, "digest_mode": "daily_digest"})
    assert resp.status_code == 200
    assert resp.json()["email_enabled"] is False
    refetched = seeded["client"].get("/api/v1/notifications/preferences", headers=seeded["candidate"]).json()
    assert refetched["email_enabled"] is False
    assert refetched["digest_mode"] == "daily_digest"
    # restore for later tests in this module
    seeded["client"].put("/api/v1/notifications/preferences", headers=seeded["candidate"], json={"email_enabled": True})


# --- Automation engine: subscription match + saved-job interest ---------------

def test_automation_notified_subscribed_and_saved_job_users(seeded):
    # Job A matched via the organization="SSC" subscription; job B via
    # the direct saved-job interest (no subscription needed for that path).
    assert seeded["automation_result"]["recruitments_scanned"] == 2
    assert seeded["automation_result"]["recruitment_notifications"] >= 2


def test_notification_center_shows_both_jobs(seeded):
    resp = seeded["client"].get("/api/v1/notifications/center?status=all", headers=seeded["candidate"])
    assert resp.status_code == 200
    body = resp.json()
    job_ids = {item["job_id"] for item in body["items"]}
    assert seeded["a"] in job_ids
    assert seeded["b"] in job_ids
    assert body["unread_count"] == body["total"]  # nothing read yet


def test_automation_scan_is_idempotent_on_rerun_without_new_jobs(seeded):
    # Re-running with no new jobs/updates since the cursor moved past
    # both A and B should notify nobody a second time. Calls the
    # service function directly (bypassing HTTP) so this doesn't cost
    # another admin-key-rate-limited request — the file is already at
    # its 10-calls-per-module budget via the admin-only HTTP tests below.
    from app.db.session import SessionLocal
    from app.services.automation import run_automation_scan

    before = seeded["client"].get("/api/v1/notifications/center?status=all", headers=seeded["candidate"]).json()["total"]
    db = SessionLocal()
    try:
        rerun = run_automation_scan(db)
    finally:
        db.close()
    after = seeded["client"].get("/api/v1/notifications/center?status=all", headers=seeded["candidate"]).json()["total"]
    assert rerun["recruitments_scanned"] == 0
    assert after == before


# --- Notification center actions -----------------------------------------------

def test_mark_read_archive_and_read_all(seeded):
    items = seeded["client"].get("/api/v1/notifications/center?status=all", headers=seeded["candidate"]).json()["items"]
    target = items[0]["id"]

    read_resp = seeded["client"].post(f"/api/v1/notifications/{target}/read", headers=seeded["candidate"])
    assert read_resp.status_code == 200

    unread_after = seeded["client"].get("/api/v1/notifications/center?status=unread", headers=seeded["candidate"]).json()
    assert target not in {i["id"] for i in unread_after["items"]}

    archive_resp = seeded["client"].post(f"/api/v1/notifications/{target}/archive", headers=seeded["candidate"])
    assert archive_resp.status_code == 200
    archived = seeded["client"].get("/api/v1/notifications/center?status=archived", headers=seeded["candidate"]).json()
    assert target in {i["id"] for i in archived["items"]}

    mark_all = seeded["client"].post("/api/v1/notifications/read-all", headers=seeded["candidate"])
    assert mark_all.status_code == 200
    still_unread = seeded["client"].get("/api/v1/notifications/center?status=unread", headers=seeded["candidate"]).json()
    assert still_unread["total"] == 0


def test_delete_notification(seeded):
    items = seeded["client"].get("/api/v1/notifications/center?status=all", headers=seeded["candidate"]).json()["items"]
    target = items[-1]["id"]
    resp = seeded["client"].delete(f"/api/v1/notifications/{target}", headers=seeded["candidate"])
    assert resp.status_code == 204
    after = seeded["client"].get("/api/v1/notifications/center?status=all", headers=seeded["candidate"]).json()
    assert target not in {i["id"] for i in after["items"]}


def test_notification_center_search(seeded):
    resp = seeded["client"].get("/api/v1/notifications/center?status=all&search=UPSC", headers=seeded["candidate"])
    assert resp.status_code == 200
    assert all("UPSC" in i["title"] or "UPSC" in i["message"] for i in resp.json()["items"])


# --- Reminders (free, no admin calls) -------------------------------------------

def test_custom_reminder_create_list_delete(seeded):
    created = seeded["client"].post("/api/v1/reminders", headers=seeded["candidate"], json={
        "job_id": seeded["b"], "reminder_type": "custom", "target_date": "2099-01-01", "offset_days": 7,
    })
    assert created.status_code == 201
    body = created.json()
    assert body["fire_date"] == "2098-12-25"

    listed = seeded["client"].get("/api/v1/reminders", headers=seeded["candidate"]).json()
    assert any(r["id"] == body["id"] for r in listed)

    deleted = seeded["client"].delete(f"/api/v1/reminders/{body['id']}", headers=seeded["candidate"])
    assert deleted.status_code == 204


def test_reminder_rejects_unknown_job(seeded):
    resp = seeded["client"].post("/api/v1/reminders", headers=seeded["candidate"], json={
        "job_id": 999999, "reminder_type": "custom", "target_date": "2099-01-01",
    })
    assert resp.status_code == 404


# --- Admin: queue, stats, logs, templates, health (free after the fixture) -----

def test_admin_queue_has_entries_for_both_channels(seeded):
    resp = seeded["client"].get("/api/v1/admin/notifications/queue", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    channels = {row["channel"] for row in resp.json()["items"]}
    assert "in_app" in channels and "email" in channels


def test_admin_stats_reflects_deliveries(seeded):
    resp = seeded["client"].get("/api/v1/admin/notifications/stats", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["delivery_by_status"].get("sent", 0) >= 2
    assert "email" in body["delivery_by_channel"]


def test_admin_automation_logs_recorded(seeded):
    resp = seeded["client"].get("/api/v1/admin/automation/logs", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    triggers = {row["trigger"] for row in resp.json()["items"]}
    assert "recruitment_published" in triggers or "subscription_match" in triggers


def test_admin_template_upsert_took_effect(seeded):
    resp = seeded["client"].put("/api/v1/admin/notification-templates/result/email", headers=ADMIN_HEADERS,
                                json={"subject": "Custom result subject", "body": "Custom result body {job_title}"})
    assert resp.status_code == 200
    assert resp.json()["subject"] == "Custom result subject"


def test_admin_health_reports_scheduled_jobs(seeded):
    resp = seeded["client"].get("/api/v1/admin/automation/health", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    # The scheduler runs each job once on TestClient startup (next_run_time=now).
    assert "careeros_notifications" in resp.json()


def test_known_template_keys_endpoint_is_public_and_matches_defaults():
    with TestClient(app) as client:
        resp = client.get("/api/v1/notification-template-keys")
        assert resp.status_code == 200
        keys = resp.json()
        for expected in ("admit_card", "result", "deadline_extended", "reminder", "subscription_match"):
            assert expected in keys
