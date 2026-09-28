"""V17.2 — Enterprise Security Hardening.

Env-var overrides below are set at import time, before `app.main` (and
therefore `app.core.config.settings`, a module-level singleton) is
first imported anywhere in the test process. See TEST_REPORT_V17_2.md
for why that matters: if this file is NOT the first test file pytest
imports in a given run, these overrides silently do nothing and the
defaults apply instead — a pre-existing characteristic of how every
test file in this project sets config via os.environ, not something
new here. Run this file on its own if in doubt:

    pytest tests/test_v17_2_security_hardening.py
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v17_2.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"
# Disabled for the lockout tests below, which need several consecutive
# failed attempts without progressive delay's 429s getting in the way.
# Progressive delay's own logic is verified separately as a pure
# function, not through HTTP timing.
os.environ["ACCOUNT_PROGRESSIVE_DELAY_BASE_SECONDS"] = "0"
os.environ["SESSION_IDLE_TIMEOUT_MINUTES"] = "1"
os.environ["SESSION_ABSOLUTE_TIMEOUT_DAYS"] = "1"
# This file makes many candidate-login calls across several tests, all
# sharing one client IP (TestClient) and therefore one generic "login"
# rate-limit bucket (already covered on its own in
# test_v16_hardening.py). Raised here so it can't trip mid-test and
# mask the *account*-lockout logic this file exists to test — a
# distinct mechanism keyed by account, not by IP (see
# app/core/account_lockout.py).
os.environ["AUTH_RATE_LIMIT_ATTEMPTS"] = "1000"

from datetime import datetime, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


import pytest  # noqa: E402


@pytest.fixture(autouse=True, scope="module")
def _apply_v17_2_settings_overrides():
    """The os.environ overrides above only take effect if this is the first module to import the app.
    In a full-suite run the settings singleton already exists, so apply the same values to it directly
    (and restore them afterwards) to make this file independent of collection order."""
    from app.core.config import settings

    overrides = {
        "account_progressive_delay_base_seconds": 0,
        "session_idle_timeout_minutes": 1,
        "session_absolute_timeout_days": 1,
        "auth_rate_limit_attempts": 1000,
    }
    original = {k: getattr(settings, k) for k in overrides}
    for k, v in overrides.items():
        setattr(settings, k, v)
    try:
        yield
    finally:
        for k, v in original.items():
            setattr(settings, k, v)

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}
PW = "correct-horse-battery-1"


def _register_candidate(client, email, password=PW):
    return client.post(
        "/api/v1/auth/candidate/register",
        json={"email": email, "password": password, "password_confirm": password, "full_name": "V17.2 Tester"},
    )


def _login_candidate(client, email, password=PW):
    return client.post("/api/v1/auth/candidate/login", json={"email": email, "password": password})


def _user_id(client, email):
    from app.db.session import SessionLocal
    from app.models.domain import User
    from sqlalchemy import select

    db = SessionLocal()
    try:
        return db.scalar(select(User).where(User.email == email)).id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Pure-function checks — no HTTP, no timing sensitivity.
# ---------------------------------------------------------------------------

def test_progressive_delay_pure_function():
    from app.core.account_lockout import progressive_delay_seconds
    from app.core.config import settings

    # This file sets ACCOUNT_PROGRESSIVE_DELAY_BASE_SECONDS=0 at import
    # time (see module docstring) so the HTTP-level lockout tests below
    # aren't slowed down by real delays — but that same override
    # zeroes every value this function could return (0 * 2**n == 0),
    # which would make every assertion below trivially true without
    # actually exercising the threshold/exponential-growth/cap logic.
    # Patch real, known values locally for just this test instead.
    original = (
        settings.account_progressive_delay_after_attempts,
        settings.account_progressive_delay_base_seconds,
        settings.account_progressive_delay_max_seconds,
    )
    settings.account_progressive_delay_after_attempts = 3
    settings.account_progressive_delay_base_seconds = 2
    settings.account_progressive_delay_max_seconds = 30
    try:
        assert progressive_delay_seconds(0) == 0
        assert progressive_delay_seconds(2) == 0  # below the after_attempts threshold (3)
        assert progressive_delay_seconds(3) == 2  # base_seconds
        assert progressive_delay_seconds(4) == 4  # base_seconds * 2**1
        assert progressive_delay_seconds(20) == 30  # capped at max_seconds
    finally:
        (
            settings.account_progressive_delay_after_attempts,
            settings.account_progressive_delay_base_seconds,
            settings.account_progressive_delay_max_seconds,
        ) = original


def test_lock_duration_escalates_and_caps():
    from app.core.account_lockout import lock_duration_minutes

    assert lock_duration_minutes(0) == 5
    assert lock_duration_minutes(1) == 10
    assert lock_duration_minutes(2) == 20
    assert lock_duration_minutes(10) == 240  # capped at account_lockout_max_minutes


# ---------------------------------------------------------------------------
# Account lockout — through the actual login endpoint.
# ---------------------------------------------------------------------------

def test_account_locks_after_repeated_failed_logins_and_blocks_even_correct_password():
    with TestClient(app) as client:
        email = "lockout1@example.com"
        _register_candidate(client, email)

        for _ in range(5):  # account_lockout_threshold default
            r = _login_candidate(client, email, password="wrong-password")
            assert r.status_code == 401

        # The account is now locked — even the CORRECT password is
        # rejected, which is the whole point of a lockout.
        locked = _login_candidate(client, email, password=PW)
        assert locked.status_code == 423


def test_admin_sees_and_clears_temporary_lock():
    with TestClient(app) as client:
        email = "lockout2@example.com"
        _register_candidate(client, email)
        for _ in range(5):
            _login_candidate(client, email, password="wrong-password")

        listing = client.get("/api/v1/admin/security/locked-accounts", headers=ADMIN_HEADERS)
        assert listing.status_code == 200
        temp_emails = {row["email"] for row in listing.json()["temporary"]}
        assert email in temp_emails

        uid = _user_id(client, email)
        unlock = client.post(f"/api/v1/admin/users/{uid}/unlock", headers=ADMIN_HEADERS)
        assert unlock.status_code == 200
        assert unlock.json()["locked_until"] is None

        ok = _login_candidate(client, email, password=PW)
        assert ok.status_code == 200


def test_admin_can_permanently_lock_and_unlock():
    with TestClient(app) as client:
        email = "permalock@example.com"
        _register_candidate(client, email)
        uid = _user_id(client, email)

        lock = client.post(f"/api/v1/admin/users/{uid}/lock", headers=ADMIN_HEADERS, json={"permanent": True, "reason": "policy violation"})
        assert lock.status_code == 200
        assert lock.json()["active"] is False

        # Permanent lock folds into the same generic 401 as a wrong
        # password — deliberately not a distinct signal (see _login's
        # comment on why lockout is checked separately/earlier).
        blocked = _login_candidate(client, email, password=PW)
        assert blocked.status_code == 401

        listing = client.get("/api/v1/admin/security/locked-accounts", headers=ADMIN_HEADERS)
        assert email in {row["email"] for row in listing.json()["permanent"]}

        unlock = client.post(f"/api/v1/admin/users/{uid}/unlock", headers=ADMIN_HEADERS)
        assert unlock.json()["active"] is True

        ok = _login_candidate(client, email, password=PW)
        assert ok.status_code == 200


def test_failed_logins_are_visible_to_admin():
    with TestClient(app) as client:
        email = "visiblefail@example.com"
        _register_candidate(client, email)
        _login_candidate(client, email, password="wrong-password")

        events = client.get("/api/v1/admin/security/failed-logins", headers=ADMIN_HEADERS)
        assert events.status_code == 200
        assert any(row["entity_id"] == email for row in events.json())


# ---------------------------------------------------------------------------
# OTP hardening.
# ---------------------------------------------------------------------------

def test_otp_verify_max_attempts_invalidates_code():
    with TestClient(app) as client:
        email = "otpattempts@example.com"
        _register_candidate(client, email)

        for _ in range(5):  # otp_max_attempts default
            r = client.post("/api/v1/auth/verify-email", json={"email": email, "code": "000000"})
            assert r.status_code == 400

        from app.db.session import SessionLocal
        from app.models.domain import EmailVerification, User
        from sqlalchemy import select

        db = SessionLocal()
        try:
            user = db.scalar(select(User).where(User.email == email))
            row = db.scalar(
                select(EmailVerification)
                .where(EmailVerification.user_id == user.id, EmailVerification.purpose == "verify_email")
                .order_by(EmailVerification.id.desc())
            )
            assert row.attempts >= 5
            assert row.consumed is True  # invalidated, not just "still wrong"
        finally:
            db.close()


def test_otp_resend_cooldown_blocks_immediate_resend():
    with TestClient(app) as client:
        email = "otpcooldown@example.com"
        _register_candidate(client, email)  # issues an initial code

        from app.core.otp_security import resend_cooldown_remaining_seconds
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            uid = _user_id(client, email)
            remaining = resend_cooldown_remaining_seconds(db, uid, "verify_email")
            assert remaining > 0  # just issued, well within the 60s default cooldown
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Session idle / absolute timeout — enforced in rotate_refresh_token.
# ---------------------------------------------------------------------------

def _login_and_get_refresh_token(client, email):
    r = _login_candidate(client, email)
    assert r.status_code == 200
    return r.json()["refresh_token"], r.json()["session"]["id"]


def test_session_idle_timeout_revokes_on_refresh():
    with TestClient(app) as client:
        email = "idletimeout@example.com"
        _register_candidate(client, email)
        refresh_token, session_id = _login_and_get_refresh_token(client, email)

        from app.db.session import SessionLocal
        from app.models.domain import UserSession

        db = SessionLocal()
        try:
            row = db.get(UserSession, session_id)
            row.last_seen_at = datetime.utcnow() - timedelta(minutes=5)  # > 1min idle timeout override
            db.commit()
        finally:
            db.close()

        refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert refreshed.status_code == 401
        assert "expired" in refreshed.json()["detail"].lower()


def test_session_absolute_timeout_revokes_on_refresh():
    with TestClient(app) as client:
        email = "absolutetimeout@example.com"
        _register_candidate(client, email)
        refresh_token, session_id = _login_and_get_refresh_token(client, email)

        from app.db.session import SessionLocal
        from app.models.domain import UserSession

        db = SessionLocal()
        try:
            row = db.get(UserSession, session_id)
            row.created_at = datetime.utcnow() - timedelta(days=3)  # > 1 day absolute timeout override
            row.last_seen_at = datetime.utcnow()  # idle timeout not the trigger here
            db.commit()
        finally:
            db.close()

        refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert refreshed.status_code == 401


# ---------------------------------------------------------------------------
# Admin session visibility + revoke.
# ---------------------------------------------------------------------------

def test_admin_can_list_and_revoke_a_users_session():
    with TestClient(app) as client:
        email = "adminrevoke@example.com"
        _register_candidate(client, email)
        refresh_token, session_id = _login_and_get_refresh_token(client, email)
        uid = _user_id(client, email)

        sessions = client.get(f"/api/v1/admin/users/{uid}/sessions", headers=ADMIN_HEADERS)
        assert sessions.status_code == 200
        assert any(s["id"] == session_id for s in sessions.json())

        revoke = client.post(f"/api/v1/admin/sessions/{session_id}/revoke", headers=ADMIN_HEADERS)
        assert revoke.status_code == 200
        assert revoke.json()["user_id"] == uid

        refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert refreshed.status_code == 401


# ---------------------------------------------------------------------------
# Distinct, stricter rate-limit buckets.
# ---------------------------------------------------------------------------

def test_admin_login_has_its_own_stricter_rate_limit():
    with TestClient(app) as client:
        from app.core.config import settings

        limit = settings.admin_login_rate_limit_attempts
        last_status = None
        for _ in range(limit + 2):
            last_status = client.post(
                "/api/v1/auth/admin/login", json={"email": "nobody@example.com", "password": "wrong"}
            ).status_code
        assert last_status == 429


def test_profile_update_is_rate_limited_independently():
    with TestClient(app) as client:
        email = "profilerl@example.com"
        _register_candidate(client, email)
        login = _login_candidate(client, email)
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        from app.core.config import settings

        limit = settings.profile_update_rate_limit_attempts
        last_status = None
        for _ in range(limit + 2):
            last_status = client.put("/api/v1/profile", headers=headers, json={}).status_code
        assert last_status == 429


# ---------------------------------------------------------------------------
# Security event handler registry — a real extension point, not a fake
# SIEM/webhook integration (see core/security_events.py's docstring).
# ---------------------------------------------------------------------------

def test_security_event_handlers_are_notified_and_failures_dont_break_the_request():
    from app.core import security_events

    seen = []
    security_events.register_handler(lambda event, entity_type, entity_id, detail: seen.append(event))

    def broken_handler(event, entity_type, entity_id, detail):
        raise RuntimeError("simulated broken webhook")

    security_events.register_handler(broken_handler)

    with TestClient(app) as client:
        email = "handlerregistry@example.com"
        r = _register_candidate(client, email)
        assert r.status_code == 201
        login = _login_candidate(client, email)
        assert login.status_code == 200  # the broken handler must not fail the request

    assert security_events.SecurityEvent.LOGIN_SUCCESS in seen
