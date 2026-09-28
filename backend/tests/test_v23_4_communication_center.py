"""V23.4 — Communication Center, Interview & Deadline Reminders tests.

Same conventions as test_v23_3_smart_job_alerts.py / test_v23_1_*: own
SQLite file, EMAIL_MODE=console, SCHEDULER_ENABLED=false so the
in-process scheduler never races these tests, and the reminder/digest
engines are invoked directly against a SessionLocal() (same precedent
as test_v23_1_notification_infrastructure.py's dedupe test) since
they're background-job entry points, not HTTP endpoints, apart from
the admin-guarded manual-run route.

NOT RUN IN THIS ENVIRONMENT: the sandbox this suite was written in has
no outbound network access, so `pip install -r requirements.txt`
cannot complete and pytest cannot actually execute here — see this
version's final report / docs/V23_4_COMMUNICATION_CENTER.md "Known
limitations". This file is written to run with `pytest -q` in a normal
dev environment; nothing below should be read as an executed result.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v23_4.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"
os.environ["EMAIL_MODE"] = "console"
os.environ["SCHEDULER_ENABLED"] = "false"

from datetime import date, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}

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
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _user_id(client, headers) -> int:
    return client.get("/api/v1/auth/me", headers=headers).json()["id"]


def _create_application(client, headers, **overrides) -> dict:
    _counter["n"] += 1
    payload = {"company": f"Acme {_counter['n']}", "job_title": "Backend Engineer", "status": "APPLIED"}
    payload.update(overrides)
    resp = client.post("/api/v1/applications", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_interview(client, headers, application_id: int, **overrides) -> dict:
    payload = {"interview_type": "VIDEO", "result": "SCHEDULED"}
    payload.update(overrides)
    resp = client.post(f"/api/v1/applications/{application_id}/interviews", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_task(client, headers, application_id: int, **overrides) -> dict:
    payload = {"title": "Submit assessment"}
    payload.update(overrides)
    resp = client.post(f"/api/v1/applications/{application_id}/tasks", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Summary / Action Required / Upcoming — real data, no fake values
# ---------------------------------------------------------------------------


def test_summary_zero_state_for_fresh_user(client):
    headers = _register_and_login(client, "v234fresh")
    resp = client.get("/api/v1/communication/summary", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "unread_notifications": 0,
        "upcoming_interviews": 0,
        "upcoming_deadlines": 0,
        "overdue_deadlines": 0,
        "overdue_tasks": 0,
        "applications_needing_attention": 0,
        "new_job_matches": 0,
    }


def test_summary_counts_overdue_task_and_upcoming_interview(client):
    headers = _register_and_login(client, "v234summary")
    app_record = _create_application(client, headers)
    _create_task(client, headers, app_record["id"], title="Overdue task", due_at=_iso(datetime.utcnow() - timedelta(days=2)))
    _create_interview(client, headers, app_record["id"], scheduled_at=_iso(datetime.utcnow() + timedelta(days=2)))

    resp = client.get("/api/v1/communication/summary", headers=headers)
    body = resp.json()
    assert body["overdue_tasks"] == 1
    assert body["upcoming_interviews"] == 1


def test_action_required_includes_overdue_task_and_prepare_for_interview(client):
    headers = _register_and_login(client, "v234actions")
    app_record = _create_application(client, headers)
    _create_task(client, headers, app_record["id"], title="Send portfolio", due_at=_iso(datetime.utcnow() - timedelta(days=1)))
    _create_interview(client, headers, app_record["id"], scheduled_at=_iso(datetime.utcnow() + timedelta(days=1)))

    resp = client.get("/api/v1/communication/actions", headers=headers)
    assert resp.status_code == 200, resp.text
    actions = resp.json()["actions"]
    kinds = {a["kind"] for a in actions}
    assert "complete_overdue_task" in kinds
    assert "prepare_for_interview" in kinds
    # URGENT/HIGH sorted ahead of anything lower
    priorities = [a["priority"] for a in actions]
    order = {"URGENT": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}
    assert priorities == sorted(priorities, key=lambda p: order[p])


def test_action_required_ownership_isolation(client):
    headers_a = _register_and_login(client, "v234owna")
    headers_b = _register_and_login(client, "v234ownb")
    app_a = _create_application(client, headers_a)
    _create_task(client, headers_a, app_a["id"], title="A's task", due_at=_iso(datetime.utcnow() - timedelta(days=1)))

    resp_b = client.get("/api/v1/communication/actions", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json()["actions"] == []


def test_upcoming_buckets_items_by_date(client):
    headers = _register_and_login(client, "v234upcoming")
    app_record = _create_application(client, headers, deadline=(date.today() + timedelta(days=10)).isoformat())
    # V23.5 fix: a fixed "+5 hours" offset crosses into UTC tomorrow
    # whenever this suite runs in the last ~5 hours of the UTC day,
    # making the original hardcoded `body["TODAY"]` assertion flaky by
    # time of day rather than by actual bucketing correctness (the
    # aggregator buckets by UTC date, matching
    # app.communication.reminders' documented UTC-storage convention —
    # see that module's own docstring on why display stays UTC).
    # Asserting against whichever of TODAY/TOMORROW is actually correct
    # for "right now" tests the same real behavior without being
    # sensitive to the wall-clock time this suite happens to run at.
    interview_at = datetime.utcnow() + timedelta(hours=5)
    _create_interview(client, headers, app_record["id"], scheduled_at=_iso(interview_at))
    expected_bucket = "TODAY" if interview_at.date() == date.today() else "TOMORROW"

    resp = client.get("/api/v1/communication/upcoming", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any(item["type"] == "INTERVIEW" for item in body[expected_bucket])
    assert any(item["type"] == "DEADLINE" for item in body["LATER"])


# ---------------------------------------------------------------------------
# Reminder idempotency — the spec's central requirement
# ---------------------------------------------------------------------------


def test_interview_reminder_fires_once_and_is_idempotent_on_rerun(client):
    from app.communication.reminders import run_due_reminders
    from app.db.session import SessionLocal
    from app.models.domain import Notification, NotificationReminder

    headers = _register_and_login(client, "v234reminder")
    user_id = _user_id(client, headers)
    app_record = _create_application(client, headers)
    # 23.5 hours out: the 24-hours-before offset's scheduled_for is
    # ~30 minutes in the past — due now, within the late-arrival grace
    # window — while the 1-hour-before offset is still far in the future.
    interview = _create_interview(
        client, headers, app_record["id"], scheduled_at=_iso(datetime.utcnow() + timedelta(hours=23, minutes=30))
    )

    db = SessionLocal()
    try:
        result_1 = run_due_reminders(db)
        # V23.5 fix: run_due_reminders scans ALL SCHEDULED interviews in
        # the database (by design — it's the same scan production's
        # scheduler runs, across every user, not just this test's). This
        # test file shares one database across many tests via the
        # module-scoped `client` fixture, so another test's own
        # SCHEDULED interview can coincidentally also become "due" at
        # this same simulated `now`, making an exact-equality assertion
        # on the GLOBAL created/sent counts flaky depending on test
        # execution order and wall-clock timing — confirmed by it
        # failing only in full-suite runs, never in isolation. The
        # per-interview-scoped queries below (source_id=interview["id"])
        # are what actually verifies this test's claim (idempotency for
        # THIS interview) and aren't sensitive to other tests' data, so
        # the global counts are only checked as "at least one thing
        # happened," not for an exact value.
        assert result_1["interviews"]["created"] >= 1
        assert result_1["interviews"]["sent"] >= 1

        reminders_after_first = db.query(NotificationReminder).filter_by(
            source_type="INTERVIEW", source_id=interview["id"]
        ).all()
        assert len(reminders_after_first) == 1
        assert reminders_after_first[0].status == "SENT"

        # V23.5 fix: creating the interview itself already produced one
        # category=INTERVIEW notification via V23.1's own
        # interview_scheduled event (app.applications.events) — that's
        # correct, expected, pre-existing behavior, not something this
        # test should assert doesn't exist. What this test actually
        # cares about is that the REMINDER produced exactly one
        # notification, so it filters on the reminder's own
        # notification_type rather than the whole INTERVIEW category.
        reminder_notifications_after_first = db.query(Notification).filter_by(
            user_id=user_id, category="INTERVIEW", notification_type="reminder_interview"
        ).count()
        assert reminder_notifications_after_first == 1

        # Simulate a worker retry / scheduler double-tick.
        run_due_reminders(db)

        reminders_after_second = db.query(NotificationReminder).filter_by(
            source_type="INTERVIEW", source_id=interview["id"]
        ).all()
        assert len(reminders_after_second) == 1  # still exactly one row — not recreated by the re-run

        reminder_notifications_after_second = db.query(Notification).filter_by(
            user_id=user_id, category="INTERVIEW", notification_type="reminder_interview"
        ).count()
        assert reminder_notifications_after_second == 1  # still exactly one reminder notification
    finally:
        db.close()


def test_no_reminder_for_cancelled_interview(client):
    from app.communication.reminders import run_due_reminders
    from app.db.session import SessionLocal
    from app.models.domain import NotificationReminder

    headers = _register_and_login(client, "v234cancelled")
    app_record = _create_application(client, headers)
    interview = _create_interview(
        client, headers, app_record["id"], scheduled_at=_iso(datetime.utcnow() + timedelta(hours=23, minutes=30)),
    )
    cancel = client.patch(
        f"/api/v1/applications/{app_record['id']}/interviews/{interview['id']}", headers=headers, json={"result": "CANCELLED"}
    )
    assert cancel.status_code == 200, cancel.text

    db = SessionLocal()
    try:
        run_due_reminders(db)
        rows = db.query(NotificationReminder).filter_by(source_type="INTERVIEW", source_id=interview["id"]).all()
        assert rows == []
    finally:
        db.close()


def test_deadline_reminder_due_today(client):
    from app.communication.reminders import run_due_reminders
    from app.db.session import SessionLocal
    from app.models.domain import NotificationReminder

    headers = _register_and_login(client, "v234deadline")
    app_record = _create_application(client, headers, deadline=date.today().isoformat())

    db = SessionLocal()
    try:
        result = run_due_reminders(db)
        assert result["deadlines"]["created"] == 1
        row = db.query(NotificationReminder).filter_by(source_type="DEADLINE", source_id=app_record["id"]).one()
        assert row.reminder_type == "DUE_TODAY"
        assert row.priority == "URGENT"
        assert row.status == "SENT"
    finally:
        db.close()


def test_quiet_hours_delays_non_urgent_reminder(client):
    from app.communication.reminders import _in_quiet_hours

    class _FakePref:
        timezone = "UTC"
        quiet_hours_start = 22
        quiet_hours_end = 7

    now_in_quiet = datetime(2026, 1, 1, 23, 0)  # 11pm UTC — inside 22:00-07:00
    now_outside_quiet = datetime(2026, 1, 1, 12, 0)  # noon UTC — outside
    assert _in_quiet_hours(_FakePref(), now_in_quiet) is True
    assert _in_quiet_hours(_FakePref(), now_outside_quiet) is False


def test_quiet_hours_never_delays_urgent_reminder_end_to_end(client, monkeypatch):
    """A DUE_TODAY deadline (URGENT) is delivered even while the
    user is (forced, via monkeypatch, to be) inside quiet hours —
    spec section 17: "URGENT/security-critical notifications may
    follow separate rules." Forcing _in_quiet_hours rather than
    picking a real wall-clock window keeps this deterministic
    regardless of what time the suite happens to run."""
    import app.communication.reminders as reminders_module
    from app.db.session import SessionLocal
    from app.models.domain import NotificationReminder

    monkeypatch.setattr(reminders_module, "_in_quiet_hours", lambda pref, now: True)

    headers = _register_and_login(client, "v234urgentquiet")
    app_record = _create_application(client, headers, deadline=date.today().isoformat())

    db = SessionLocal()
    try:
        reminders_module.run_due_reminders(db)
        row = db.query(NotificationReminder).filter_by(source_type="DEADLINE", source_id=app_record["id"]).one()
        # URGENT (due today) is delivered regardless of quiet hours.
        assert row.status == "SENT"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------


def test_digest_not_sent_when_not_opted_in(client):
    from app.communication.digest import send_digest_for_user
    from app.db.session import SessionLocal

    headers = _register_and_login(client, "v234digestoptout")
    user_id = _user_id(client, headers)
    app_record = _create_application(client, headers)
    _create_task(client, headers, app_record["id"], due_at=_iso(datetime.utcnow() - timedelta(days=1)))

    db = SessionLocal()
    try:
        sent = send_digest_for_user(db, user_id)
        assert sent is False
    finally:
        db.close()


def test_digest_not_sent_when_no_content(client):
    from app.communication.digest import send_digest_for_user
    from app.db.session import SessionLocal
    from app.models.domain import UserNotificationPreference

    headers = _register_and_login(client, "v234digestempty")
    user_id = _user_id(client, headers)

    db = SessionLocal()
    try:
        pref = db.get(UserNotificationPreference, user_id) or UserNotificationPreference(user_id=user_id)
        pref.digest_enabled = True
        db.add(pref)
        db.commit()

        sent = send_digest_for_user(db, user_id)
        assert sent is False  # spec section 12: "Do NOT send empty emails."
    finally:
        db.close()


def test_digest_sent_once_per_day_when_opted_in_with_content(client):
    from app.communication.digest import send_digest_for_user
    from app.db.session import SessionLocal
    from app.models.domain import EmailMessage, UserNotificationPreference

    headers = _register_and_login(client, "v234digestcontent")
    user_id = _user_id(client, headers)
    app_record = _create_application(client, headers)
    _create_task(client, headers, app_record["id"], due_at=_iso(datetime.utcnow() - timedelta(days=1)))

    db = SessionLocal()
    try:
        pref = db.get(UserNotificationPreference, user_id) or UserNotificationPreference(user_id=user_id)
        pref.digest_enabled = True
        db.add(pref)
        db.commit()

        first = send_digest_for_user(db, user_id)
        second = send_digest_for_user(db, user_id)  # same day — must be a no-op
        assert first is True
        assert second is False

        count = db.query(EmailMessage).filter_by(user_id=user_id, template_key="DAILY_CAREER_DIGEST").count()
        assert count == 1
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Manual reminder-run endpoint — admin-only
# ---------------------------------------------------------------------------


def test_manual_reminder_run_requires_admin_key(client):
    headers = _register_and_login(client, "v234manualrun")
    resp = client.post("/api/v1/communication/reminders/run", headers=headers)
    assert resp.status_code in (401, 403)


def test_manual_reminder_run_with_admin_key_succeeds(client):
    resp = client.post("/api/v1/communication/reminders/run", headers=ADMIN_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "interviews" in body and "deadlines" in body and "tasks" in body


# ---------------------------------------------------------------------------
# Preferences extension (spec section 13 — reused, not duplicated)
# ---------------------------------------------------------------------------


def test_preferences_accept_timezone_and_digest_enabled(client):
    headers = _register_and_login(client, "v234prefs")
    resp = client.put(
        "/api/v1/notifications/preferences", headers=headers,
        json={"timezone": "Asia/Kolkata", "digest_enabled": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["timezone"] == "Asia/Kolkata"
    assert body["digest_enabled"] is True


def test_preferences_reject_invalid_timezone(client):
    headers = _register_and_login(client, "v234badtz")
    resp = client.put("/api/v1/notifications/preferences", headers=headers, json={"timezone": "Not/A_Real_Zone"})
    assert resp.status_code == 422
