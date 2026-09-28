"""V22.2 — Smart Application Dashboard & Kanban tests (backend).

Covers what's new this version: status transition rules (terminal
states require explicit reopen), the /applications/dashboard and
/applications/upcoming-deadlines endpoints, conversion-rate honesty at
zero sample size, and that all of this remains correctly
ownership-isolated. The Kanban/dashboard UI itself has no backend
logic of its own to unit test here — it's covered by
V22.1's + this file's API-level tests plus the frontend production
build (see V22_2_APPLICATION_DASHBOARD.md's Testing section).
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v22_2.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

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
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_application(client, headers, **overrides):
    payload = {"company": "Acme", "job_title": "Engineer", "status": "APPLIED"}
    payload.update(overrides)
    resp = client.post("/api/v1/applications", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _set_status(client, headers, app_id, status, **kwargs):
    return client.post(f"/api/v1/applications/{app_id}/status", headers=headers, json={"status": status, **kwargs})


# ---------------------------------------------------------------------------
# Status transition rules
# ---------------------------------------------------------------------------


def test_forward_transitions_are_never_blocked(client):
    headers = _register_and_login(client, "v22_2fwd")
    a = _create_application(client, headers, status="APPLIED")
    for status in ["ASSESSMENT", "INTERVIEW", "OFFER"]:
        r = _set_status(client, headers, a["id"], status)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == status


def test_skipping_stages_is_allowed_not_unnecessarily_restrictive(client):
    headers = _register_and_login(client, "v22_2skip")
    a = _create_application(client, headers, status="APPLIED")
    # Straight to REJECTED with no assessment/interview step — a very
    # real outcome the spec explicitly says must not be blocked.
    r = _set_status(client, headers, a["id"], "REJECTED")
    assert r.status_code == 200


def test_lateral_move_between_non_terminal_stages_allowed(client):
    headers = _register_and_login(client, "v22_2lateral")
    a = _create_application(client, headers, status="INTERVIEW")
    r = _set_status(client, headers, a["id"], "ASSESSMENT")
    assert r.status_code == 200


def test_terminal_status_requires_explicit_reopen(client):
    headers = _register_and_login(client, "v22_2reopen")
    a = _create_application(client, headers, status="OFFER")
    _set_status(client, headers, a["id"], "ACCEPTED")

    blocked = _set_status(client, headers, a["id"], "INTERVIEW")
    assert blocked.status_code == 409

    reopened = _set_status(client, headers, a["id"], "INTERVIEW", reopen=True)
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "INTERVIEW"


def test_reopen_via_patch_also_works(client):
    headers = _register_and_login(client, "v22_2reopenpatch")
    a = _create_application(client, headers, status="OFFER")
    _set_status(client, headers, a["id"], "REJECTED")

    blocked = client.patch(f"/api/v1/applications/{a['id']}", headers=headers, json={"status": "APPLIED"})
    assert blocked.status_code == 409

    reopened = client.patch(f"/api/v1/applications/{a['id']}", headers=headers, json={"status": "APPLIED", "reopen": True})
    assert reopened.status_code == 200


def test_setting_terminal_status_to_itself_never_requires_reopen(client):
    headers = _register_and_login(client, "v22_2noop")
    a = _create_application(client, headers, status="REJECTED")
    r = _set_status(client, headers, a["id"], "REJECTED")
    assert r.status_code == 200


def test_ghosted_is_freely_reversible_not_terminal(client):
    headers = _register_and_login(client, "v22_2ghost")
    a = _create_application(client, headers, status="GHOSTED")
    r = _set_status(client, headers, a["id"], "INTERVIEW")
    assert r.status_code == 200, "GHOSTED should not require reopen to move out of"


def test_invalid_status_still_rejected_with_reopen_true(client):
    headers = _register_and_login(client, "v22_2invalid")
    a = _create_application(client, headers, status="APPLIED")
    r = _set_status(client, headers, a["id"], "NOT_A_REAL_STATUS", reopen=True)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def test_dashboard_reflects_real_counts_not_fake_data(client):
    headers = _register_and_login(client, "v22_2dash")
    _create_application(client, headers, company="A", job_title="X", status="APPLIED")
    _create_application(client, headers, company="B", job_title="Y", status="INTERVIEW")
    _create_application(client, headers, company="C", job_title="Z", status="OFFER")

    dash = client.get("/api/v1/applications/dashboard", headers=headers).json()
    assert dash["total"] == 3
    assert dash["by_status"]["APPLIED"] == 1
    assert dash["by_status"]["INTERVIEW"] == 1
    assert dash["by_status"]["OFFER"] == 1
    assert dash["applications_this_week"] >= 3
    assert dash["applications_this_month"] >= 3
    assert "recent_activity" in dash
    assert "upcoming_deadlines" in dash


def test_dashboard_stats_isolated_per_user(client):
    headers_a = _register_and_login(client, "v22_2dashA")
    headers_b = _register_and_login(client, "v22_2dashB")
    _create_application(client, headers_a, company="OnlyA")

    dash_b = client.get("/api/v1/applications/dashboard", headers=headers_b).json()
    assert dash_b["total"] == 0


def test_conversion_rate_is_null_not_misleading_zero_with_no_sample(client):
    headers = _register_and_login(client, "v22_2conv0")
    dash = client.get("/api/v1/applications/dashboard", headers=headers).json()
    assert dash["conversion_rates"]["applied_to_interview"] is None
    assert dash["conversion_rates"]["interview_to_offer"] is None
    assert dash["conversion_rates"]["offer_to_acceptance"] is None


def test_conversion_rate_computed_from_history_not_current_status_only(client):
    """A rejected-after-interview application's *current* status is
    REJECTED, not INTERVIEW — the conversion rate must still count it
    as having reached INTERVIEW, since it really did."""
    headers = _register_and_login(client, "v22_2convhist")
    a = _create_application(client, headers, status="APPLIED")
    _set_status(client, headers, a["id"], "INTERVIEW")
    _set_status(client, headers, a["id"], "REJECTED")

    dash = client.get("/api/v1/applications/dashboard", headers=headers).json()
    assert dash["conversion_rates"]["applied_to_interview"] == 1.0


def test_dashboard_requires_authentication(client):
    r = client.get("/api/v1/applications/dashboard")
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Upcoming deadlines
# ---------------------------------------------------------------------------


def test_upcoming_deadlines_sorted_nearest_first(client):
    from datetime import date, timedelta

    headers = _register_and_login(client, "v22_2deadlines")
    far = (date.today() + timedelta(days=20)).isoformat()
    near = (date.today() + timedelta(days=2)).isoformat()
    _create_application(client, headers, company="Far", job_title="F", deadline=far)
    _create_application(client, headers, company="Near", job_title="N", deadline=near)

    resp = client.get("/api/v1/applications/upcoming-deadlines", headers=headers)
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    assert items[0]["company"] == "Near"
    assert items[0]["urgency"] == "due_soon"
    assert items[1]["urgency"] == "upcoming"


def test_overdue_deadline_flagged_correctly(client):
    from datetime import date, timedelta

    headers = _register_and_login(client, "v22_2overdue")
    past = (date.today() - timedelta(days=2)).isoformat()
    a = _create_application(client, headers, company="Late Co", job_title="L", status="PLANNING_TO_APPLY")
    client.patch(f"/api/v1/applications/{a['id']}", headers=headers, json={"deadline": past})

    resp = client.get("/api/v1/applications/upcoming-deadlines", headers=headers).json()
    match = next((i for i in resp if i["application_id"] == a["id"]), None)
    assert match is not None
    assert match["urgency"] == "overdue"


def test_terminal_applications_excluded_from_upcoming_deadlines(client):
    from datetime import date, timedelta

    headers = _register_and_login(client, "v22_2termdeadline")
    soon = (date.today() + timedelta(days=1)).isoformat()
    a = _create_application(client, headers, company="Done Co", job_title="D", status="OFFER", deadline=soon)
    _set_status(client, headers, a["id"], "ACCEPTED")

    resp = client.get("/api/v1/applications/upcoming-deadlines", headers=headers).json()
    assert not any(i["application_id"] == a["id"] for i in resp)


def test_upcoming_deadlines_isolated_per_user(client):
    from datetime import date, timedelta

    headers_a = _register_and_login(client, "v22_2ddA")
    headers_b = _register_and_login(client, "v22_2ddB")
    soon = (date.today() + timedelta(days=1)).isoformat()
    _create_application(client, headers_a, company="PrivateToA", deadline=soon)

    resp_b = client.get("/api/v1/applications/upcoming-deadlines", headers=headers_b).json()
    assert not any(i["company"] == "PrivateToA" for i in resp_b)


def test_upcoming_deadlines_requires_authentication(client):
    r = client.get("/api/v1/applications/upcoming-deadlines")
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_search_matches_job_title(client):
    headers = _register_and_login(client, "v22_2searchtitle")
    _create_application(client, headers, company="Zed Co", job_title="Unique Wizard Role")
    resp = client.get("/api/v1/applications", headers=headers, params={"search": "Wizard"})
    assert resp.status_code == 200
    assert any(a["job_title"] == "Unique Wizard Role" for a in resp.json()["items"])


def test_search_matches_location(client):
    headers = _register_and_login(client, "v22_2searchloc")
    _create_application(client, headers, company="Loc Co", job_title="Engineer", location="Kathmandu")
    resp = client.get("/api/v1/applications", headers=headers, params={"search": "Kathmandu"})
    assert resp.status_code == 200
    assert any(a["location"] == "Kathmandu" for a in resp.json()["items"])


def test_search_isolated_per_user(client):
    headers_a = _register_and_login(client, "v22_2searchA")
    headers_b = _register_and_login(client, "v22_2searchB")
    _create_application(client, headers_a, company="OnlySearchableByA", job_title="Secret Role")
    resp_b = client.get("/api/v1/applications", headers=headers_b, params={"search": "Secret Role"})
    assert resp_b.json()["items"] == []





def test_v22_1_stats_endpoint_shape_unchanged(client):
    """The dashboard endpoint is additive — /stats keeps its original
    shape for any existing caller (the candidate dashboard widget)."""
    headers = _register_and_login(client, "v22_2statsshape")
    _create_application(client, headers)
    stats = client.get("/api/v1/applications/stats", headers=headers).json()
    assert set(stats.keys()) == {"total", "by_status", "recent_activity"}


def test_v21_1_search_still_works(client):
    r = client.get("/api/v1/search", params={"q": "engineer"})
    assert r.status_code == 200


def test_v21_3_recommendations_still_work(client):
    headers = _register_and_login(client, "v22_2recregress")
    r = client.get("/api/v1/job-recommendations", headers=headers)
    assert r.status_code == 200
