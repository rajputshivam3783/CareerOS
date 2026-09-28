"""V22.4 — AI Application Intelligence & Follow-ups tests.

Deterministic logic (health/priority/next-action/follow-up-timing/
risks/action-plan) is tested with NO provider mocking at all — those
endpoints must never touch the LLM. Every AI-calling endpoint
(analyze/follow-up/interview-prep) is tested with the provider layer
mocked at ``app.ai.completion_service.route_complete`` (the exact
monkeypatch point ``test_v20_3_ai_career_copilot.py`` already
established) — no real, paid LLM calls happen in this suite.
"""

import os
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v22_4.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.ai.providers.base import CompletionResult  # noqa: E402
from app.ai.provider_router import AllProvidersFailedError, RoutedResult  # noqa: E402
from app.main import app  # noqa: E402

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


def _mock_completion(monkeypatch, *, text: str = None, raise_all_failed: bool = False):
    """Monkeypatches app.ai.completion_service.route_complete (the
    same seam test_v20_3_ai_career_copilot.py uses) and returns a
    dict with a 'calls' counter the test can inspect."""
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


NARRATIVE_JSON = '{"summary": "This application is progressing normally.", "encouragement_or_caution": "Keep it up.", "talking_points": ["Recent activity is good."]}'
FOLLOWUP_JSON = '{"subject": "Following up on my application", "body": "Dear Hiring Team,\\n\\nI wanted to follow up...\\n\\nBest,\\n[Your Name]"}'
INTERVIEW_PREP_JSON = (
    '{"topics_to_prepare": ["System design basics"], "likely_areas": ["Data structures"], '
    '"suggested_questions": ["Tell me about a challenging project."], "candidate_specific_prep": ["Review your resume projects."], '
    '"questions_to_ask_interviewer": ["What does success look like in this role?"]}'
)


# ---------------------------------------------------------------------------
# Deterministic engine — NO provider mocking. Must never call the LLM.
# ---------------------------------------------------------------------------


