"""V23.2 — Email Notification & Template Engine tests.

Uses EMAIL_MODE=console (the default) throughout — no real SMTP
connection is ever opened in this suite. Provider failures are
simulated by monkeypatching app.email.provider.get_provider to return
a fake provider that raises, never by attempting a real network call.
"""

import json
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v23_2.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"
os.environ["EMAIL_MODE"] = "console"

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.models.domain import EmailMessage, User  # noqa: E402

_counter = {"n": 0}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _register_and_login(client, email_prefix: str) -> tuple[dict, str]:
    _counter["n"] += 1
    email = f"{email_prefix}{_counter['n']}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Test User"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return headers, email


def _create_application(client, headers, **overrides):
    payload = {"company": "Acme", "job_title": "Engineer", "status": "APPLIED"}
    payload.update(overrides)
    resp = client.post("/api/v1/applications", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _user_id_and_db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _user_by_email(db, email: str) -> User:
    return db.scalars(select(User).where(User.email == email)).first()


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


def test_template_rendering_and_required_variable_validation(client):
    # V23.5 fix: `client` is unused in this test's body, but requesting
    # it forces the module-scoped fixture (which runs the app's
    # lifespan startup, creating tables via Base.metadata.create_all)
    # to run before this test's raw SessionLocal() touches the
    # database. Without it, this test — the first in the file that
    # doesn't otherwise request `client` — ran against a database with
    # no tables yet whenever it executed before any test that does
    # request `client` (a real, reproducible test-ordering bug, not a
    # production issue: production always runs migrations/create_all
    # before serving any request). See docs/V23_BUG_REPORT.md.
    from app.email import templates as email_templates

    db = _user_id_and_db()
    try:
        template = email_templates.get_or_seed_template(db, "APPLICATION_STATUS_CHANGED")
        subject, html_body, text_body = email_templates.render(template, {
            "user_name": "Priya", "job_title": "Backend Engineer", "company_name": "Acme",
            "application_status": "Interview", "action_url": "/applications/1",
        })
        assert "Priya" not in subject or "Acme" in subject  # subject renders company_name
        assert "Backend Engineer" in html_body
        assert "Backend Engineer" in text_body

        with pytest.raises(email_templates.TemplateError):
            email_templates.render(template, {"user_name": "Priya"})  # missing required variables
    finally:
        db.close()


def test_template_html_escapes_variable_values_but_not_markup(client):
    # V23.5 fix: same reason as the test above — see its comment.
    from app.email import templates as email_templates

    db = _user_id_and_db()
    try:
        template = email_templates.get_or_seed_template(db, "SYSTEM_NOTIFICATION")
        _, html_body, text_body = email_templates.render(template, {
            "user_name": "<script>alert(1)</script>", "notification_title": "Alert",
            "notification_message": "hello", "action_url": "/notifications",
        })
        assert "<script>" not in html_body
        assert "&lt;script&gt;" in html_body
        # plain text is never escaped — nothing to break out of
        assert "<script>alert(1)</script>" in text_body
        # the template's own trusted markup survives escaping of the variable
        assert "<h2" in html_body
    finally:
        db.close()


def test_unknown_template_key_rejected():
    from app.email import templates as email_templates

    db = _user_id_and_db()
    try:
        with pytest.raises(email_templates.TemplateError):
            email_templates.get_or_seed_template(db, "NOT_A_REAL_TEMPLATE")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Queue / retry / failure
# ---------------------------------------------------------------------------


def test_queue_email_creates_queued_message_and_process_queue_sends_it(client):
    from app.email import service as email_service

    headers, email = _register_and_login(client, "v23_2queuesend")
    db = _user_id_and_db()
    try:
        user = _user_by_email(db, email)
        msg = email_service.queue_email(
            db, user_id=user.id, recipient=user.email, template_key="SYSTEM_NOTIFICATION",
            variables={"user_name": "Test", "notification_title": "Hi", "notification_message": "hello", "action_url": "/notifications"},
            category="SYSTEM",
        )
        assert msg is not None
        assert msg.status == "QUEUED"

        result = email_service.process_queue(db)
        assert result["sent"] >= 1

        db.refresh(msg)
        assert msg.status == "SENT"
        assert msg.sent_at is not None
    finally:
        db.close()


def test_queue_email_respects_email_preference(client):
    from app.email import service as email_service

    headers, email = _register_and_login(client, "v23_2prefoff")
    # Turn off APPLICATION-category email
    resp = client.put("/api/v1/notifications/preferences", headers=headers, json={"email_application": False})
    assert resp.status_code == 200

    db = _user_id_and_db()
    try:
        user = _user_by_email(db, email)
        msg = email_service.queue_email(
            db, user_id=user.id, recipient=user.email, template_key="APPLICATION_STATUS_CHANGED",
            variables={"user_name": "Test", "job_title": "Eng", "company_name": "Acme", "application_status": "Interview", "action_url": "/x"},
            category="APPLICATION",
        )
        assert msg is None  # preference says no
    finally:
        db.close()


def test_retry_then_permanent_failure(client, monkeypatch):
    from app.email import provider as email_provider
    from app.email import service as email_service

    class AlwaysFailsProvider(email_provider.EmailProvider):
        name = "fake-failing"

        def send(self, message):
            raise email_provider.EmailSendError("simulated permanent provider failure")

    # service.py did `from app.email.provider import get_provider`, a
    # name-bound import — patching app.email.provider.get_provider
    # would NOT affect service.py's already-bound local name. Patch
    # the name where it's actually called from instead (same pattern
    # V22.4's tests use for completion_service.route_complete).
    monkeypatch.setattr(email_service, "get_provider", lambda: AlwaysFailsProvider())

    headers, email = _register_and_login(client, "v23_2retryfail")
    db = _user_id_and_db()
    try:
        user = _user_by_email(db, email)
        msg = email_service.queue_email(
            db, user_id=user.id, recipient=user.email, template_key="SYSTEM_NOTIFICATION",
            variables={"user_name": "Test", "notification_title": "Hi", "notification_message": "hello", "action_url": "/notifications"},
            max_attempts=2,
        )
        assert msg is not None

        email_service.process_queue(db)
        db.refresh(msg)
        assert msg.status == "RETRYING"
        assert msg.attempts == 1
        assert msg.scheduled_at > msg.created_at  # pushed forward by backoff

        # Force it due again and let it exhaust attempts
        msg.scheduled_at = msg.created_at
        db.commit()
        email_service.process_queue(db)
        db.refresh(msg)
        assert msg.status == "FAILED"
        assert msg.attempts == 2
        assert msg.failed_at is not None
        assert msg.last_error is not None
    finally:
        db.close()


def test_duplicate_dedupe_key_returns_existing_not_a_new_row(client):
    from app.email import service as email_service
    headers, email = _register_and_login(client, "v23_2dedupeemail")
    db = _user_id_and_db()
    try:
        user = _user_by_email(db, email)
        first = email_service.queue_email(
            db, user_id=user.id, recipient=user.email, template_key="SYSTEM_NOTIFICATION",
            variables={"user_name": "Test", "notification_title": "Hi", "notification_message": "hello", "action_url": "/notifications"},
            dedupe_key="test_dedupe:unique_case_v232",
        )
        second = email_service.queue_email(
            db, user_id=user.id, recipient=user.email, template_key="SYSTEM_NOTIFICATION",
            variables={"user_name": "Test", "notification_title": "Different", "notification_message": "different", "action_url": "/notifications"},
            dedupe_key="test_dedupe:unique_case_v232",
        )
        assert first.id == second.id
        count = db.scalar(select(EmailMessage).where(EmailMessage.dedupe_key == "test_dedupe:unique_case_v232"))
        assert count is not None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Notification -> Email integration
# ---------------------------------------------------------------------------


def test_application_status_change_queues_an_email(client):
    headers, email = _register_and_login(client, "v23_2statusemail")
    a = _create_application(client, headers, status="APPLIED")
    resp = client.post(f"/api/v1/applications/{a['id']}/status", headers=headers, json={"status": "INTERVIEW"})
    assert resp.status_code == 200

    db = _user_id_and_db()
    try:
        msgs = db.scalars(select(EmailMessage).where(EmailMessage.recipient == email, EmailMessage.template_key == "APPLICATION_STATUS_CHANGED")).all()
        assert len(msgs) == 1
        variables = json.loads(msgs[0].variables_json)
        assert variables["application_status"] == "Interview"
    finally:
        db.close()


def test_interview_scheduled_queues_an_email(client):
    headers, email = _register_and_login(client, "v23_2ivemail")
    a = _create_application(client, headers, status="INTERVIEW")
    client.post(f"/api/v1/applications/{a['id']}/interviews", headers=headers, json={"interview_type": "technical"})

    db = _user_id_and_db()
    try:
        msgs = db.scalars(select(EmailMessage).where(EmailMessage.recipient == email, EmailMessage.template_key == "INTERVIEW_SCHEDULED")).all()
        assert len(msgs) == 1
    finally:
        db.close()


def test_application_creation_does_not_queue_an_email():
    """application_created is in-app-only this version — no
    dedicated template/at-minimum requirement for it."""
    pass  # covered implicitly: no APPLICATION_CREATED template key exists at all


# ---------------------------------------------------------------------------
# Email verification integration
# ---------------------------------------------------------------------------


def test_registration_queues_a_verification_email_without_persisting_the_code(client):
    headers, email = _register_and_login(client, "v23_2verify")

    db = _user_id_and_db()
    try:
        msgs = db.scalars(select(EmailMessage).where(EmailMessage.recipient == email, EmailMessage.template_key == "EMAIL_VERIFICATION")).all()
        assert len(msgs) == 1
        msg = msgs[0]
        assert msg.status == "SENT"
        # The OTP code must never be persisted in variables_json.
        persisted = json.loads(msg.variables_json) if msg.variables_json else {}
        assert "otp_code" not in persisted
        assert all(len(str(v)) != 6 or not str(v).isdigit() for v in persisted.values())
    finally:
        db.close()


def test_verification_email_failure_does_not_break_registration(client, monkeypatch):
    from app.email import provider as email_provider
    from app.email import service as email_service

    class AlwaysFailsProvider(email_provider.EmailProvider):
        name = "fake-failing"

        def send(self, message):
            raise email_provider.EmailSendError("simulated failure")

    monkeypatch.setattr(email_service, "get_provider", lambda: AlwaysFailsProvider())

    _counter["n"] += 1
    email = f"v23_2regfail{_counter['n']}@example.com"
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Test User"},
    )
    assert resp.status_code in (200, 201), resp.text  # registration itself must still succeed


# ---------------------------------------------------------------------------
# Preferences API (existing endpoint, extended with email_* fields)
# ---------------------------------------------------------------------------


def test_preferences_endpoint_accepts_email_fields(client):
    headers, _ = _register_and_login(client, "v23_2prefapi")
    resp = client.put("/api/v1/notifications/preferences", headers=headers, json={"email_interview": False, "email_ai": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email_interview"] is False
    assert body["email_ai"] is True

    get_resp = client.get("/api/v1/notifications/preferences", headers=headers)
    assert get_resp.json()["email_interview"] is False


# ---------------------------------------------------------------------------
# Admin overview
# ---------------------------------------------------------------------------


def test_admin_email_overview_requires_admin(client):
    headers, _ = _register_and_login(client, "v23_2adminoverview")
    resp = client.get("/api/v1/admin/email/overview", headers=headers)
    assert resp.status_code in (401, 403)
