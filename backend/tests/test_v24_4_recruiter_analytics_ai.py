"""V24.4 — Recruiter Analytics & AI Hiring Intelligence.

Deterministic endpoints are tested with NO provider mocking at all —
they must never touch the LLM. AI endpoints are tested with the
provider layer mocked at ``app.ai.completion_service.route_complete``
(the exact seam ``test_v22_4_ai_application_intelligence.py`` already
established) — no real, paid LLM calls happen in this suite.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v24_4.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.ai.provider_router import AllProvidersFailedError, RoutedResult  # noqa: E402
from app.ai.providers.base import CompletionResult  # noqa: E402
from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}
_counter = {"n": 0}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _register_recruiter(client, suffix=None):
    _counter["n"] += 1
    suffix = suffix or _counter["n"]
    email = f"v244rec{suffix}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Rec"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    rlogin = client.post("/api/v1/auth/recruiter/login", json={"email": email, "password": "password12345!"})
    return {"Authorization": f"Bearer {rlogin.json()['access_token']}"}


def _register_candidate(client, suffix=None, *, skills=""):
    _counter["n"] += 1
    suffix = suffix or _counter["n"]
    email = f"v244cand{suffix}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Cand"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()
    if skills:
        client.put("/api/v1/profile", headers=headers, json={"skills": skills})
    return headers, me["id"]


def _publish_job(client, r_headers, title="Backend Engineer", skills="Java, SQL"):
    job = client.post(
        "/api/v1/recruiter/jobs",
        headers=r_headers,
        json={"title": title, "organization": "Acme", "location": "Remote", "description": "x", "qualification": "x", "skills": [x.strip() for x in skills.split(",") if x.strip()]},
    ).json()
    client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)
    return job


def _apply_and_get_applicant_id(client, r_headers, job, c_headers):
    client.post(f"/api/v1/jobs/{job['id']}/apply", headers=c_headers, json={})
    applicants = client.get(f"/api/v1/recruiter/jobs/{job['id']}/applicants", headers=r_headers).json()
    return applicants[0]["id"]


def _move_stage(client, r_headers, applicant_id, stage):
    return client.patch(f"/api/v1/recruiter/applicants/{applicant_id}/stage", headers=r_headers, json={"pipeline_stage": stage})


# ---------------------------------------------------------------------------
# Deterministic endpoints — NO AI mocking
# ---------------------------------------------------------------------------


def test_overview_reflects_real_data_and_empty_recruiter_is_safe(client):
    empty_headers = _register_recruiter(client, "empty")
    empty_overview = client.get("/api/v1/recruiter/analytics/overview", headers=empty_headers).json()
    assert empty_overview["total_jobs"] == 0
    assert empty_overview["total_applications"] == 0
    assert empty_overview["stale_candidates"] == 0

    r_headers = _register_recruiter(client, "a")
    job = _publish_job(client, r_headers, "Job A")
    c_headers, _cid = _register_candidate(client, "a1")
    _apply_and_get_applicant_id(client, r_headers, job, c_headers)

    overview = client.get("/api/v1/recruiter/analytics/overview", headers=r_headers).json()
    assert overview["total_jobs"] == 1
    assert overview["total_applications"] == 1
    assert overview["new_applications"] == 1


def test_funnel_handles_zero_denominator(client):
    r_headers = _register_recruiter(client, "b")
    response = client.get("/api/v1/recruiter/analytics/pipeline", headers=r_headers)
    assert response.status_code == 200
    for step in response.json()["funnel"]["steps"]:
        if step["from_count"] == 0:
            assert step["conversion_rate"] is None


def test_time_in_stage_never_treats_incomplete_as_zero(client):
    r_headers = _register_recruiter(client, "c")
    job = _publish_job(client, r_headers, "Job C")
    c_headers, _cid = _register_candidate(client, "c1")
    applicant_id = _apply_and_get_applicant_id(client, r_headers, job, c_headers)
    # Never moved past "new" — has NOT reached "interview".
    result = client.get("/api/v1/recruiter/analytics/time-in-stage", headers=r_headers).json()
    assert result["sample_sizes"]["application_to_interview"] == 0
    assert result["average_time_application_to_interview_days"] is None  # not 0.0

    move = _move_stage(client, r_headers, applicant_id, "interview")
    assert move.status_code == 200
    result2 = client.get("/api/v1/recruiter/analytics/time-in-stage", headers=r_headers).json()
    assert result2["sample_sizes"]["application_to_interview"] == 1
    assert result2["average_time_application_to_interview_days"] is not None


def test_stale_candidates_threshold_is_configurable(client):
    r_headers = _register_recruiter(client, "d")
    job = _publish_job(client, r_headers, "Job D")
    c_headers, _cid = _register_candidate(client, "d1")
    _apply_and_get_applicant_id(client, r_headers, job, c_headers)

    strict = client.get("/api/v1/recruiter/analytics/stale-candidates?threshold_days=1", headers=r_headers).json()
    lenient = client.get("/api/v1/recruiter/analytics/stale-candidates?threshold_days=365", headers=r_headers).json()
    assert strict["threshold_days"] == 1
    assert len(strict["candidates"]) >= len(lenient["candidates"])


def test_job_analytics_and_candidate_match_distribution(client):
    r_headers = _register_recruiter(client, "e")
    job = _publish_job(client, r_headers, "Job E", skills="Java, SQL")
    c_headers, _cid = _register_candidate(client, "e1", skills="Java, SQL")
    _apply_and_get_applicant_id(client, r_headers, job, c_headers)

    job_stats = client.get(f"/api/v1/recruiter/analytics/jobs/{job['id']}", headers=r_headers).json()
    assert job_stats["applications"] == 1
    assert job_stats["job_views"] is None  # untracked, never fabricated

    matches = client.get(f"/api/v1/recruiter/analytics/jobs/{job['id']}/candidates", headers=r_headers).json()
    assert matches["candidates_scored"] == 1
    assert sum(matches["distribution"].values()) == 1


def test_analytics_endpoints_are_isolated_across_recruiters(client):
    r1_headers = _register_recruiter(client, "f1")
    r2_headers = _register_recruiter(client, "f2")
    job = _publish_job(client, r1_headers, "Job F1")
    c_headers, _cid = _register_candidate(client, "f1c")
    _apply_and_get_applicant_id(client, r1_headers, job, c_headers)

    r2_overview = client.get("/api/v1/recruiter/analytics/overview", headers=r2_headers).json()
    assert r2_overview["total_jobs"] == 0
    assert r2_overview["total_applications"] == 0

    forbidden = client.get(f"/api/v1/recruiter/analytics/jobs/{job['id']}", headers=r2_headers)
    assert forbidden.status_code == 404
    forbidden2 = client.get(f"/api/v1/recruiter/analytics/jobs/{job['id']}/candidates", headers=r2_headers)
    assert forbidden2.status_code == 404


# ---------------------------------------------------------------------------
# AI endpoints — provider mocked
# ---------------------------------------------------------------------------


def _mock_completion(monkeypatch, *, text: str = None, raise_all_failed: bool = False):
    import app.ai.completion_service as completion_service_module

    state = {"calls": 0}

    def fake_route_complete(messages, **kwargs):
        state["calls"] += 1
        if raise_all_failed:
            raise AllProvidersFailedError([])
        return (
            CompletionResult(text=text, provider="test-provider", model="test-model", prompt_tokens=10, completion_tokens=10),
            RoutedResult(attempts=1, latency_ms=1.0, used_fallback=False, provider_name="test-provider"),
        )

    monkeypatch.setattr(completion_service_module, "route_complete", fake_route_complete)
    return state


PIPELINE_SUMMARY_JSON = '{"summary": "Your pipeline has 1 job with candidates in the new stage.", "points": ["1 candidate is new and needs review."]}'
FLAGGED_JSON = '{"summary": "This candidate seems like a good gender fit for the team.", "points": ["Consider their marital status."]}'


def test_ai_pipeline_summary_generates_and_caches(client, monkeypatch):
    r_headers = _register_recruiter(client, "g")
    _publish_job(client, r_headers, "Job G")
    state = _mock_completion(monkeypatch, text=PIPELINE_SUMMARY_JSON)

    first = client.post("/api/v1/recruiter/analytics/ai/pipeline-summary", headers=r_headers, json={})
    assert first.status_code == 200
    body = first.json()
    assert body["ai"]["degraded"] is False
    assert body["from_cache"] is False
    assert state["calls"] == 1

    second = client.post("/api/v1/recruiter/analytics/ai/pipeline-summary", headers=r_headers, json={})
    assert second.json()["from_cache"] is True
    assert state["calls"] == 1  # cache hit — no second provider call


def test_ai_degrades_gracefully_on_provider_failure(client, monkeypatch):
    r_headers = _register_recruiter(client, "h")
    _mock_completion(monkeypatch, raise_all_failed=True)

    response = client.post("/api/v1/recruiter/analytics/ai/pipeline-summary", headers=r_headers, json={})
    assert response.status_code == 200  # dashboard must keep working
    assert response.json()["ai"]["degraded"] is True


def test_ai_fairness_guard_withholds_protected_attribute_language(client, monkeypatch):
    r_headers = _register_recruiter(client, "i")
    job = _publish_job(client, r_headers, "Job I", skills="Java")
    c1_headers, c1_id = _register_candidate(client, "i1", skills="Java")
    c2_headers, c2_id = _register_candidate(client, "i2", skills="Java, SQL")
    client.post(f"/api/v1/jobs/{job['id']}/apply", headers=c1_headers, json={})
    client.post(f"/api/v1/jobs/{job['id']}/apply", headers=c2_headers, json={})

    _mock_completion(monkeypatch, text=FLAGGED_JSON)
    response = client.post(
        "/api/v1/recruiter/analytics/ai/candidate-comparison",
        headers=r_headers,
        json={"job_id": job["id"], "candidate_ids": [c1_id, c2_id]},
    )
    assert response.status_code == 200
    ai = response.json()["ai"]
    assert ai["flagged"] is True
    assert "gender" not in ai["summary"].lower()
    assert "marital status" not in " ".join(ai["points"]).lower()


def test_ai_candidate_comparison_rejects_unauthorized_candidate(client, monkeypatch):
    r1_headers = _register_recruiter(client, "j1")
    r2_headers = _register_recruiter(client, "j2")
    job1 = _publish_job(client, r1_headers, "Job J1")
    c_headers, c_id = _register_candidate(client, "j1c")
    client.post(f"/api/v1/jobs/{job1['id']}/apply", headers=c_headers, json={})

    job2 = _publish_job(client, r2_headers, "Job J2")
    other_headers, other_id = _register_candidate(client, "j2c")
    client.post(f"/api/v1/jobs/{job2['id']}/apply", headers=other_headers, json={})

    _mock_completion(monkeypatch, text=PIPELINE_SUMMARY_JSON)
    # r2 tries to compare r1's private (non-opted-in) applicant against
    # their own candidate on r2's own job — must be rejected as
    # "not found", not silently scored.
    response = client.post(
        "/api/v1/recruiter/analytics/ai/candidate-comparison",
        headers=r2_headers,
        json={"job_id": job2["id"], "candidate_ids": [c_id, other_id]},
    )
    assert response.status_code == 404


def test_ai_job_insights_never_fabricates_untracked_metrics(client, monkeypatch):
    r_headers = _register_recruiter(client, "k")
    job = _publish_job(client, r_headers, "Job K")
    _mock_completion(monkeypatch, text=PIPELINE_SUMMARY_JSON)

    response = client.post(f"/api/v1/recruiter/analytics/ai/job-insights/{job['id']}", headers=r_headers, json={})
    assert response.status_code == 200
    facts = response.json()["facts"]
    assert facts["job_has_skills_listed"] is True
    assert "performance" in facts
    assert "job_views" not in facts["performance"] or facts["performance"].get("job_views") is None


def test_analytics_ai_requires_recruiter_role(client):
    c_headers, _cid = _register_candidate(client, "nonrecruiter")
    response = client.post("/api/v1/recruiter/analytics/ai/pipeline-summary", headers=c_headers, json={})
    assert response.status_code in (401, 403)