def test_overview_new_saved_application_is_low_priority_apply_now(client):
    headers = _register_and_login(client, "v22_4saved")
    a = _create_application(client, headers, status="SAVED")

    resp = client.get(f"/api/v1/applications/{a['id']}/ai/overview", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["priority"] == "Low"
    assert data["next_best_action"]["action"] == "Apply now"
    assert data["narrative"] is None  # nothing generated/cached yet


def test_overview_overdue_task_shows_in_signals_and_risks(client):
    headers = _register_and_login(client, "v22_4overdue")
    a = _create_application(client, headers, status="APPLIED")
    past_due = (datetime.utcnow() - timedelta(days=5)).isoformat()
    client.post(f"/api/v1/applications/{a['id']}/tasks", headers=headers, json={"title": "Send documents", "due_at": past_due})

    resp = client.get(f"/api/v1/applications/{a['id']}/ai/overview", headers=headers)
    data = resp.json()
    assert data["signals"]["overdue_task_count"] == 1
    assert any(r["risk"] == "Overdue task(s)" for r in data["risks"])
    assert any("overdue" in reason.lower() for reason in data["health"]["reasons"])


def test_overview_upcoming_interview_raises_priority(client):
    headers = _register_and_login(client, "v22_4interview")
    a = _create_application(client, headers, status="INTERVIEW")
    soon = (datetime.utcnow() + timedelta(hours=6)).isoformat()
    client.post(f"/api/v1/applications/{a['id']}/interviews", headers=headers, json={"interview_type": "technical", "scheduled_at": soon})

    resp = client.get(f"/api/v1/applications/{a['id']}/ai/overview", headers=headers)
    data = resp.json()
    assert data["priority"] in ("High", "Critical")
    assert data["next_best_action"]["action"] == "Prepare for interview"
    assert data["signals"]["has_upcoming_interview"] is True


def test_overview_deadline_approaching_is_a_risk(client):
    headers = _register_and_login(client, "v22_4deadline")
    soon_deadline = (datetime.utcnow() + timedelta(days=2)).date().isoformat()
    a = _create_application(client, headers, status="APPLIED", deadline=soon_deadline)

    resp = client.get(f"/api/v1/applications/{a['id']}/ai/overview", headers=headers)
    data = resp.json()
    assert any(r["risk"] == "Deadline approaching" for r in data["risks"])


def test_accepted_application_is_healthy_no_action_needed(client):
    headers = _register_and_login(client, "v22_4accepted")
    a = _create_application(client, headers, status="ACCEPTED")

    resp = client.get(f"/api/v1/applications/{a['id']}/ai/overview", headers=headers)
    data = resp.json()
    assert data["health"]["label"] == "Healthy"
    assert data["next_best_action"]["action"] == "No action required"
    assert data["priority"] == "Low"


def test_action_plan_and_risks_endpoints_never_call_the_llm(client, monkeypatch):
    """No monkeypatch on route_complete here at all — if either
    endpoint tried to call the LLM, it would attempt a real network
    call (no provider is configured in this test env) and fail/hang
    rather than returning cleanly."""
    headers = _register_and_login(client, "v22_4detplan")
    a = _create_application(client, headers, status="SAVED")

    plan_resp = client.post(f"/api/v1/applications/{a['id']}/ai/action-plan", headers=headers)
    assert plan_resp.status_code == 200
    assert isinstance(plan_resp.json()["action_plan"], list)

    risks_resp = client.post(f"/api/v1/applications/{a['id']}/ai/risks", headers=headers)
    assert risks_resp.status_code == 200
    assert isinstance(risks_resp.json()["risks"], list)


# ---------------------------------------------------------------------------
# AI narrative (POST /analyze) — provider mocked
# ---------------------------------------------------------------------------


def test_analyze_generates_and_caches_narrative(client, monkeypatch):
    headers = _register_and_login(client, "v22_4analyze")
    a = _create_application(client, headers, status="APPLIED")
    state = _mock_completion(monkeypatch, text=NARRATIVE_JSON)

    first = client.post(f"/api/v1/applications/{a['id']}/ai/analyze", headers=headers, json={})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["narrative"]["degraded"] is False
    assert body["narrative"]["summary"] == "This application is progressing normally."
    assert body["from_cache"] is False
    assert state["calls"] == 1

    second = client.post(f"/api/v1/applications/{a['id']}/ai/analyze", headers=headers, json={})
    assert second.status_code == 200
    assert second.json()["from_cache"] is True
    assert state["calls"] == 1  # no second provider call — served from cache

    overview = client.get(f"/api/v1/applications/{a['id']}/ai/overview", headers=headers).json()
    assert overview["narrative"]["summary"] == "This application is progressing normally."
    assert overview["narrative_generated_at"] is not None


def test_analyze_cache_invalidates_when_status_changes(client, monkeypatch):
    headers = _register_and_login(client, "v22_4cachebust")
    a = _create_application(client, headers, status="APPLIED")
    state = _mock_completion(monkeypatch, text=NARRATIVE_JSON)

    client.post(f"/api/v1/applications/{a['id']}/ai/analyze", headers=headers, json={})
    assert state["calls"] == 1

    client.post(f"/api/v1/applications/{a['id']}/status", headers=headers, json={"status": "INTERVIEW"})

    overview = client.get(f"/api/v1/applications/{a['id']}/ai/overview", headers=headers).json()
    # Different status -> different fingerprint/context_key -> no cache hit for the new state
    assert overview["narrative"] is None


def test_analyze_degrades_on_provider_failure(client, monkeypatch):
    headers = _register_and_login(client, "v22_4failure")
    a = _create_application(client, headers, status="APPLIED")
    _mock_completion(monkeypatch, raise_all_failed=True)

    resp = client.post(f"/api/v1/applications/{a['id']}/ai/analyze", headers=headers, json={})
    assert resp.status_code == 200  # never a 500 — the workspace must keep working
    body = resp.json()
    assert body["narrative"]["degraded"] is True
    assert "unavailable" in body["narrative"]["summary"].lower()
    # deterministic signals are still present even though AI failed
    assert body["priority"] in ("Low", "Medium", "High", "Critical")


def test_analyze_degrades_on_malformed_response(client, monkeypatch):
    headers = _register_and_login(client, "v22_4malformed")
    a = _create_application(client, headers, status="APPLIED")
    _mock_completion(monkeypatch, text="this is not json at all")

    resp = client.post(f"/api/v1/applications/{a['id']}/ai/analyze", headers=headers, json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["narrative"]["degraded"] is True
    assert "parsed" in body["narrative"]["summary"].lower()


# ---------------------------------------------------------------------------
# AI follow-up (POST /follow-up) — provider mocked
# ---------------------------------------------------------------------------


def test_follow_up_generates_subject_and_body(client, monkeypatch):
    headers = _register_and_login(client, "v22_4followup")
    a = _create_application(client, headers, status="INTERVIEW")
    _mock_completion(monkeypatch, text=FOLLOWUP_JSON)

    resp = client.post(f"/api/v1/applications/{a['id']}/ai/follow-up", headers=headers, json={"tone": "friendly"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["subject"]
    assert body["body"]
    assert body["tone"] == "FRIENDLY"
    assert body["degraded"] is False


def test_follow_up_invalid_tone_defaults_to_professional(client, monkeypatch):
    headers = _register_and_login(client, "v22_4tonedef")
    a = _create_application(client, headers, status="APPLIED")
    _mock_completion(monkeypatch, text=FOLLOWUP_JSON)

    resp = client.post(f"/api/v1/applications/{a['id']}/ai/follow-up", headers=headers, json={"tone": "sarcastic"})
    assert resp.status_code == 200
    assert resp.json()["tone"] == "PROFESSIONAL"


def test_follow_up_never_sends_anything(client, monkeypatch):
    """There is no email-sending code path at all — this test just
    documents that the response is a draft, not a send confirmation."""
    headers = _register_and_login(client, "v22_4nosend")
    a = _create_application(client, headers, status="APPLIED")
    _mock_completion(monkeypatch, text=FOLLOWUP_JSON)

    resp = client.post(f"/api/v1/applications/{a['id']}/ai/follow-up", headers=headers, json={})
    body = resp.json()
    assert "sent" not in body
    assert "email_id" not in body


# ---------------------------------------------------------------------------
# AI interview prep (POST /interview-prep) — provider mocked
# ---------------------------------------------------------------------------


def test_interview_prep_requires_an_interview(client):
    headers = _register_and_login(client, "v22_4noiv")
    a = _create_application(client, headers, status="APPLIED")

    resp = client.post(f"/api/v1/applications/{a['id']}/ai/interview-prep", headers=headers, json={})
    assert resp.status_code == 400


def test_interview_prep_generates_labeled_suggestions(client, monkeypatch):
    headers = _register_and_login(client, "v22_4ivprep")
    a = _create_application(client, headers, status="INTERVIEW")
    iv = client.post(f"/api/v1/applications/{a['id']}/interviews", headers=headers, json={"interview_type": "technical"}).json()
    _mock_completion(monkeypatch, text=INTERVIEW_PREP_JSON)

    resp = client.post(f"/api/v1/applications/{a['id']}/ai/interview-prep", headers=headers, json={"interview_id": iv["id"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["topics_to_prepare"]
    assert "not guaranteed" in body["note"].lower() or "suggestions" in body["note"].lower()
    assert body["interview_id"] == iv["id"]


def test_interview_prep_rejects_foreign_interview_id(client, monkeypatch):
    headers_a = _register_and_login(client, "v22_4ivowner_a")
    headers_b = _register_and_login(client, "v22_4ivowner_b")
    a = _create_application(client, headers_a, status="INTERVIEW")
    iv = client.post(f"/api/v1/applications/{a['id']}/interviews", headers=headers_a, json={"interview_type": "hr"}).json()
    b = _create_application(client, headers_b, status="INTERVIEW")
    _mock_completion(monkeypatch, text=INTERVIEW_PREP_JSON)

    resp = client.post(f"/api/v1/applications/{b['id']}/ai/interview-prep", headers=headers_b, json={"interview_id": iv["id"]})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Ownership isolation (IDOR)
# ---------------------------------------------------------------------------


def test_ai_endpoints_are_isolated_across_users(client, monkeypatch):
    headers_a = _register_and_login(client, "v22_4aiowner_a")
    headers_b = _register_and_login(client, "v22_4aiowner_b")
    a = _create_application(client, headers_a, status="APPLIED")
    _mock_completion(monkeypatch, text=NARRATIVE_JSON)

    assert client.get(f"/api/v1/applications/{a['id']}/ai/overview", headers=headers_b).status_code == 404
    assert client.post(f"/api/v1/applications/{a['id']}/ai/analyze", headers=headers_b, json={}).status_code == 404
    assert client.post(f"/api/v1/applications/{a['id']}/ai/follow-up", headers=headers_b, json={}).status_code == 404
    assert client.post(f"/api/v1/applications/{a['id']}/ai/interview-prep", headers=headers_b, json={}).status_code == 404
    assert client.post(f"/api/v1/applications/{a['id']}/ai/action-plan", headers=headers_b).status_code == 404
    assert client.post(f"/api/v1/applications/{a['id']}/ai/risks", headers=headers_b).status_code == 404


# ---------------------------------------------------------------------------
# Cost control — rate limiting
# ---------------------------------------------------------------------------


def test_ai_generate_endpoints_are_rate_limited(client, monkeypatch):
    """The 'application-ai-generate' bucket is shared (keyed by client
    IP) across every test in this module, so this doesn't assert an
    exact call count — it asserts that sustained calls eventually get
    a 429 rather than an unbounded number of (mocked) provider calls."""
    headers = _register_and_login(client, "v22_4ratelimit")
    a = _create_application(client, headers, status="APPLIED")
    _mock_completion(monkeypatch, text=FOLLOWUP_JSON)

    statuses = []
    for _ in range(30):
        resp = client.post(f"/api/v1/applications/{a['id']}/ai/follow-up", headers=headers, json={"force": True})
        statuses.append(resp.status_code)
        if 429 in statuses:
            break

    assert 429 in statuses
