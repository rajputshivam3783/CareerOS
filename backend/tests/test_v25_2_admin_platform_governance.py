"""V25.2 — Advanced Admin & Platform Governance.

Covers, in order: platform-admin authorization (including the central
rule that organization OWNER/ADMIN grants nothing at the platform
level), the dashboard, user management and lifecycle, organization
suspension behaviour, job moderation, audit creation/immutability/
filtering, platform search scoping, analytics privacy, system health,
platform settings, maintenance mode, announcements, bulk actions, and
V25.1 regression.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v25_2.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.domain import Job, PlatformAuditLog, PlatformSetting, User  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}
PW = "password12345!"
API = "/api/v1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _register(client, suffix, role="candidate"):
    email = f"v252{suffix}@example.com"
    client.post(
        f"{API}/auth/register",
        json={"email": email, "password": PW, "password_confirm": PW, "full_name": f"User {suffix}"},
    )
    login = client.post(f"{API}/auth/login", json={"email": email, "password": PW})
    token = login.json()["access_token"]
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    if role != "candidate":
        client.post(f"{API}/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": role})
        # Each role logs in through its own endpoint — /auth/login is
        # candidate-only (see app.api.auth._login's allowed-role set).
        path = {"recruiter": "/auth/recruiter/login"}.get(role, "/auth/admin/login")
        login = client.post(f"{API}{path}", json={"email": email, "password": PW})
        token = login.json()["access_token"]
    return email, me["id"], {"Authorization": f"Bearer {token}"}


def _platform_admin(client, suffix):
    """A real platform-administrator account (not the shared key)."""
    email = f"v252admin{suffix}@example.com"
    client.post(
        f"{API}/admin/create-admin-user",
        headers=ADMIN_HEADERS,
        json={"email": email, "password": PW, "full_name": f"Admin {suffix}", "role": "admin"},
    )
    login = client.post(f"{API}/auth/admin/login", json={"email": email, "password": PW})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_org(client, headers, name):
    resp = client.post(f"{API}/organizations", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _seed_job(client, *, title, status="review", owner_user_id=None):
    """Create a job directly through the admin ingest route, then set
    its owner/status in the database — the fastest way to get a job in
    a specific state without depending on the recruiter wizard."""
    resp = client.post(
        f"{API}/admin/ingest",
        headers=ADMIN_HEADERS,
        json={"title": title, "organization": "Test Org", "source_reference": title},
    )
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["job_id"]
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        job.status = status
        if owner_user_id:
            job.owner_user_id = owner_user_id
        db.commit()
    finally:
        db.close()
    return job_id


def _reset_settings():
    db = SessionLocal()
    try:
        db.query(PlatformSetting).delete()
        db.commit()
    finally:
        db.close()
    from app.core.platform_settings import invalidate_cache

    invalidate_cache()


# ===========================================================================
# 24/31. Platform-admin authorization — the central separation
# ===========================================================================


def test_candidate_recruiter_and_org_roles_cannot_access_admin():
    """The rule this whole version rests on: organization
    administration is not platform administration."""
    with TestClient(app) as client:
        _e, _cid, candidate = _register(client, "authcand")
        _e, rid, recruiter = _register(client, "authrec", role="recruiter")

        # This recruiter is the OWNER of their own organization — the
        # strongest role that exists inside a tenant.
        org = _create_org(client, recruiter, "Auth Test Org")
        members = client.get(f"{API}/organizations/{org['id']}/members", headers=recruiter).json()
        assert members[0]["role"] == "OWNER"

        for headers, label in ((candidate, "candidate"), (recruiter, "organization OWNER")):
            for path in (
                "/admin/dashboard",
                "/admin/users",
                "/admin/organizations",
                "/admin/jobs",
                "/admin/audit",
                "/admin/analytics",
                "/admin/system/health",
                "/admin/settings",
                "/admin/search?q=test",
                "/admin/me/platform-permissions",
            ):
                resp = client.get(f"{API}{path}", headers=headers)
                assert resp.status_code == 403, f"{label} reached {path}: {resp.status_code}"


def test_unauthenticated_and_bad_key_are_rejected():
    with TestClient(app) as client:
        assert client.get(f"{API}/admin/dashboard").status_code == 401
        assert client.get(f"{API}/admin/dashboard", headers={"X-Admin-Key": "wrong"}).status_code == 401


def test_org_owner_cannot_suspend_users_or_organizations():
    """Privilege escalation: the mutating endpoints, not just reads."""
    with TestClient(app) as client:
        _e, _uid, recruiter = _register(client, "escrec", role="recruiter")
        _e, victim_id, _v = _register(client, "escvictim")
        org = _create_org(client, recruiter, "Escalation Org")

        assert (
            client.post(
                f"{API}/admin/users/{victim_id}/suspend",
                headers=recruiter,
                json={"reason": "policy_violation"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"{API}/admin/organizations/{org['id']}/suspend",
                headers=recruiter,
                json={"reason": "policy_violation"},
            ).status_code
            == 403
        )
        assert (
            client.put(f"{API}/admin/settings/maintenance_mode", headers=recruiter, json={"value": True}).status_code
            == 403
        )


def test_privilege_escalation_attempt_is_recorded_as_a_security_event():
    with TestClient(app) as client:
        _e, _uid, recruiter = _register(client, "escaudit", role="recruiter")
        client.get(f"{API}/admin/dashboard", headers=recruiter)

        events = client.get(
            f"{API}/admin/security/events?action=privilege_escalation_attempt", headers=ADMIN_HEADERS
        ).json()
        assert events["total"] >= 1
        detail = events["results"][0]["detail"] or ""
        # The event is useful for investigation but carries no credential.
        assert "role=" in detail
        assert "Bearer" not in detail and PW not in detail


def test_platform_admin_user_can_access_admin():
    with TestClient(app) as client:
        admin = _platform_admin(client, "access")
        me = client.get(f"{API}/admin/me/platform-permissions", headers=admin)
        assert me.status_code == 200, me.text
        assert "USER_MANAGEMENT" in me.json()["permissions"]
        assert me.json()["can_perform_sensitive_actions"] is True


# ===========================================================================
# 3. Dashboard
# ===========================================================================


def test_dashboard_reports_real_counts():
    with TestClient(app) as client:
        before = client.get(f"{API}/admin/dashboard", headers=ADMIN_HEADERS).json()
        _register(client, "dashuser")
        after = client.get(f"{API}/admin/dashboard", headers=ADMIN_HEADERS).json()

        assert after["users"]["total"] == before["users"]["total"] + 1
        # Every documented omission is declared rather than faked.
        assert "active_users" in after["omitted_metrics"]
        assert "demographics" in after["omitted_metrics"]
        for section in ("users", "organizations", "jobs", "applications"):
            assert all(isinstance(v, int) for v in after[section].values())


def test_dashboard_requires_analytics_permission():
    with TestClient(app) as client:
        _e, _uid, candidate = _register(client, "dashperm")
        assert client.get(f"{API}/admin/dashboard", headers=candidate).status_code == 403


# ===========================================================================
# 4/5. User management and lifecycle
# ===========================================================================


def test_user_list_search_filter_and_pagination():
    with TestClient(app) as client:
        _register(client, "searchable_alpha")
        _register(client, "searchable_beta")

        page = client.get(f"{API}/admin/users?q=searchable_alpha", headers=ADMIN_HEADERS).json()
        assert page["total"] >= 1
        assert all("searchable_alpha" in r["email"] for r in page["results"])

        # Legacy V9 keys still present on every row.
        row = page["results"][0]
        for key in ("id", "email", "full_name", "role", "active"):
            assert key in row

        limited = client.get(f"{API}/admin/users?limit=1", headers=ADMIN_HEADERS).json()
        assert len(limited["results"]) == 1
        assert limited["limit"] == 1
        # Unbounded pages are impossible.
        assert client.get(f"{API}/admin/users?limit=5000", headers=ADMIN_HEADERS).status_code == 422


def test_user_list_never_exposes_sensitive_fields():
    with TestClient(app) as client:
        _e, uid, _h = _register(client, "sensitive")
        page = client.get(f"{API}/admin/users?q=sensitive", headers=ADMIN_HEADERS).json()
        detail = client.get(f"{API}/admin/users/{uid}", headers=ADMIN_HEADERS).json()
        blob = str(page) + str(detail)
        for forbidden in ("password_hash", "password", "otp", "token", "resume_snapshot"):
            assert forbidden not in blob.lower(), forbidden


def test_suspend_blocks_authentication_and_preserves_records():
    with TestClient(app) as client:
        email, uid, headers = _register(client, "suspendme")
        # The user has a session and can use it.
        assert client.get(f"{API}/auth/me", headers=headers).status_code == 200

        resp = client.post(
            f"{API}/admin/users/{uid}/suspend",
            headers=ADMIN_HEADERS,
            json={"reason": "policy_violation", "note": "internal only"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["account_status"] == "SUSPENDED"

        # Existing token no longer works, and they cannot log back in.
        assert client.get(f"{API}/auth/me", headers=headers).status_code == 401
        assert client.post(f"{API}/auth/login", json={"email": email, "password": PW}).status_code != 200

        # The user record itself still exists — nothing was destroyed.
        db = SessionLocal()
        try:
            user = db.get(User, uid)
            assert user is not None
            assert user.active is False
            assert user.suspended_at is not None
        finally:
            db.close()


def test_reactivate_restores_access():
    with TestClient(app) as client:
        email, uid, _h = _register(client, "reactivateme")
        client.post(f"{API}/admin/users/{uid}/suspend", headers=ADMIN_HEADERS, json={"reason": "spam"})
        resp = client.post(f"{API}/admin/users/{uid}/reactivate", headers=ADMIN_HEADERS, json={})
        assert resp.status_code == 200
        assert resp.json()["account_status"] == "ACTIVE"
        assert client.post(f"{API}/auth/login", json={"email": email, "password": PW}).status_code == 200


def test_suspension_preserves_organization_membership():
    """Platform status and organization membership are independent."""
    with TestClient(app) as client:
        _e, owner_id, owner = _register(client, "memberowner", role="recruiter")
        org = _create_org(client, owner, "Membership Org")

        client.post(f"{API}/admin/users/{owner_id}/suspend", headers=ADMIN_HEADERS, json={"reason": "spam"})
        detail = client.get(f"{API}/admin/users/{owner_id}", headers=ADMIN_HEADERS).json()
        membership = [m for m in detail["organization_memberships"] if m["organization_id"] == org["id"]]
        assert len(membership) == 1
        assert membership[0]["membership_status"] == "ACTIVE"
        assert membership[0]["organization_role"] == "OWNER"
        # ...while the platform account is suspended.
        assert detail["account_status"] == "SUSPENDED"


def test_cannot_suspend_own_account():
    with TestClient(app) as client:
        admin = _platform_admin(client, "selfsuspend")
        me = client.get(f"{API}/admin/me/platform-permissions", headers=admin).json()
        assert me["role"] == "admin"
        users = client.get(f"{API}/admin/users?q=v252adminselfsuspend", headers=admin).json()
        uid = users["results"][0]["id"]
        resp = client.post(f"{API}/admin/users/{uid}/suspend", headers=admin, json={"reason": "other"})
        assert resp.status_code == 400


def test_suspend_rejects_unknown_reason():
    with TestClient(app) as client:
        _e, uid, _h = _register(client, "badreason")
        resp = client.post(
            f"{API}/admin/users/{uid}/suspend", headers=ADMIN_HEADERS, json={"reason": "made_up_reason"}
        )
        assert resp.status_code == 422


def test_user_idor_returns_404_not_a_leak():
    with TestClient(app) as client:
        assert client.get(f"{API}/admin/users/99999999", headers=ADMIN_HEADERS).status_code == 404
        assert (
            client.post(
                f"{API}/admin/users/99999999/suspend", headers=ADMIN_HEADERS, json={"reason": "spam"}
            ).status_code
            == 404
        )


# ===========================================================================
# 6/7. Organization management and suspension
# ===========================================================================


def test_organization_list_and_detail_counts():
    with TestClient(app) as client:
        _e, _uid, recruiter = _register(client, "orglist", role="recruiter")
        org = _create_org(client, recruiter, "Listable Organization")

        page = client.get(f"{API}/admin/organizations?q=Listable", headers=ADMIN_HEADERS).json()
        assert page["total"] >= 1
        assert page["results"][0]["member_count"] >= 1

        detail = client.get(f"{API}/admin/organizations/{org['id']}", headers=ADMIN_HEADERS).json()
        assert detail["status"] == "ACTIVE"
        assert len(detail["members"]) >= 1
        member = detail["members"][0]
        # Organization role and platform status are reported as
        # separate, clearly-named facts.
        assert member["organization_role"] == "OWNER"
        assert member["platform_account_status"] == "ACTIVE"


def test_organization_suspension_unpublishes_jobs_and_blocks_members():
    with TestClient(app) as client:
        _e, owner_id, owner = _register(client, "suspendorg", role="recruiter")
        org = _create_org(client, owner, "Suspendable Organization")
        job_id = _seed_job(client, title="Suspendable Org Job", status="published", owner_user_id=owner_id)

        resp = client.post(
            f"{API}/admin/organizations/{org['id']}/suspend",
            headers=ADMIN_HEADERS,
            json={"reason": "policy_violation", "note": "internal"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "SUSPENDED"
        assert resp.json()["jobs_suspended"] == 1

        # The live listing is no longer published.
        db = SessionLocal()
        try:
            assert db.get(Job, job_id).status == "suspended"
        finally:
            db.close()

        # Members can no longer act in the organization — and the error
        # does not disclose the moderation reason.
        blocked = client.get(f"{API}/organizations/{org['id']}/members", headers=owner)
        assert blocked.status_code == 404
        assert "policy_violation" not in blocked.text

        # Nothing was deleted.
        detail = client.get(f"{API}/admin/organizations/{org['id']}", headers=ADMIN_HEADERS).json()
        assert detail["member_count"] >= 1


def test_organization_reactivation_restores_exactly_the_suspended_jobs():
    with TestClient(app) as client:
        _e, owner_id, owner = _register(client, "reactorg", role="recruiter")
        org = _create_org(client, owner, "Reactivatable Organization")
        live = _seed_job(client, title="Reactivate Live Job", status="published", owner_user_id=owner_id)
        # A job suspended individually, for its own reason, must NOT be
        # restored by reactivating the company.
        individually = _seed_job(client, title="Reactivate Bad Job", status="published", owner_user_id=owner_id)
        client.post(
            f"{API}/admin/jobs/{individually}/suspend",
            headers=ADMIN_HEADERS,
            json={"reason": "prohibited_content"},
        )

        client.post(
            f"{API}/admin/organizations/{org['id']}/suspend",
            headers=ADMIN_HEADERS,
            json={"reason": "suspicious_activity"},
        )
        resp = client.post(f"{API}/admin/organizations/{org['id']}/reactivate", headers=ADMIN_HEADERS, json={})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ACTIVE"

        db = SessionLocal()
        try:
            assert db.get(Job, live).status == "published"
            assert db.get(Job, individually).status == "suspended"
        finally:
            db.close()

        assert client.get(f"{API}/organizations/{org['id']}/members", headers=owner).status_code == 200


def test_organization_suspension_preserves_candidate_applications():
    with TestClient(app) as client:
        _e, owner_id, owner = _register(client, "apporg", role="recruiter")
        _e, cand_id, candidate = _register(client, "appcand")
        org = _create_org(client, owner, "Application Preserving Org")
        job_id = _seed_job(client, title="Application Preserving Job", status="published", owner_user_id=owner_id)

        applied = client.post(f"{API}/jobs/{job_id}/apply", headers=candidate, json={"cover_note": "hello"})
        assert applied.status_code in (200, 201), applied.text

        client.post(
            f"{API}/admin/organizations/{org['id']}/suspend",
            headers=ADMIN_HEADERS,
            json={"reason": "policy_violation"},
        )

        # The candidate's own application history is untouched.
        detail = client.get(f"{API}/admin/organizations/{org['id']}", headers=ADMIN_HEADERS).json()
        assert detail["application_count"] >= 1


# ===========================================================================
# 8/9. Job moderation
# ===========================================================================


def test_job_approve_reject_suspend_restore_cycle():
    with TestClient(app) as client:
        job_id = _seed_job(client, title="Moderation Cycle Job", status="review")

        approved = client.post(f"{API}/admin/jobs/{job_id}/approve", headers=ADMIN_HEADERS, json={})
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "published"

        suspended = client.post(
            f"{API}/admin/jobs/{job_id}/suspend",
            headers=ADMIN_HEADERS,
            json={"reason": "misleading_information", "note": "internal note"},
        )
        assert suspended.json()["status"] == "suspended"
        assert suspended.json()["moderation_reason"] == "misleading_information"

        # Suspending twice would destroy the restore point — refused.
        assert (
            client.post(
                f"{API}/admin/jobs/{job_id}/suspend", headers=ADMIN_HEADERS, json={"reason": "spam"}
            ).status_code
            == 409
        )

        restored = client.post(f"{API}/admin/jobs/{job_id}/restore", headers=ADMIN_HEADERS, json={})
        assert restored.json()["status"] == "published"
        assert restored.json()["moderation_reason"] is None


def test_job_rejection_requires_a_valid_reason_and_keeps_the_legacy_route_working():
    with TestClient(app) as client:
        # Legacy V9 call: no body at all. Must still work.
        legacy_id = _seed_job(client, title="Legacy Reject Job", status="review")
        legacy = client.post(f"{API}/admin/jobs/{legacy_id}/reject", headers=ADMIN_HEADERS)
        assert legacy.status_code == 200, legacy.text
        assert legacy.json()["rejected"] is True
        assert legacy.json()["reason"] == "other"

        # Structured call.
        structured_id = _seed_job(client, title="Structured Reject Job", status="review")
        structured = client.post(
            f"{API}/admin/jobs/{structured_id}/reject",
            headers=ADMIN_HEADERS,
            json={"reason": "duplicate_listing", "note": "dupe of 123"},
        )
        assert structured.json()["reason"] == "duplicate_listing"

        # An invalid reason is rejected by the bulk/suspend validators.
        bad_id = _seed_job(client, title="Bad Reason Job", status="published")
        assert (
            client.post(
                f"{API}/admin/jobs/{bad_id}/suspend", headers=ADMIN_HEADERS, json={"reason": "nonsense"}
            ).status_code
            == 422
        )


def test_job_internal_note_is_not_exposed_to_the_public_job_endpoint():
    with TestClient(app) as client:
        job_id = _seed_job(client, title="Internal Note Job", status="published")
        client.post(
            f"{API}/admin/jobs/{job_id}/suspend",
            headers=ADMIN_HEADERS,
            json={"reason": "prohibited_content", "note": "SECRETMODERATORNOTE"},
        )
        public = client.get(f"{API}/jobs/{job_id}")
        assert "SECRETMODERATORNOTE" not in public.text

        # The platform-admin surface does see it.
        admin_view = client.get(f"{API}/admin/jobs?q=Internal Note Job", headers=ADMIN_HEADERS).json()
        assert admin_view["results"][0]["moderation_note"] == "SECRETMODERATORNOTE"


def test_job_list_filters():
    with TestClient(app) as client:
        _seed_job(client, title="Filterable Review Job", status="review")
        page = client.get(f"{API}/admin/jobs?status=review&q=Filterable", headers=ADMIN_HEADERS).json()
        assert page["total"] >= 1
        assert all(r["status"] == "review" for r in page["results"])
        assert client.get(f"{API}/admin/jobs?status=not_a_status", headers=ADMIN_HEADERS).status_code == 422


def test_restore_of_a_job_with_no_prior_status_returns_it_to_review():
    """A restore must never auto-publish. The safe direction is back
    into the queue for a human decision."""
    with TestClient(app) as client:
        job_id = _seed_job(client, title="No Prior Status Job", status="rejected")
        db = SessionLocal()
        try:
            job = db.get(Job, job_id)
            job.pre_moderation_status = None
            db.commit()
        finally:
            db.close()
        restored = client.post(f"{API}/admin/jobs/{job_id}/restore", headers=ADMIN_HEADERS, json={})
        assert restored.json()["status"] == "review"


# ===========================================================================
# 10/11/12/32. Audit
# ===========================================================================


def test_every_admin_action_creates_an_audit_record():
    with TestClient(app) as client:
        _e, uid, _h = _register(client, "auditsubject")
        client.post(
            f"{API}/admin/users/{uid}/suspend",
            headers=ADMIN_HEADERS,
            json={"reason": "abuse_report", "note": "ticket 42"},
        )

        page = client.get(f"{API}/admin/audit?action=USER_SUSPENDED", headers=ADMIN_HEADERS).json()
        assert page["total"] >= 1
        row = page["results"][0]
        assert row["target_type"] == "user"
        assert row["reason"] == "abuse_report"
        assert row["result"] == "success"
        assert row["actor_type"] == "admin_key"
        assert row["created_at"] is not None


def test_audit_filters_and_pagination():
    with TestClient(app) as client:
        _e, uid, _h = _register(client, "auditfilter")
        client.post(f"{API}/admin/users/{uid}/suspend", headers=ADMIN_HEADERS, json={"reason": "spam"})
        client.post(f"{API}/admin/users/{uid}/reactivate", headers=ADMIN_HEADERS, json={})

        by_target = client.get(
            f"{API}/admin/audit?target_type=user&target_id={uid}", headers=ADMIN_HEADERS
        ).json()
        assert by_target["total"] >= 2
        assert all(r["target_id"] == str(uid) for r in by_target["results"])

        history = client.get(f"{API}/admin/users/{uid}/history", headers=ADMIN_HEADERS).json()
        assert history["total"] >= 2

        paged = client.get(f"{API}/admin/audit?limit=1", headers=ADMIN_HEADERS).json()
        assert len(paged["results"]) == 1
        assert client.get(f"{API}/admin/audit?limit=99999", headers=ADMIN_HEADERS).status_code == 422


def test_audit_log_is_append_only_through_the_api():
    """No route exists to edit or delete an audit record."""
    with TestClient(app) as client:
        _e, uid, _h = _register(client, "auditimmutable")
        client.post(f"{API}/admin/users/{uid}/suspend", headers=ADMIN_HEADERS, json={"reason": "spam"})
        row_id = client.get(f"{API}/admin/audit?action=USER_SUSPENDED", headers=ADMIN_HEADERS).json()["results"][0][
            "id"
        ]

        for method in ("put", "patch", "delete", "post"):
            resp = client.request(method.upper(), f"{API}/admin/audit/{row_id}", headers=ADMIN_HEADERS, json={})
            assert resp.status_code in (404, 405), f"{method} on an audit row returned {resp.status_code}"

        db = SessionLocal()
        try:
            assert db.get(PlatformAuditLog, row_id) is not None
        finally:
            db.close()


def test_audit_metadata_never_stores_secretish_keys():
    from app.core.platform_audit import _safe_metadata

    encoded = _safe_metadata(
        {
            "password_hash": "abc",
            "refresh_token": "xyz",
            "api_key": "k",
            "resume_text": "long resume",
            "from_status": "review",
            "ids": list(range(500)),
        }
    )
    assert "abc" not in encoded and "xyz" not in encoded
    assert "resume" not in encoded.lower()
    assert "review" in encoded
    # A large list is summarized, not dumped.
    assert encoded.count("\"sample\"") == 1
    assert len(encoded) < 1000


# ===========================================================================
# 13. Platform search
# ===========================================================================


def test_platform_search_is_scoped_and_authorized():
    with TestClient(app) as client:
        _e, _uid, recruiter = _register(client, "searchscope", role="recruiter")
        _create_org(client, recruiter, "Searchable Scope Organization")
        _seed_job(client, title="Searchable Scope Job", status="published")

        out = client.get(f"{API}/admin/search?q=Searchable Scope", headers=ADMIN_HEADERS).json()["results"]
        assert any("Searchable Scope Organization" == o["name"] for o in out.get("organizations", []))
        assert any("Searchable Scope Job" == j["title"] for j in out.get("jobs", []))

        # Unauthorized callers get nothing at all.
        _e, _cid, candidate = _register(client, "searchcand")
        assert client.get(f"{API}/admin/search?q=Searchable", headers=candidate).status_code == 403


def test_platform_search_rejects_injection_style_input_safely():
    with TestClient(app) as client:
        resp = client.get(f"{API}/admin/search?q='; DROP TABLE users;--", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["results"].get("users") == []
        # The table is very much still there.
        assert client.get(f"{API}/admin/users?limit=1", headers=ADMIN_HEADERS).status_code == 200


# ===========================================================================
# 14/15. Analytics and analytics privacy
# ===========================================================================


def test_analytics_returns_dense_series_and_aggregates():
    with TestClient(app) as client:
        data = client.get(f"{API}/admin/analytics?days=7", headers=ADMIN_HEADERS).json()
        assert data["range_days"] == 7
        assert len(data["users"]["registrations_over_time"]) == 7
        assert all(set(p) == {"date", "count"} for p in data["users"]["registrations_over_time"])
        assert isinstance(data["jobs"]["by_status"], list)
        assert client.get(f"{API}/admin/analytics?days=9999", headers=ADMIN_HEADERS).status_code == 422


def test_analytics_exposes_no_individual_candidate_data():
    with TestClient(app) as client:
        _e, owner_id, owner = _register(client, "privacyowner", role="recruiter")
        _e, _cid, candidate = _register(client, "privacycand")
        job_id = _seed_job(client, title="Privacy Analytics Job", status="published", owner_user_id=owner_id)
        client.post(f"{API}/jobs/{job_id}/apply", headers=candidate, json={"cover_note": "PRIVATECOVERNOTE"})

        body = client.get(f"{API}/admin/analytics?days=30", headers=ADMIN_HEADERS).text
        assert "PRIVATECOVERNOTE" not in body
        assert "v252privacycand@example.com" not in body
        # No demographic breakdown exists anywhere in the payload.
        for term in ("gender", "ethnicity", "age_group", "religion", "disability"):
            assert term not in body.lower()


# ===========================================================================
# 16/17/18. System health
# ===========================================================================


def test_system_health_reports_real_indicators_without_secrets():
    with TestClient(app) as client:
        health = client.get(f"{API}/admin/system/health", headers=ADMIN_HEADERS).json()
        names = {i["name"] for i in health["indicators"]}
        assert {"api", "database", "migrations", "email", "ai_provider", "ingestion"} <= names
        assert health["status"] in ("ok", "degraded", "error")

        database = next(i for i in health["indicators"] if i["name"] == "database")
        assert database["status"] == "ok"
        # Driver family only — never the DSN.
        assert database["driver"] in ("sqlite", "postgresql")
        body = client.get(f"{API}/admin/system/health", headers=ADMIN_HEADERS).text
        for secret in ("change-this-admin-key", "change-this-jwt-secret", "sqlite:///"):
            assert secret not in body


def test_unconfigured_providers_report_unknown_not_ok():
    """An unconfigured optional provider is 'unknown', never a
    fabricated green light — and never degrades the overall status."""
    with TestClient(app) as client:
        health = client.get(f"{API}/admin/system/health", headers=ADMIN_HEADERS).json()
        ai = next(i for i in health["indicators"] if i["name"] == "ai_provider")
        assert ai["status"] == "unknown"
        assert ai["configured"] is False


def test_background_jobs_and_ingestion_report_only_real_state():
    with TestClient(app) as client:
        jobs = client.get(f"{API}/admin/system/background-jobs", headers=ADMIN_HEADERS).json()
        assert jobs["queues"][0]["name"] == "email"
        assert all(isinstance(jobs["queues"][0][k], int) for k in ("queued", "sent", "failed", "retrying"))

        ingestion = client.get(f"{API}/admin/system/ingestion", headers=ADMIN_HEADERS).json()
        # Ingestion is disabled by default in this deployment and the
        # response says so rather than implying sources are live.
        assert ingestion["globally_enabled"] is False
        assert ingestion["note"]
        assert all(s["currently_collecting"] is False for s in ingestion["sources"])


def test_admin_cannot_execute_arbitrary_background_jobs():
    with TestClient(app) as client:
        # The only queue action is re-queueing specific failed emails.
        resp = client.post(
            f"{API}/admin/system/background-jobs/email/retry",
            headers=ADMIN_HEADERS,
            json={"message_ids": [999999]},
        )
        assert resp.status_code == 200
        assert resp.json()["requeued"] == 0
        # There is no generic "run this job" route.
        assert client.post(f"{API}/admin/system/background-jobs/run", headers=ADMIN_HEADERS, json={}).status_code in (
            404,
            405,
        )


# ===========================================================================
# 19/20. Settings and maintenance mode
# ===========================================================================


def test_settings_are_typed_and_validated():
    with TestClient(app) as client:
        _reset_settings()
        listing = client.get(f"{API}/admin/settings", headers=ADMIN_HEADERS).json()["settings"]
        keys = {s["key"] for s in listing}
        assert "maintenance_mode" in keys and "registration_enabled" in keys

        # Unknown key -> 404, not a silently-created setting.
        assert (
            client.put(f"{API}/admin/settings/totally_made_up", headers=ADMIN_HEADERS, json={"value": 1}).status_code
            == 404
        )
        # Wrong type -> 422.
        assert (
            client.put(
                f"{API}/admin/settings/announcement_max_recipients", headers=ADMIN_HEADERS, json={"value": "abc"}
            ).status_code
            == 422
        )
        # Out of bounds -> 422.
        assert (
            client.put(
                f"{API}/admin/settings/announcement_max_recipients", headers=ADMIN_HEADERS, json={"value": 0}
            ).status_code
            == 422
        )

        ok = client.put(f"{API}/admin/settings/ai_features_enabled", headers=ADMIN_HEADERS, json={"value": False})
        assert ok.status_code == 200
        assert ok.json()["value"] is False
        _reset_settings()


def test_setting_change_is_audited():
    with TestClient(app) as client:
        _reset_settings()
        client.put(f"{API}/admin/settings/ai_features_enabled", headers=ADMIN_HEADERS, json={"value": False})
        page = client.get(f"{API}/admin/audit?action=PLATFORM_SETTING_CHANGED", headers=ADMIN_HEADERS).json()
        assert page["total"] >= 1
        assert page["results"][0]["target_id"] == "ai_features_enabled"
        _reset_settings()


def test_registration_can_be_closed_by_setting():
    with TestClient(app) as client:
        _reset_settings()
        client.put(f"{API}/admin/settings/registration_enabled", headers=ADMIN_HEADERS, json={"value": False})
        blocked = client.post(
            f"{API}/auth/register",
            json={
                "email": "v252blocked@example.com",
                "password": PW,
                "password_confirm": PW,
                "full_name": "Blocked",
            },
        )
        assert blocked.status_code == 403
        _reset_settings()
        # Reopened.
        assert (
            client.post(
                f"{API}/auth/register",
                json={
                    "email": "v252reopened@example.com",
                    "password": PW,
                    "password_confirm": PW,
                    "full_name": "Reopened",
                },
            ).status_code
            == 201
        )


def test_maintenance_mode_blocks_users_but_never_admins_or_health():
    with TestClient(app) as client:
        _reset_settings()
        _e, _uid, candidate = _register(client, "maintcand")
        client.put(f"{API}/admin/settings/maintenance_mode", headers=ADMIN_HEADERS, json={"value": True})

        blocked = client.get(f"{API}/jobs", headers=candidate)
        assert blocked.status_code == 503
        assert blocked.json()["maintenance"] is True
        assert blocked.headers.get("Retry-After")

        # Administrators keep working — so they can turn it back off.
        assert client.get(f"{API}/admin/dashboard", headers=ADMIN_HEADERS).status_code == 200
        # Health/liveness endpoints stay available for orchestrators.
        assert client.get("/health").status_code == 200
        assert client.get("/live").status_code == 200
        assert client.get("/ready").status_code == 200
        # Login stays reachable, or the admin exemption is unreachable.
        assert client.post(f"{API}/auth/login", json={"email": "nobody@example.com", "password": PW}).status_code != 503

        client.put(f"{API}/admin/settings/maintenance_mode", headers=ADMIN_HEADERS, json={"value": False})
        _reset_settings()
        assert client.get(f"{API}/jobs", headers=candidate).status_code == 200


# ===========================================================================
# 21. Announcements
# ===========================================================================


def test_announcement_requires_an_explicit_second_send_step():
    with TestClient(app) as client:
        _reset_settings()
        _register(client, "announcetarget")

        created = client.post(
            f"{API}/admin/announcements",
            headers=ADMIN_HEADERS,
            json={"title": "Scheduled maintenance", "message": "We will be down briefly.", "audience": "CANDIDATES"},
        )
        assert created.status_code == 201
        announcement_id = created.json()["id"]
        # Creation delivered nothing.
        assert created.json()["status"] == "DRAFT"
        assert created.json()["recipient_count"] == 0

        sent = client.post(f"{API}/admin/announcements/{announcement_id}/send", headers=ADMIN_HEADERS)
        assert sent.status_code == 200, sent.text
        assert sent.json()["status"] == "SENT"
        assert sent.json()["delivered"] >= 1

        # Re-sending is refused, so a retry cannot double-post.
        assert client.post(f"{API}/admin/announcements/{announcement_id}/send", headers=ADMIN_HEADERS).status_code == 409


def test_announcement_email_is_off_unless_explicitly_enabled():
    with TestClient(app) as client:
        _reset_settings()
        created = client.post(
            f"{API}/admin/announcements",
            headers=ADMIN_HEADERS,
            json={"title": "Email test", "message": "Body", "audience": "CANDIDATES", "channel": "BOTH"},
        ).json()
        sent = client.post(f"{API}/admin/announcements/{created['id']}/send", headers=ADMIN_HEADERS).json()
        assert sent["email_channel_allowed"] is False
        assert sent["emails_queued"] == 0
        assert "in-app only" in (sent["note"] or "")


def test_announcement_send_is_audited():
    with TestClient(app) as client:
        created = client.post(
            f"{API}/admin/announcements",
            headers=ADMIN_HEADERS,
            json={"title": "Audited announcement", "message": "Body", "audience": "PLATFORM_ADMINS"},
        ).json()
        client.post(f"{API}/admin/announcements/{created['id']}/send", headers=ADMIN_HEADERS)
        page = client.get(f"{API}/admin/audit?action=ANNOUNCEMENT_SENT", headers=ADMIN_HEADERS).json()
        assert page["total"] >= 1


# ===========================================================================
# 27. Bulk actions
# ===========================================================================


def test_bulk_job_moderation_reports_partial_failure_and_audits_each_item():
    with TestClient(app) as client:
        good_a = _seed_job(client, title="Bulk Job A", status="review")
        good_b = _seed_job(client, title="Bulk Job B", status="review")

        resp = client.post(
            f"{API}/admin/bulk/jobs/moderate",
            headers=ADMIN_HEADERS,
            json={"job_ids": [good_a, good_b, 99999999], "action": "reject", "reason": "spam"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["result"] == "partial"
        assert set(body["succeeded"]) == {good_a, good_b}
        assert body["failed"][0]["job_id"] == 99999999

        # One audit row per item, plus a batch summary row.
        per_item = client.get(f"{API}/admin/audit?action=JOB_REJECTED", headers=ADMIN_HEADERS).json()
        assert per_item["total"] >= 2
        summary = client.get(f"{API}/admin/audit?action=BULK_JOB_MODERATION", headers=ADMIN_HEADERS).json()
        assert summary["total"] >= 1


def test_bulk_actions_are_bounded_and_offer_no_deletion():
    with TestClient(app) as client:
        too_many = client.post(
            f"{API}/admin/bulk/jobs/moderate",
            headers=ADMIN_HEADERS,
            json={"job_ids": list(range(1, 200)), "action": "approve"},
        )
        assert too_many.status_code == 422

        # A reason is mandatory for the destructive-ish transitions.
        assert (
            client.post(
                f"{API}/admin/bulk/jobs/moderate",
                headers=ADMIN_HEADERS,
                json={"job_ids": [1], "action": "reject"},
            ).status_code
            == 422
        )
        # No bulk delete route exists at all.
        assert client.post(f"{API}/admin/bulk/jobs/delete", headers=ADMIN_HEADERS, json={}).status_code in (404, 405)


# ===========================================================================
# Regression — V25.1 and earlier must keep working
# ===========================================================================


def test_v25_1_organization_workflow_still_works():
    with TestClient(app) as client:
        _e, _uid, owner = _register(client, "regowner", role="recruiter")
        _member_email, _mid, member = _register(client, "regmember", role="recruiter")
        org = _create_org(client, owner, "Regression Organization")

        invite = client.post(
            f"{API}/organizations/{org['id']}/members/invite",
            headers=owner,
            json={"email": "v252regmember@example.com", "role": "RECRUITER"},
        )
        assert invite.status_code == 201, invite.text
        accepted = client.post(
            f"{API}/organization-invitations/{invite.json()['token']}/accept", headers=member
        )
        assert accepted.status_code == 200, accepted.text

        members = client.get(f"{API}/organizations/{org['id']}/members", headers=owner).json()
        assert len(members) == 2


def test_cross_tenant_isolation_still_holds_and_is_now_logged():
    with TestClient(app) as client:
        _e, _a, owner_a = _register(client, "tenanta", role="recruiter")
        _e, _b, owner_b = _register(client, "tenantb", role="recruiter")
        org_a = _create_org(client, owner_a, "Tenant A Organization")

        blocked = client.get(f"{API}/organizations/{org_a['id']}/members", headers=owner_b)
        assert blocked.status_code == 404

        events = client.get(
            f"{API}/admin/security/events?action=cross_tenant_access_attempt", headers=ADMIN_HEADERS
        ).json()
        assert events["total"] >= 1


def test_legacy_admin_routes_still_work():
    with TestClient(app) as client:
        assert client.get(f"{API}/admin/stats", headers=ADMIN_HEADERS).status_code == 200
        assert client.get(f"{API}/admin/review", headers=ADMIN_HEADERS).status_code == 200
        assert client.get(f"{API}/admin/audit-logs", headers=ADMIN_HEADERS).status_code == 200
        assert client.get(f"{API}/admin/recruiters/pending", headers=ADMIN_HEADERS).status_code == 200

        job_id = _seed_job(client, title="Legacy Publish Job", status="review")
        published = client.post(f"{API}/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)
        assert published.status_code == 200
        assert published.json() == {"published": True, "id": job_id}


def test_candidate_and_recruiter_core_flows_unaffected():
    with TestClient(app) as client:
        _e, _uid, candidate = _register(client, "regflow")
        assert client.get(f"{API}/jobs").status_code == 200
        assert client.get(f"{API}/auth/me", headers=candidate).status_code == 200
        assert client.get(f"{API}/notifications", headers=candidate).status_code == 200
