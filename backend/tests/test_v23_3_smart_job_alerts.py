"""V23.3 — Smart Job Alerts & Personalized Job Notifications tests.

Uses EMAIL_MODE=console (no real SMTP), same convention as
test_v23_2_email_system.py. Jobs are created via POST /admin/ingest +
publish, same convention as test_v21_3_ai_job_recommendation_engine.py
— skill detection comes from the shared SKILLS vocabulary scanning
title/description/qualification (search indexing hooks pick these up
in real time), so requested skill words are embedded in the
description, exactly as that suite already does.

PRE-EXISTING BUG FOUND (not introduced by V23.3, not fixed here — see
this file's final report / docs/V23_3_SMART_JOB_ALERTS.md "Known
limitations"): app/api/platform.py defines its own V7
``GET /notifications`` (and ``POST .../read``) that is registered in
app.api.routes BEFORE app.api.notifications' richer V23.1 versions of
the same paths, so the V7 route silently wins and V23.1's `category`
query-param filtering is never reached. Tests below that need to
assert on notification content query the Notification table directly
rather than depend on that (broken) endpoint.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v23_3.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"
os.environ["EMAIL_MODE"] = "console"
os.environ["SCHEDULER_ENABLED"] = "false"

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


def _create_and_publish_job(client, **overrides) -> int:
    _counter["n"] += 1
    skills = overrides.pop("skills", "Python,SQL,AWS")
    payload = {
        "title": f"Python Developer V23.3 #{_counter['n']}",
        "organization": "Acme Corp",
        "description": f"Looking for someone with skills in {skills}.",
        "qualification": "B.Tech",
        "location": "Noida",
        "job_type": "Private",
        "source_name": "V23.3 Test",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/admin/ingest", headers=ADMIN_HEADERS, json=payload)
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["job_id"]
    pub = client.post(f"/api/v1/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)
    assert pub.status_code == 200, pub.text
    return job_id


def _set_profile(client, headers, **overrides):
    payload = {"skills": "Python,SQL", "location": "Noida", "highest_qualification": "Graduate"}
    payload.update(overrides)
    resp = client.put("/api/v1/profile", headers=headers, json=payload)
    assert resp.status_code == 200, resp.text


def _create_alert(client, headers, **overrides) -> dict:
    payload = {"name": f"Alert {_counter['n']}", "keywords": "python developer", "location": "Noida"}
    payload.update(overrides)
    resp = client.post("/api/v1/job-alerts", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_create_alert(client):
    headers = _register_and_login(client, "crud")
    alert = _create_alert(client, headers, name="My First Alert")
    assert alert["name"] == "My First Alert"
    assert alert["frequency"] == "INSTANT"
    assert alert["enabled"] is True
    assert alert["last_run_at"] is None


def test_create_alert_allows_all_fields_optional(client):
    headers = _register_and_login(client, "crudmin")
    resp = client.post("/api/v1/job-alerts", headers=headers, json={"name": "Bare minimum"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["keywords"] is None


def test_update_alert(client):
    headers = _register_and_login(client, "update")
    alert = _create_alert(client, headers)
    resp = client.patch(f"/api/v1/job-alerts/{alert['id']}", headers=headers, json={"location": "Pune", "frequency": "WEEKLY"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["location"] == "Pune"
    assert body["frequency"] == "WEEKLY"
    # untouched fields survive a partial update
    assert body["keywords"] == "python developer"


def test_delete_alert(client):
    headers = _register_and_login(client, "delete")
    alert = _create_alert(client, headers)
    resp = client.delete(f"/api/v1/job-alerts/{alert['id']}", headers=headers)
    assert resp.status_code == 204
    resp = client.get(f"/api/v1/job-alerts/{alert['id']}", headers=headers)
    assert resp.status_code == 404


def test_enable_disable_alert(client):
    headers = _register_and_login(client, "enable")
    alert = _create_alert(client, headers)
    resp = client.post(f"/api/v1/job-alerts/{alert['id']}/disable", headers=headers)
    assert resp.status_code == 200 and resp.json()["enabled"] is False
    resp = client.post(f"/api/v1/job-alerts/{alert['id']}/enable", headers=headers)
    assert resp.status_code == 200 and resp.json()["enabled"] is True


def test_list_alerts(client):
    headers = _register_and_login(client, "list")
    _create_alert(client, headers, name="A")
    _create_alert(client, headers, name="B")
    resp = client.get("/api/v1/job-alerts", headers=headers)
    assert resp.status_code == 200
    names = {a["name"] for a in resp.json()}
    assert {"A", "B"}.issubset(names)


# ---------------------------------------------------------------------------
# Ownership isolation (IDOR)
# ---------------------------------------------------------------------------


def test_ownership_isolation(client):
    owner_headers = _register_and_login(client, "owner")
    other_headers = _register_and_login(client, "other")
    alert = _create_alert(client, owner_headers)
    aid = alert["id"]

    assert client.get(f"/api/v1/job-alerts/{aid}", headers=other_headers).status_code == 404
    assert client.patch(f"/api/v1/job-alerts/{aid}", headers=other_headers, json={"name": "hacked"}).status_code == 404
    assert client.delete(f"/api/v1/job-alerts/{aid}", headers=other_headers).status_code == 404
    assert client.post(f"/api/v1/job-alerts/{aid}/disable", headers=other_headers).status_code == 404
    assert client.post(f"/api/v1/job-alerts/{aid}/run-now", headers=other_headers).status_code == 404
    assert client.get(f"/api/v1/job-alerts/{aid}/matches", headers=other_headers).status_code == 404
    assert client.get(f"/api/v1/job-alerts/{aid}/history", headers=other_headers).status_code == 404

    # the real owner is unaffected
    assert client.get(f"/api/v1/job-alerts/{aid}", headers=owner_headers).status_code == 200
    assert client.get(f"/api/v1/job-alerts/{aid}", headers=owner_headers).json()["name"] != "hacked"


def test_alerts_isolated_per_user_in_list(client):
    a_headers = _register_and_login(client, "isoa")
    b_headers = _register_and_login(client, "isob")
    _create_alert(client, a_headers, name="A-only")
    names_for_b = {a["name"] for a in client.get("/api/v1/job-alerts", headers=b_headers).json()}
    assert "A-only" not in names_for_b


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_invalid_frequency_rejected(client):
    headers = _register_and_login(client, "badfreq")
    resp = client.post("/api/v1/job-alerts", headers=headers, json={"name": "x", "frequency": "HOURLY"})
    assert resp.status_code == 422


def test_blank_name_rejected(client):
    headers = _register_and_login(client, "blankname")
    resp = client.post("/api/v1/job-alerts", headers=headers, json={"name": "   "})
    assert resp.status_code == 422


def test_salary_max_below_min_rejected(client):
    headers = _register_and_login(client, "badsalary")
    resp = client.post("/api/v1/job-alerts", headers=headers, json={"name": "x", "salary_min": 100, "salary_max": 10})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Matching / preview
# ---------------------------------------------------------------------------


def test_matching_finds_relevant_job(client):
    headers = _register_and_login(client, "match")
    job_id = _create_and_publish_job(client, title="Backend Python Engineer", location="Noida")
    alert = _create_alert(client, headers, keywords="backend python engineer", location="Noida")
    resp = client.get(f"/api/v1/job-alerts/{alert['id']}/matches", headers=headers)
    assert resp.status_code == 200, resp.text
    job_ids = {m["job_id"] for m in resp.json()["items"]}
    assert job_id in job_ids


def test_matching_excludes_non_matching_location(client):
    headers = _register_and_login(client, "matchloc")
    _create_and_publish_job(client, title="Rare Unique Title Nine", location="Mumbai")
    alert = _create_alert(client, headers, keywords="rare unique title nine", location="Chennai")
    resp = client.get(f"/api/v1/job-alerts/{alert['id']}/matches", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_preview_unsaved_alert(client):
    headers = _register_and_login(client, "preview")
    job_id = _create_and_publish_job(client, title="Preview Target Role", location="Noida")
    resp = client.post(
        "/api/v1/job-alerts/preview", headers=headers, json={"name": "unsaved", "keywords": "preview target role"}
    )
    assert resp.status_code == 200, resp.text
    job_ids = {m["job_id"] for m in resp.json()["items"]}
    assert job_id in job_ids


def test_relevance_threshold_filters_low_scores(client):
    headers = _register_and_login(client, "threshold")
    _create_and_publish_job(client, title="Threshold Test Role Unique", location="Noida")
    high_bar = _create_alert(client, headers, keywords="threshold test role unique", min_relevance_score=99)
    resp = client.get(f"/api/v1/job-alerts/{high_bar['id']}/matches", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_personalized_matching_uses_profile(client):
    headers = _register_and_login(client, "personal")
    _set_profile(client, headers, skills="Python,SQL", location="Noida")
    job_id = _create_and_publish_job(client, title="Personalized Python Role", location="Noida", skills="Python,SQL")
    alert = _create_alert(
        client, headers, name="Personalized", keywords="personalized python role", use_profile_personalization=True
    )
    resp = client.get(f"/api/v1/job-alerts/{alert['id']}/matches", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert any(m["job_id"] == job_id for m in items)
    match = next(m for m in items if m["job_id"] == job_id)
    assert match["relevance_score"] > 0
    assert any("skill" in r.lower() for r in match["match_reasons"])


# ---------------------------------------------------------------------------
# Execution / deduplication / idempotency
# ---------------------------------------------------------------------------


def test_run_now_delivers_instant_notification_and_email(client):
    headers = _register_and_login(client, "instant")
    _create_and_publish_job(client, title="Instant Alert Target Role", location="Noida")
    alert = _create_alert(client, headers, keywords="instant alert target role")

    resp = client.post(f"/api/v1/job-alerts/{alert['id']}/run-now", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "SUCCESS"
    assert body["jobs_matched"] == 1
    assert body["notifications_created"] == 1
    assert body["emails_queued"] == 1

    notifs = client.get("/api/v1/notifications?category=JOB", headers=headers)
    assert notifs.status_code == 200
    from app.db.session import SessionLocal
    from app.models.domain import Notification

    db = SessionLocal()
    try:
        rows = db.query(Notification).filter(Notification.dedupe_key.like(f"job_alert_match:{alert['id']}:%")).all()
        assert len(rows) == 1
    finally:
        db.close()


def test_run_now_is_idempotent_no_duplicate_delivery(client):
    headers = _register_and_login(client, "idempotent")
    _create_and_publish_job(client, title="Idempotent Target Role", location="Noida")
    alert = _create_alert(client, headers, keywords="idempotent target role")

    first = client.post(f"/api/v1/job-alerts/{alert['id']}/run-now", headers=headers).json()
    assert first["jobs_matched"] == 1 and first["notifications_created"] == 1 and first["emails_queued"] == 1

    second = client.post(f"/api/v1/job-alerts/{alert['id']}/run-now", headers=headers).json()
    assert second["notifications_created"] == 0
    assert second["emails_queued"] == 0

    from app.db.session import SessionLocal
    from app.models.domain import Notification

    db = SessionLocal()
    try:
        rows = db.query(Notification).filter(Notification.dedupe_key.like(f"job_alert_match:{alert['id']}:%")).all()
        assert len(rows) == 1  # never duplicated across two runs
    finally:
        db.close()


def test_deduplication_record_prevents_reprocessing_same_job(client):
    headers = _register_and_login(client, "dedupdb")
    job_id = _create_and_publish_job(client, title="Dedup Record Target Role", location="Noida")
    alert = _create_alert(client, headers, keywords="dedup record target role")
    client.post(f"/api/v1/job-alerts/{alert['id']}/run-now", headers=headers)

    from app.db.session import SessionLocal
    from app.models.domain import JobAlertDelivery

    db = SessionLocal()
    try:
        rows = db.query(JobAlertDelivery).filter(
            JobAlertDelivery.job_alert_id == alert["id"], JobAlertDelivery.job_id == job_id
        ).all()
        channels = {r.channel for r in rows}
        assert channels == {"IN_APP", "EMAIL"}
        assert len(rows) == 2  # exactly one delivery row per channel, never duplicated
    finally:
        db.close()


def test_history_records_each_run(client):
    headers = _register_and_login(client, "history")
    alert = _create_alert(client, headers)
    client.post(f"/api/v1/job-alerts/{alert['id']}/run-now", headers=headers)
    client.post(f"/api/v1/job-alerts/{alert['id']}/run-now", headers=headers)
    resp = client.get(f"/api/v1/job-alerts/{alert['id']}/history", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    assert all(i["status"] == "SUCCESS" for i in items)


# ---------------------------------------------------------------------------
# Digest (DAILY / WEEKLY)
# ---------------------------------------------------------------------------


def _run_digest_test(client, frequency: str, template_key: str):
    headers = _register_and_login(client, frequency.lower())
    for i in range(3):
        _create_and_publish_job(client, title=f"{frequency} Digest Unique Role {i}", location="Noida")
    alert = _create_alert(client, headers, keywords=f"{frequency.lower()} digest unique role", frequency=frequency)

    resp = client.post(f"/api/v1/job-alerts/{alert['id']}/run-now", headers=headers)
    body = resp.json()
    assert body["jobs_matched"] == 3
    assert body["notifications_created"] == 3  # in-app is per-job regardless of frequency
    assert body["emails_queued"] == 1  # exactly ONE digest email, never one per job

    from app.db.session import SessionLocal
    from app.models.domain import EmailMessage

    db = SessionLocal()
    try:
        digest_msgs = [m for m in db.query(EmailMessage).filter(EmailMessage.template_key == template_key).all()]
        assert len(digest_msgs) >= 1
        latest = digest_msgs[-1]
        assert '"match_count": "3"' in latest.variables_json
    finally:
        db.close()


def test_daily_digest_aggregates_into_one_email(client):
    _run_digest_test(client, "DAILY", "JOB_ALERT_DAILY")


def test_weekly_digest_aggregates_into_one_email(client):
    _run_digest_test(client, "WEEKLY", "JOB_ALERT_WEEKLY")


# ---------------------------------------------------------------------------
# Preference enforcement
# ---------------------------------------------------------------------------


def test_email_preference_disabled_blocks_email_not_in_app(client):
    headers = _register_and_login(client, "emailpref")
    client.put("/api/v1/notifications/preferences", headers=headers, json={"email_job": False})
    _create_and_publish_job(client, title="Email Pref Target Role", location="Noida")
    alert = _create_alert(client, headers, keywords="email pref target role")

    resp = client.post(f"/api/v1/job-alerts/{alert['id']}/run-now", headers=headers).json()
    assert resp["notifications_created"] == 1  # in-app unaffected
    assert resp["emails_queued"] == 0  # email suppressed


def test_in_app_preference_disabled_blocks_in_app_not_email(client):
    headers = _register_and_login(client, "inapppref")
    client.put("/api/v1/notifications/preferences", headers=headers, json={"notify_job": False})
    _create_and_publish_job(client, title="InApp Pref Target Role", location="Noida")
    alert = _create_alert(client, headers, keywords="inapp pref target role")

    resp = client.post(f"/api/v1/job-alerts/{alert['id']}/run-now", headers=headers).json()
    assert resp["notifications_created"] == 0  # in-app suppressed
    assert resp["emails_queued"] == 1  # email unaffected


def test_both_preferences_disabled_still_matches_but_delivers_nothing(client):
    headers = _register_and_login(client, "bothpref")
    client.put("/api/v1/notifications/preferences", headers=headers, json={"email_job": False, "notify_job": False})
    _create_and_publish_job(client, title="Both Pref Target Role", location="Noida")
    alert = _create_alert(client, headers, keywords="both pref target role")

    resp = client.post(f"/api/v1/job-alerts/{alert['id']}/run-now", headers=headers).json()
    assert resp["jobs_matched"] == 1
    assert resp["notifications_created"] == 0
    assert resp["emails_queued"] == 0


# ---------------------------------------------------------------------------
# Disabled alert never runs; enabled-only scanning
# ---------------------------------------------------------------------------


def test_disabled_alert_not_picked_up_by_due_alerts(client):
    headers = _register_and_login(client, "disabledscan")
    alert = _create_alert(client, headers)
    client.post(f"/api/v1/job-alerts/{alert['id']}/disable", headers=headers)

    from app.db.session import SessionLocal
    from app.job_alerts.execution import due_alerts

    db = SessionLocal()
    try:
        due_ids = {a.id for a in due_alerts(db)}
        assert alert["id"] not in due_ids
    finally:
        db.close()


def test_frequency_window_gates_daily_weekly_due_selection(client):
    """A DAILY/WEEKLY alert that already ran recently isn't due again;
    an INSTANT alert always is (spec section 3)."""
    headers = _register_and_login(client, "duewindow")
    instant = _create_alert(client, headers, frequency="INSTANT")
    daily = _create_alert(client, headers, frequency="DAILY")

    from datetime import datetime

    from app.db.session import SessionLocal
    from app.job_alerts.execution import due_alerts
    from app.models.domain import JobAlert

    db = SessionLocal()
    try:
        row = db.get(JobAlert, daily["id"])
        row.last_run_at = datetime.utcnow()
        db.commit()

        due_ids = {a.id for a in due_alerts(db)}
        assert instant["id"] in due_ids
        assert daily["id"] not in due_ids  # ran moments ago, window not elapsed
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_run_alert_handles_missing_user_gracefully(client):
    """Simulates a failure mid-pipeline (spec section 28: "failure
    handling") — the run must be recorded as FAILED with a safe error
    summary, never raise out to the caller, and never crash a batch.
    Uses a real (FK-valid) but deactivated user, since job_alerts.user_id
    has an enforced FK to users.id (SQLite FK enforcement is on in this
    project) — a deactivated account is the realistic version of "this
    alert's owner can no longer receive alerts" that app.job_alerts.
    execution.run_alert explicitly checks for."""
    headers = _register_and_login(client, "deactivated")
    alert = _create_alert(client, headers)

    from app.db.session import SessionLocal
    from app.job_alerts.execution import run_alert
    from app.models.domain import JobAlert, User

    db = SessionLocal()
    try:
        alert_row = db.get(JobAlert, alert["id"])
        user_row = db.get(User, alert_row.user_id)
        user_row.active = False
        db.commit()

        db.refresh(alert_row)
        run = run_alert(db, alert_row)  # must not raise
        assert run.status == "FAILED"
        assert run.error_summary is not None
        # never a raw stack trace (spec section 19)
        assert "Traceback" not in run.error_summary

        refreshed = db.get(JobAlert, alert["id"])
        assert refreshed.last_run_status == "FAILED"
    finally:
        db.close()


def test_run_due_alerts_isolates_one_failing_alert_from_the_batch(client):
    good_headers = _register_and_login(client, "batchfail")
    good_job = _create_and_publish_job(client, title="Batch Isolation Target Role", location="Noida")
    good_alert = _create_alert(client, good_headers, keywords="batch isolation target role")

    broken_headers = _register_and_login(client, "batchfailbroken")

    from app.db.session import SessionLocal
    from app.job_alerts.execution import run_due_alerts
    from app.models.domain import JobAlert, User

    db = SessionLocal()
    try:
        broken_alert = _create_alert(client, broken_headers, name="Broken alert")
        broken_row = db.get(JobAlert, broken_alert["id"])
        broken_user = db.get(User, broken_row.user_id)
        broken_user.active = False  # deactivated owner -> run_alert raises mid-pipeline for this one alert
        db.commit()

        result = run_due_alerts(db)
        assert result["alerts_failed"] >= 1
        assert result["alerts_succeeded"] >= 1  # the good alert still ran despite the broken one

        good_row = db.get(JobAlert, good_alert["id"])
        assert good_row.last_run_status == "SUCCESS"
        broken_row_after = db.get(JobAlert, broken_alert["id"])
        assert broken_row_after.last_run_status == "FAILED"
    finally:
        db.close()
    assert good_job  # keep referenced


# ---------------------------------------------------------------------------
# Concurrency (best-effort, single-process simulation)
# ---------------------------------------------------------------------------


def test_concurrent_delivery_insert_does_not_duplicate(client):
    """Simulates two workers racing to record the same delivery — the
    UNIQUE(job_alert_id, job_id, channel) constraint (spec section 22)
    must let exactly one insert win."""
    headers = _register_and_login(client, "concurrent")
    job_id = _create_and_publish_job(client, title="Concurrency Target Role", location="Noida")
    alert = _create_alert(client, headers, keywords="concurrency target role")

    from app.db.session import SessionLocal
    from app.job_alerts.execution import _record_delivery
    from app.models.domain import JobAlert, JobAlertDelivery

    db1 = SessionLocal()
    db2 = SessionLocal()
    try:
        alert_row1 = db1.get(JobAlert, alert["id"])
        alert_row2 = db2.get(JobAlert, alert["id"])

        first = _record_delivery(db1, alert=alert_row1, job_id=job_id, channel="IN_APP", score=80)
        second = _record_delivery(db2, alert=alert_row2, job_id=job_id, channel="IN_APP", score=80)

        assert first is True
        assert second is False  # lost the race — same (alert, job, channel) already recorded

        db3 = SessionLocal()
        try:
            rows = db3.query(JobAlertDelivery).filter(
                JobAlertDelivery.job_alert_id == alert["id"], JobAlertDelivery.job_id == job_id
            ).all()
            assert len(rows) == 1
        finally:
            db3.close()
    finally:
        db1.close()
        db2.close()


# ---------------------------------------------------------------------------
# Regression — V16-V23.2 functionality untouched
# ---------------------------------------------------------------------------


def test_regression_existing_alerts_saved_search_unaffected(client):
    """The pre-existing V7/V19.4 `alerts` (alert_type='job') saved-
    search system must keep working exactly as before — see
    JobAlert's docstring for why V23.3 deliberately did not touch it."""
    headers = _register_and_login(client, "regressold")
    resp = client.post("/api/v1/subscriptions", headers=headers, json={"subscription_type": "organization", "value": "Acme"})
    assert resp.status_code in (200, 201), resp.text


def test_regression_search_still_works(client):
    resp = client.get("/api/v1/search?q=python")
    assert resp.status_code == 200


def test_regression_recommendations_endpoint_still_works(client):
    headers = _register_and_login(client, "regressrec")
    resp = client.get("/api/v1/recommendations", headers=headers)
    assert resp.status_code == 200


def test_regression_notifications_endpoint_still_works(client):
    headers = _register_and_login(client, "regressnotif")
    resp = client.get("/api/v1/notifications", headers=headers)
    assert resp.status_code == 200


def test_regression_email_queue_processing_still_works(client):
    from app.db.session import SessionLocal
    from app.email.service import process_queue

    db = SessionLocal()
    try:
        result = process_queue(db)
        assert "processed" in result
    finally:
        db.close()


# ---------------------------------------------------------------------------
# V23.5 — abuse protection on the expensive endpoints
# ---------------------------------------------------------------------------


def test_run_now_is_rate_limited(client):
    """spec V23.5 section 17: 'abuse of alert execution endpoints' — a
    confirmed gap (docs/V23_BUG_REPORT.md): POST .../run-now had no
    cost control at all before this fix."""
    headers = _register_and_login(client, "ratelimitrun")
    alert = _create_alert(client, headers)
    statuses = [client.post(f"/api/v1/job-alerts/{alert['id']}/run-now", headers=headers).status_code for _ in range(35)]
    assert 429 in statuses


def test_preview_is_rate_limited(client):
    headers = _register_and_login(client, "ratelimitpreview")
    statuses = [
        client.post("/api/v1/job-alerts/preview", headers=headers, json={"name": "x", "keywords": "python"}).status_code
        for _ in range(35)
    ]
    assert 429 in statuses
