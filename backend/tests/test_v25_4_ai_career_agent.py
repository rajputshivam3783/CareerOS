"""V25.4 — Advanced AI Career Agent & Automation tests.

Deterministic logic (state machine, tool registry validation,
permission denylist, action lifecycle idempotency, intent JSON
parsing) is tested with NO provider mocking at all — none of it
touches the LLM. Every chat-endpoint test that ends in an AI-narrated
reply mocks the provider layer at
``app.ai.completion_service.route_complete`` — the exact monkeypatch
point ``test_v20_3_ai_career_copilot.py``/``test_v22_4_...py`` already
established — so no real, paid LLM call happens in this suite.

Sections mirror the spec's own testing list (section 36):
Agent / Tools / Security / AI.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v25_4.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.ai.provider_router import AllProvidersFailedError, RoutedResult  # noqa: E402
from app.ai.providers.base import CompletionResult  # noqa: E402
from app.career_agent import (  # noqa: E402
    intent,
    permissions,
    state_machine,
    tool_registry,
)
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
    payload = {"company": "Acme", "job_title": "Backend Engineer", "status": "APPLIED"}
    payload.update(overrides)
    resp = client.post("/api/v1/applications", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _mock_completion(monkeypatch, *, text: str = "This is a test reply.", raise_all_failed: bool = False):
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


def _start_conversation(client, headers) -> int:
    resp = client.post("/api/v1/career-agent/conversations", headers=headers, json={})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# AGENT — state machine
# ---------------------------------------------------------------------------


class TestStateMachine:
    def test_read_path_is_legal(self):
        state_machine.assert_transition(state_machine.AgentState.IDLE, state_machine.AgentState.UNDERSTANDING)
        state_machine.assert_transition(state_machine.AgentState.UNDERSTANDING, state_machine.AgentState.PLANNING)
        state_machine.assert_transition(state_machine.AgentState.PLANNING, state_machine.AgentState.EXECUTING)
        state_machine.assert_transition(state_machine.AgentState.EXECUTING, state_machine.AgentState.COMPLETED)

    def test_write_path_requires_confirmation_state(self):
        state_machine.assert_transition(state_machine.AgentState.PLANNING, state_machine.AgentState.WAITING_FOR_CONFIRMATION)
        state_machine.assert_transition(state_machine.AgentState.WAITING_FOR_CONFIRMATION, state_machine.AgentState.EXECUTING)

    def test_cannot_skip_confirmation_straight_to_completed(self):
        with pytest.raises(state_machine.IllegalTransitionError):
            state_machine.assert_transition(state_machine.AgentState.WAITING_FOR_CONFIRMATION, state_machine.AgentState.COMPLETED)

    def test_cannot_jump_understanding_to_executing(self):
        with pytest.raises(state_machine.IllegalTransitionError):
            state_machine.assert_transition(state_machine.AgentState.UNDERSTANDING, state_machine.AgentState.EXECUTING)

    def test_terminal_states_have_no_outgoing_transitions(self):
        with pytest.raises(state_machine.IllegalTransitionError):
            state_machine.assert_transition(state_machine.AgentState.COMPLETED, state_machine.AgentState.EXECUTING)
        with pytest.raises(state_machine.IllegalTransitionError):
            state_machine.assert_transition(state_machine.AgentState.FAILED, state_machine.AgentState.EXECUTING)

    def test_risk_level_next_state_mapping(self):
        assert state_machine.NEXT_STATE_AFTER_PLANNING["READ"] == state_machine.AgentState.EXECUTING
        assert state_machine.NEXT_STATE_AFTER_PLANNING["WRITE"] == state_machine.AgentState.WAITING_FOR_CONFIRMATION
        assert state_machine.NEXT_STATE_AFTER_PLANNING["HIGH_RISK"] == state_machine.AgentState.WAITING_FOR_CONFIRMATION


# ---------------------------------------------------------------------------
# TOOLS — registry validation (LLM -> validated tool call, never LLM -> SQL)
# ---------------------------------------------------------------------------


class TestToolRegistry:
    def test_unknown_tool_rejected(self):
        with pytest.raises(tool_registry.ToolValidationError):
            tool_registry.validate_call("drop_all_tables", {})

    def test_unexpected_parameter_rejected(self):
        with pytest.raises(tool_registry.ToolValidationError):
            tool_registry.validate_call("get_saved_jobs", {"raw_sql": "SELECT * FROM users"})

    def test_missing_required_parameter_rejected(self):
        with pytest.raises(tool_registry.ToolValidationError):
            tool_registry.validate_call("get_job_details", {})

    def test_valid_call_is_type_coerced(self):
        cleaned = tool_registry.validate_call("get_job_details", {"job_id": "42"})
        assert cleaned == {"job_id": 42}

    def test_list_param_accepts_single_value(self):
        cleaned = tool_registry.validate_call("search_jobs", {"skills": "python"})
        assert cleaned["skills"] == ["python"]

    def test_every_registered_tool_has_a_callable_handler(self):
        for spec in tool_registry.TOOLS.values():
            assert callable(spec.handler)
            assert spec.risk in {"READ", "WRITE", "HIGH_RISK"}


# ---------------------------------------------------------------------------
# SECURITY — no recruiter/admin tool ever reaches the candidate registry
# ---------------------------------------------------------------------------


class TestToolPermissions:
    def test_no_recruiter_admin_tools_in_registry(self):
        for name in tool_registry.TOOLS:
            permissions.assert_candidate_safe_tool_name(name)  # raises if forbidden

    def test_forbidden_keyword_is_actually_caught(self):
        with pytest.raises(PermissionError):
            permissions.assert_candidate_safe_tool_name("recruiter_view_pipeline")

    def test_require_candidate_rejects_none_user(self):
        with pytest.raises(permissions.ToolPermissionError):
            permissions.require_candidate(None)


# ---------------------------------------------------------------------------
# AI — intent JSON parsing never executes an unvalidated tool call
# ---------------------------------------------------------------------------


class TestIntentParsing:
    def test_valid_json_with_known_tool(self):
        detected = intent._parse_and_validate('{"tool": "get_saved_jobs", "params": {}, "clarify": null}')
        assert detected.tool_name == "get_saved_jobs"

    def test_malformed_json_degrades_to_clarify_never_crashes(self):
        detected = intent._parse_and_validate("not json at all {{{")
        assert detected.tool_name is None
        assert detected.clarify

    def test_unknown_tool_name_never_passed_through(self):
        detected = intent._parse_and_validate('{"tool": "drop_database", "params": {}, "clarify": null}')
        assert detected.tool_name is None  # never the unwhitelisted name
        assert detected.clarify

    def test_missing_required_param_degrades_to_clarify(self):
        detected = intent._parse_and_validate('{"tool": "get_job_details", "params": {}, "clarify": null}')
        assert detected.tool_name is None
        assert detected.clarify

    def test_fast_path_matches_without_any_ai_call(self):
        detected = intent.fast_path("What jobs match my current skills? show job recommendations")
        assert detected is not None
        assert detected.tool_name == "get_job_recommendations"

    def test_fast_path_returns_none_for_unrecognized_free_text(self):
        assert intent.fast_path("tell me a joke about backend engineers") is None


# ---------------------------------------------------------------------------
# AGENT — chat endpoint, READ tool (fast-path intent, AI narration mocked)
# ---------------------------------------------------------------------------


class TestChatReadFlow:
    def test_read_tool_executes_immediately_and_is_completed(self, client, monkeypatch):
        headers = _register_and_login(client, "agentread")
        state = _mock_completion(monkeypatch, text="You have no saved jobs yet.")
        conversation_id = _start_conversation(client, headers)

        resp = client.post(
            f"/api/v1/career-agent/conversations/{conversation_id}/messages",
            headers=headers,
            json={"message": "show me my saved jobs"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["state"] == "COMPLETED"
        assert body["action"]["action_type"] == "get_saved_jobs"
        assert body["action"]["status"] == "COMPLETED"
        assert state["calls"] == 1  # exactly one AI call (narration) — fast path skipped intent AI call

    def test_general_question_with_no_tool_still_grounded(self, client, monkeypatch):
        headers = _register_and_login(client, "agentgeneral")
        # First AI call is intent detection (must be JSON); since no tool
        # applies here the model reports tool=null/clarify=null, so the
        # second AI call narrates a grounded general answer using the same
        # mocked text (a real provider would answer prose the second time).
        state = _mock_completion(monkeypatch, text='{"tool": null, "params": {}, "clarify": null}')
        conversation_id = _start_conversation(client, headers)

        resp = client.post(
            f"/api/v1/career-agent/conversations/{conversation_id}/messages",
            headers=headers,
            json={"message": "any general advice for someone starting their career?"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["state"] == "COMPLETED"
        assert resp.json()["action"] is None
        assert state["calls"] == 2  # one intent-detection call + one narration call


# ---------------------------------------------------------------------------
# AGENT — WRITE/HIGH_RISK confirmation flow (no AI call needed — deterministic template)
# ---------------------------------------------------------------------------


class TestConfirmationFlow:
    def test_write_tool_requires_confirmation_before_executing(self, client, monkeypatch):
        headers = _register_and_login(client, "agentwrite")
        application = _create_application(client, headers)
        conversation_id = _start_conversation(client, headers)

        # Bypass NLU for this test — the intent layer itself is covered by
        # TestIntentParsing above; this isolates the confirmation pipeline.
        import app.career_agent.intent as intent_module

        monkeypatch.setattr(
            intent_module,
            "detect",
            lambda db, user, message: intent_module.DetectedIntent(
                tool_name="schedule_follow_up",
                params={"application_id": application["id"], "follow_up_in_days": 5},
            ),
        )

        resp = client.post(
            f"/api/v1/career-agent/conversations/{conversation_id}/messages",
            headers=headers,
            json={"message": "remind me to follow up with this application in 5 days"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["state"] == "WAITING_FOR_CONFIRMATION"
        action_id = body["action"]["id"]
        assert body["action"]["status"] == "PENDING_CONFIRMATION"

        # Nothing executed yet — no task exists.
        tasks_resp = client.get(f"/api/v1/applications/{application['id']}/tasks", headers=headers)
        if tasks_resp.status_code == 200:
            assert tasks_resp.json() == [] or all("Follow up" not in t.get("title", "") for t in tasks_resp.json())

        pending = client.get("/api/v1/career-agent/pending-actions", headers=headers)
        assert pending.status_code == 200
        assert any(a["id"] == action_id for a in pending.json()["pending_actions"])

        confirm = client.post(f"/api/v1/career-agent/actions/{action_id}/confirm", headers=headers)
        assert confirm.status_code == 200, confirm.text
        assert confirm.json()["status"] == "COMPLETED"
        assert confirm.json()["result"]["title"].startswith("Follow up")

        # Idempotent: re-confirming the same action never re-executes it.
        confirm_again = client.post(f"/api/v1/career-agent/actions/{action_id}/confirm", headers=headers)
        assert confirm_again.status_code == 409

    def test_reject_prevents_execution(self, client, monkeypatch):
        headers = _register_and_login(client, "agentreject")
        application = _create_application(client, headers)
        conversation_id = _start_conversation(client, headers)

        import app.career_agent.intent as intent_module

        monkeypatch.setattr(
            intent_module,
            "detect",
            lambda db, user, message: intent_module.DetectedIntent(
                tool_name="create_application_task",
                params={"application_id": application["id"], "title": "Prep portfolio"},
            ),
        )

        resp = client.post(
            f"/api/v1/career-agent/conversations/{conversation_id}/messages",
            headers=headers, json={"message": "add a task to prep my portfolio"},
        )
        action_id = resp.json()["action"]["id"]

        reject = client.post(f"/api/v1/career-agent/actions/{action_id}/reject", headers=headers)
        assert reject.status_code == 200
        assert reject.json()["status"] == "REJECTED"

        confirm_after_reject = client.post(f"/api/v1/career-agent/actions/{action_id}/confirm", headers=headers)
        assert confirm_after_reject.status_code == 409

    def test_high_risk_submit_application_never_claims_success(self, client, monkeypatch):
        headers = _register_and_login(client, "agenthighrisk")
        conversation_id = _start_conversation(client, headers)

        import app.career_agent.intent as intent_module

        monkeypatch.setattr(
            intent_module, "detect",
            lambda db, user, message: intent_module.DetectedIntent(tool_name="submit_application", params={"job_id": 999999}),
        )

        resp = client.post(
            f"/api/v1/career-agent/conversations/{conversation_id}/messages",
            headers=headers, json={"message": "submit my application to this job"},
        )
        action_id = resp.json()["action"]["id"]

        confirm = client.post(f"/api/v1/career-agent/actions/{action_id}/confirm", headers=headers)
        assert confirm.status_code == 200
        # Nonexistent job -> tool raises ToolInputError -> action FAILED, never a fabricated success.
        assert confirm.json()["status"] in {"FAILED"}


# ---------------------------------------------------------------------------
# SECURITY — cross-user isolation (spec section 34)
# ---------------------------------------------------------------------------


class TestCrossUserIsolation:
    def test_cannot_read_another_users_conversation(self, client):
        headers_a = _register_and_login(client, "isoa")
        headers_b = _register_and_login(client, "isob")
        conversation_id = _start_conversation(client, headers_a)

        resp = client.get(f"/api/v1/career-agent/conversations/{conversation_id}", headers=headers_b)
        assert resp.status_code == 404

    def test_cannot_confirm_another_users_action(self, client, monkeypatch):
        headers_a = _register_and_login(client, "isoactiona")
        headers_b = _register_and_login(client, "isoactionb")
        application = _create_application(client, headers_a)
        conversation_id = _start_conversation(client, headers_a)

        import app.career_agent.intent as intent_module

        monkeypatch.setattr(
            intent_module, "detect",
            lambda db, user, message: intent_module.DetectedIntent(
                tool_name="schedule_follow_up", params={"application_id": application["id"]}
            ),
        )
        resp = client.post(
            f"/api/v1/career-agent/conversations/{conversation_id}/messages",
            headers=headers_a, json={"message": "follow up in 3 days"},
        )
        action_id = resp.json()["action"]["id"]

        forged = client.post(f"/api/v1/career-agent/actions/{action_id}/confirm", headers=headers_b)
        assert forged.status_code == 404

    def test_cannot_list_conversations_across_users(self, client):
        headers_a = _register_and_login(client, "isolista")
        headers_b = _register_and_login(client, "isolistb")
        _start_conversation(client, headers_a)

        resp_b = client.get("/api/v1/career-agent/conversations", headers=headers_b)
        assert resp_b.status_code == 200
        assert resp_b.json()["conversations"] == []

    def test_no_recruiter_or_admin_tool_reachable_via_registry_endpoint(self, client):
        headers = _register_and_login(client, "isotools")
        resp = client.get("/api/v1/career-agent/tools", headers=headers)
        assert resp.status_code == 200
        names = [t["name"] for t in resp.json()["tools"]]
        for name in names:
            assert "recruiter" not in name and "admin" not in name


# ---------------------------------------------------------------------------
# AGENT — conversation history CRUD (spec section 15)
# ---------------------------------------------------------------------------


class TestConversationHistory:
    def test_full_lifecycle_rename_archive_delete(self, client, monkeypatch):
        headers = _register_and_login(client, "history")
        _mock_completion(monkeypatch)
        conversation_id = _start_conversation(client, headers)

        rename = client.patch(
            f"/api/v1/career-agent/conversations/{conversation_id}", headers=headers, json={"title": "Backend job hunt"}
        )
        assert rename.status_code == 200
        assert rename.json()["title"] == "Backend job hunt"

        archive = client.post(f"/api/v1/career-agent/conversations/{conversation_id}/archive", headers=headers)
        assert archive.status_code == 200
        assert archive.json()["status"] == "archived"

        active_only = client.get("/api/v1/career-agent/conversations", headers=headers)
        assert conversation_id not in [c["id"] for c in active_only.json()["conversations"]]

        delete = client.delete(f"/api/v1/career-agent/conversations/{conversation_id}", headers=headers)
        assert delete.status_code == 204

        gone = client.get(f"/api/v1/career-agent/conversations/{conversation_id}", headers=headers)
        assert gone.status_code == 404


# ---------------------------------------------------------------------------
# AI — provider failure never surfaces as a raw 500
# ---------------------------------------------------------------------------


class TestAIFailureFallback:
    def test_all_providers_failing_returns_graceful_message_not_500(self, client, monkeypatch):
        headers = _register_and_login(client, "aifail")
        _mock_completion(monkeypatch, raise_all_failed=True)
        conversation_id = _start_conversation(client, headers)

        resp = client.post(
            f"/api/v1/career-agent/conversations/{conversation_id}/messages",
            headers=headers, json={"message": "give me general career advice please"},
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "COMPLETED"
        assert "unavailable" in resp.json()["reply"].lower()


# ---------------------------------------------------------------------------
# AGENT — preferences (spec section 21)
# ---------------------------------------------------------------------------


class TestPreferences:
    def test_defaults_then_update(self, client):
        headers = _register_and_login(client, "prefs")
        defaults = client.get("/api/v1/career-agent/preferences", headers=headers)
        assert defaults.status_code == 200
        assert defaults.json()["proactive_enabled"] is True

        updated = client.patch(
            "/api/v1/career-agent/preferences", headers=headers,
            json={"proactive_enabled": False, "frequency": "weekly", "quiet_hours_start": 22, "quiet_hours_end": 7},
        )
        assert updated.status_code == 200
        assert updated.json()["proactive_enabled"] is False
        assert updated.json()["frequency"] == "weekly"

    def test_invalid_frequency_rejected(self, client):
        headers = _register_and_login(client, "prefsbad")
        resp = client.patch("/api/v1/career-agent/preferences", headers=headers, json={"frequency": "hourly"})
        assert resp.status_code == 422 or resp.status_code == 400


# ---------------------------------------------------------------------------
# REGRESSION — V22 applications API untouched by this addition
# ---------------------------------------------------------------------------


class TestRegression:
    def test_applications_api_still_works(self, client):
        headers = _register_and_login(client, "regression")
        application = _create_application(client, headers)
        resp = client.get(f"/api/v1/applications/{application['id']}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["company"] == "Acme"
