"""V17.1 — Enterprise Authentication Core.

Covers what's new on top of the V16 auth flow (already exercised by
test_smoke.py / test_v16_hardening.py, both left passing unchanged):
role-scoped registration/login for all four roles, refresh-token
rotation + reuse detection, logout / logout-all / session listing,
password confirmation + minimum length + reuse history, duplicate
phone validation, and admin-only account provisioning for
admin/super_admin.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v17_1.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}
PW = "correct-horse-battery-1"  # 24 chars, well above the 12-char minimum
NEW_PW = "correct-horse-battery-2"


def _register_candidate(client, email, password=PW):
    return client.post(
        "/api/v1/auth/candidate/register",
        json={"email": email, "password": password, "password_confirm": password, "full_name": "V17 Tester"},
    )


def _login_candidate(client, email, password=PW, **extra):
    return client.post("/api/v1/auth/candidate/login", json={"email": email, "password": password, **extra})


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_candidate_register_requires_matching_password_confirmation():
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/auth/candidate/register",
            json={
                "email": "mismatch@example.com", "password": PW,
                "password_confirm": "something-else-entirely", "full_name": "X",
            },
        )
        assert r.status_code == 422


def test_password_below_minimum_length_is_rejected():
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/auth/candidate/register",
            json={"email": "short@example.com", "password": "short1234", "password_confirm": "short1234", "full_name": "X"},
        )
        assert r.status_code == 422


def test_recruiter_register_requires_company_fields():
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/auth/recruiter/register",
            json={"email": "norecco@example.com", "password": PW, "password_confirm": PW, "full_name": "X"},
        )
        assert r.status_code == 422  # company_name / company_email missing

        ok = client.post(
            "/api/v1/auth/recruiter/register",
            json={
                "email": "goodrecco@example.com", "password": PW, "password_confirm": PW, "full_name": "Recruiter X",
                "company_name": "Acme Corp", "company_email": "hr@acme.example", "company_website": "https://acme.example",
            },
        )
        assert ok.status_code == 201


def test_duplicate_phone_is_rejected():
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/auth/candidate/register",
            json={
                "email": "phoneowner@example.com", "password": PW, "password_confirm": PW,
                "full_name": "Phone Owner", "phone": "+15550001111",
            },
        )
        assert first.status_code == 201

        dupe = client.post(
            "/api/v1/auth/candidate/register",
            json={
                "email": "otherphone@example.com", "password": PW, "password_confirm": PW,
                "full_name": "Other Phone", "phone": "+15550001111",
            },
        )
        assert dupe.status_code == 409


# ---------------------------------------------------------------------------
# Role-scoped login
# ---------------------------------------------------------------------------

def test_candidate_cannot_use_recruiter_login():
    with TestClient(app) as client:
        _register_candidate(client, "cand4recl@example.com")
        r = client.post("/api/v1/auth/recruiter/login", json={"email": "cand4recl@example.com", "password": PW})
        assert r.status_code == 403


def test_candidate_cannot_use_admin_login():
    with TestClient(app) as client:
        _register_candidate(client, "cand4adminl@example.com")
        r = client.post("/api/v1/auth/admin/login", json={"email": "cand4adminl@example.com", "password": PW})
        assert r.status_code == 403


def test_legacy_login_alias_matches_candidate_login():
    with TestClient(app) as client:
        _register_candidate(client, "legacyalias@example.com")
        legacy = client.post("/api/v1/auth/login", json={"email": "legacyalias@example.com", "password": PW})
        assert legacy.status_code == 200
        assert legacy.json()["role"] == "candidate"
        assert "refresh_token" in legacy.json()
        assert legacy.json()["user"]["email"] == "legacyalias@example.com"


def test_admin_login_works_for_admin_and_super_admin():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/admin/create-admin-user",
            headers=ADMIN_HEADERS,
            json={"email": "superadmin1@example.com", "password": PW, "full_name": "Super", "role": "super_admin"},
        )
        assert created.status_code == 201
        assert created.json()["role"] == "super_admin"

        login = client.post("/api/v1/auth/admin/login", json={"email": "superadmin1@example.com", "password": PW})
        assert login.status_code == 200
        assert login.json()["role"] == "super_admin"

        # Not reachable via the candidate/recruiter logins.
        wrong = client.post("/api/v1/auth/candidate/login", json={"email": "superadmin1@example.com", "password": PW})
        assert wrong.status_code == 403


def test_admin_account_creation_requires_admin_key():
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/admin/create-admin-user",
            json={"email": "noauth@example.com", "password": PW, "full_name": "X", "role": "admin"},
        )
        assert r.status_code == 401


def test_admin_creation_rejects_invalid_role():
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/admin/create-admin-user",
            headers=ADMIN_HEADERS,
            json={"email": "badrole@example.com", "password": PW, "full_name": "X", "role": "candidate"},
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Refresh tokens / sessions
# ---------------------------------------------------------------------------

def test_refresh_token_rotates_and_old_token_cannot_be_reused():
    with TestClient(app) as client:
        _register_candidate(client, "rotator@example.com")
        login = _login_candidate(client, "rotator@example.com")
        old_refresh = login.json()["refresh_token"]

        first_refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
        assert first_refresh.status_code == 200
        assert first_refresh.json()["refresh_token"] != old_refresh

        # Reusing the now-rotated-away token must fail (theft/replay detection).
        reused = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
        assert reused.status_code == 401

        # And it should have taken the whole session down with it.
        second_use_of_new_token = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": first_refresh.json()["refresh_token"]}
        )
        assert second_use_of_new_token.status_code == 401


def test_logout_revokes_the_refresh_token():
    with TestClient(app) as client:
        _register_candidate(client, "logoutuser@example.com")
        login = _login_candidate(client, "logoutuser@example.com")
        access = login.json()["access_token"]
        refresh_token = login.json()["refresh_token"]

        out = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access}"},
            json={"refresh_token": refresh_token},
        )
        assert out.status_code == 200

        again = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert again.status_code == 401


def test_sessions_list_and_logout_all():
    with TestClient(app) as client:
        _register_candidate(client, "multisession@example.com")
        login_a = _login_candidate(client, "multisession@example.com", device_id="phone-1", device_label="Phone")
        login_b = _login_candidate(client, "multisession@example.com", device_id="laptop-1", device_label="Laptop")
        access_a = login_a.json()["access_token"]

        listed = client.get("/api/v1/auth/sessions", headers={"Authorization": f"Bearer {access_a}"})
        assert listed.status_code == 200
        assert len(listed.json()) >= 2

        out_all = client.post("/api/v1/auth/logout-all", headers={"Authorization": f"Bearer {access_a}"})
        assert out_all.status_code == 200
        assert out_all.json()["sessions_revoked"] >= 2

        refresh_after = client.post("/api/v1/auth/refresh", json={"refresh_token": login_b.json()["refresh_token"]})
        assert refresh_after.status_code == 401


# ---------------------------------------------------------------------------
# Password strength / history
# ---------------------------------------------------------------------------

def test_password_strength_endpoint_scores_weak_and_strong():
    with TestClient(app) as client:
        weak = client.post("/api/v1/auth/password-strength", json={"password": "password"})
        assert weak.status_code == 200
        assert weak.json()["score"] <= 1

        strong = client.post("/api/v1/auth/password-strength", json={"password": "Zx9!qLambdaGiraffe42"})
        assert strong.status_code == 200
        assert strong.json()["score"] >= 3


def test_reset_password_rejects_recent_reuse():
    with TestClient(app) as client:
        email = "reuseblock@example.com"
        _register_candidate(client, email)

        forgot = client.post("/api/v1/auth/forgot-password", json={"email": email})
        assert forgot.status_code == 200

        # Dev-mode email isn't intercepted here; exercise the reuse-guard
        # directly against the stored hash instead, mirroring what the
        # OTP-verified path in the endpoint checks.
        from app.core.password_policy import was_recently_used
        from app.db.session import SessionLocal
        from app.models.domain import User
        from sqlalchemy import select

        db = SessionLocal()
        try:
            user = db.scalar(select(User).where(User.email == email))
            assert was_recently_used(db, user.id, PW) is True
            assert was_recently_used(db, user.id, "totally-different-pw-1") is False
        finally:
            db.close()


# ---------------------------------------------------------------------------
# JWT claims are role-independent per token
# ---------------------------------------------------------------------------

def test_me_reflects_role_and_profile_fields():
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/auth/recruiter/register",
            json={
                "email": "meprofile@example.com", "password": PW, "password_confirm": PW, "full_name": "Rec Person",
                "company_name": "Acme Corp", "company_email": "hr@acme.example",
            },
        )
        assert r.status_code == 201
        # Recruiter needs admin approval before recruiter/login works;
        # approve then log in through the recruiter-specific endpoint.
        pending = client.get("/api/v1/admin/recruiters/pending", headers=ADMIN_HEADERS)
        target = next(u for u in pending.json() if u["email"] == "meprofile@example.com")
        approved = client.post(f"/api/v1/admin/recruiters/{target['id']}/approve", headers=ADMIN_HEADERS)
        assert approved.status_code == 200

        login = client.post("/api/v1/auth/recruiter/login", json={"email": "meprofile@example.com", "password": PW})
        assert login.status_code == 200
        access = login.json()["access_token"]

        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert me.status_code == 200
        body = me.json()
        assert body["role"] == "recruiter"
        assert body["company_name"] == "Acme Corp"
