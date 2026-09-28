"""V20.1 — AI Infrastructure & LLM Framework tests.

Covers the provider abstraction (registry, routing, fallback, stub
providers), the prompt registry (seeding, versioning, validation),
conversation memory (creation, history, summarization trigger),
observability (usage logging, live health), and the /ai/* API surface
(health, providers, conversations, prompts, usage, config) — all
admin-auth paths use a promoted admin User's Bearer token rather than
X-Admin-Key, the same way test_v17_3_rbac.py does, specifically to
stay off the shared "admin-key" rate-limit bucket (10 calls/60s) since
this file makes many more than 10 admin calls.

No provider API key is configured anywhere in this file, so every
completion/embedding/moderation call exercises the "not configured"
path deterministically and never makes a real network call — is_configured()
is checked before any HTTP request is attempted (see provider_router.py).

Follows the same self-contained (own sqlite file) pattern as every
other version's test file.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v20_1.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.ai import context_builder, prompt_service, token_counter  # noqa: E402
from app.ai.provider_router import AllProvidersFailedError, PROVIDERS, complete as route_complete, provider_status  # noqa: E402
from app.ai.providers.base import ChatMessage, LLMProvider, ProviderError  # noqa: E402
from app.main import app  # noqa: E402


def _set_role(email, role):
    """Test-only helper: promote a user directly via the DB, mirroring
    test_v17_3_rbac.py's own helper, so admin calls in this file
    authenticate via Bearer JWT (app.api.admin.guard's role path) and
    never touch the shared X-Admin-Key rate-limit bucket."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.domain import User

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        user.role = role
        db.commit()
    finally:
        db.close()


def _register_and_login(client, email, name):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": name},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def seeded():
    with TestClient(app) as client:
        candidate = _register_and_login(client, "v201-candidate@example.com", "V201 Candidate")

        admin_email = "v201-admin@example.com"
        admin_headers = _register_and_login(client, admin_email, "V201 Admin")
        _set_role(admin_email, "admin")

        yield {"client": client, "candidate": candidate, "admin": admin_headers}


# --- Provider abstraction ----------------------------------------------------


def test_provider_registry_has_all_documented_providers():
    assert set(PROVIDERS) == {"anthropic", "openai", "gemini", "openrouter", "local", "ollama", "azure_openai"}


def test_future_providers_are_registered_as_unconfigured_stubs():
    for name in ("local", "ollama", "azure_openai"):
        provider = PROVIDERS[name]
        assert provider.is_configured() is False
        with pytest.raises(ProviderError):
            provider.complete([ChatMessage(role="user", content="hi")], model="x", temperature=0, max_tokens=10, timeout_seconds=5)


def test_no_provider_configured_in_test_env():
    # This test file never sets any AI_*_API_KEY, so every real
    # provider should report unconfigured — confirms the "works with
    # zero keys, just returns clear errors" posture actually holds.
    for name in ("anthropic", "openai", "gemini", "openrouter"):
        assert PROVIDERS[name].is_configured() is False


def test_complete_raises_all_providers_failed_without_any_key():
    with pytest.raises(AllProvidersFailedError) as exc_info:
        route_complete([ChatMessage(role="user", content="hi")])
    assert len(exc_info.value.errors) >= 1


def test_provider_status_shape():
    statuses = provider_status()
    names = {s["name"] for s in statuses}
    assert names == set(PROVIDERS)
    anthropic_status = next(s for s in statuses if s["name"] == "anthropic")
    assert anthropic_status["configured"] is False
    assert "complete" in anthropic_status["capabilities"]


def test_fallback_is_attempted_when_primary_fails(monkeypatch):
    """Unit-level check of the router's fallback policy using two fake
    in-memory providers, so this doesn't depend on any real vendor
    credentials: primary always fails, fallback always succeeds, and
    the router should return the fallback's result with
    used_fallback=True."""
    from app.ai import provider_router as pr

    class _FailingProvider(LLMProvider):
        name = "fake-primary"

        def is_configured(self):
            return True

        def complete(self, messages, *, model, temperature, max_tokens, timeout_seconds):
            raise ProviderError(self.name, "simulated outage")

    class _WorkingProvider(LLMProvider):
        name = "fake-fallback"

        def is_configured(self):
            return True

        def complete(self, messages, *, model, temperature, max_tokens, timeout_seconds):
            from app.ai.providers.base import CompletionResult

            return CompletionResult(text="ok", provider=self.name, model=model, prompt_tokens=5, completion_tokens=2)

    monkeypatch.setitem(pr.PROVIDERS, "fake-primary", _FailingProvider())
    monkeypatch.setitem(pr.PROVIDERS, "fake-fallback", _WorkingProvider())
    monkeypatch.setattr(pr.settings, "ai_default_provider", "fake-primary")
    monkeypatch.setattr(pr.settings, "ai_fallback_provider", "fake-fallback")
    monkeypatch.setattr(pr.settings, "ai_max_retries", 0)

    result, routed = pr.complete([ChatMessage(role="user", content="hi")])
    assert result.text == "ok"
    assert result.provider == "fake-fallback"
    assert routed.used_fallback is True


# --- Token counting & context building ---------------------------------------


def test_estimate_tokens_scales_with_length():
    assert token_counter.estimate_tokens("") == 0
    short = token_counter.estimate_tokens("hello")
    long = token_counter.estimate_tokens("hello " * 100)
    assert 0 < short < long


def test_estimate_cost_uses_provider_rate_table():
    cost = token_counter.estimate_cost_usd("anthropic", 1000, 1000)
    assert cost > 0
    assert token_counter.estimate_cost_usd("unknown-provider", 1000, 1000) == 0.0


def test_context_builder_trims_oldest_history_first():
    history = [ChatMessage(role="user" if i % 2 == 0 else "assistant", content=f"turn {i} " * 50) for i in range(20)]
    messages = context_builder.build_context(
        system_prompt="be helpful",
        summary=None,
        history=history,
        new_user_message="final question",
        max_context_tokens=200,
    )
    # System prompt first, then some trimmed tail of history, then the new user message last.
    assert messages[0].role == "system"
    assert messages[-1].content == "final question"
    assert len(messages) < len(history) + 2  # something was trimmed given the tight budget
    # Whatever history survived must be the most recent turns, not the oldest.
    kept_contents = [m.content for m in messages[1:-1]]
    if kept_contents:
        assert "turn 19" in kept_contents[-1]


def test_context_builder_includes_summary_as_system_turn():
    messages = context_builder.build_context(
        system_prompt=None,
        summary="the user previously asked about SSC CGL eligibility",
        history=[],
        new_user_message="what about the age limit?",
        max_context_tokens=1000,
    )
    assert any("SSC CGL eligibility" in m.content for m in messages if m.role == "system")


# --- Prompt registry -----------------------------------------------------


def test_default_prompts_seeded_at_startup(seeded):
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        row = prompt_service.get_active_template(db, "system.default_assistant")
        assert row.active is True
        assert row.version == 1
        row2 = prompt_service.get_active_template(db, "conversation.summarize")
        assert "{conversation_text}" in row2.template
    finally:
        db.close()


def test_render_substitutes_variables_and_validates_required_ones():
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        rendered = prompt_service.render(db, "conversation.summarize", {"conversation_text": "hello world"})
        assert "hello world" in rendered

        with pytest.raises(prompt_service.PromptValidationError):
            prompt_service.render(db, "conversation.summarize", {})
    finally:
        db.close()


def test_render_unknown_key_raises_not_found():
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        with pytest.raises(prompt_service.PromptNotFoundError):
            prompt_service.render(db, "does.not.exist", {})
    finally:
        db.close()


def test_register_template_increments_version_and_deactivates_previous():
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        v1 = prompt_service.register_template(db, "test.greeting", "Hello {name}!", variables=["name"])
        assert v1.version == 1
        v2 = prompt_service.register_template(db, "test.greeting", "Hi there, {name}.", variables=["name"])
        assert v2.version == 2
        assert v2.active is True

        db.refresh(v1)
        assert v1.active is False

        active = prompt_service.get_active_template(db, "test.greeting")
        assert active.id == v2.id
    finally:
        db.close()


# --- Conversation memory -------------------------------------------------


def test_conversation_get_or_create_is_idempotent_per_session_key():
    from app.ai import conversation_manager
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        c1 = conversation_manager.get_or_create_conversation(db, session_key="sess-abc-123")
        c2 = conversation_manager.get_or_create_conversation(db, session_key="sess-abc-123")
        assert c1.id == c2.id
    finally:
        db.close()


def test_conversation_summarizes_after_trigger_threshold(monkeypatch):
    from app.ai import conversation_manager
    from app.core.config import settings
    from app.db.session import SessionLocal

    monkeypatch.setattr(settings, "ai_conversation_summary_trigger", 4)
    monkeypatch.setattr(settings, "ai_conversation_history_max_messages", 2)

    db = SessionLocal()
    try:
        conversation = conversation_manager.get_or_create_conversation(db, session_key="sess-summarize-me")
        for i in range(5):
            conversation_manager.add_message(db, conversation, role="user", content=f"message number {i}")

        db.refresh(conversation)
        assert conversation.summary is not None
        # No AI provider is configured in this test env, so the
        # deterministic fallback summary path must have been used.
        assert "auto-condensed" in conversation.summary
    finally:
        db.close()


# --- Observability ---------------------------------------------------------


def test_usage_event_recorded_on_completion_failure():
    from app.ai import observability
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        before = observability.usage_summary(db, since_hours=24)["failure_count"]
        observability.record_event(
            db,
            observability.UsageEvent(
                service="completion",
                provider="anthropic",
                model=None,
                operation="test",
                used_fallback=False,
                prompt_tokens=0,
                completion_tokens=0,
                cost_estimate_usd=0.0,
                latency_ms=0.0,
                success=False,
                error="simulated failure",
            ),
        )
        after = observability.usage_summary(db, since_hours=24)["failure_count"]
        assert after == before + 1

        health = observability.live_provider_health()
        assert "anthropic" in health
        assert health["anthropic"]["status"] == "degraded"
    finally:
        db.close()


# --- API surface -------------------------------------------------------------


def test_health_endpoint_is_public(seeded):
    client = seeded["client"]
    response = client.get("/api/v1/ai/health")
    assert response.status_code == 200
    body = response.json()
    assert body["default_provider"] == "anthropic"
    assert "configured_providers" in body


def test_providers_endpoint_requires_admin(seeded):
    client = seeded["client"]
    denied = client.get("/api/v1/ai/providers")
    assert denied.status_code in (401, 403)

    allowed = client.get("/api/v1/ai/providers", headers=seeded["admin"])
    assert allowed.status_code == 200
    assert len(allowed.json()["providers"]) == len(PROVIDERS)


def test_conversation_flow_returns_503_without_a_provider(seeded):
    client, candidate = seeded["client"], seeded["candidate"]

    started = client.post("/api/v1/ai/conversations", headers=candidate, json={"session_key": "e2e-session-1"})
    assert started.status_code == 200
    conversation_id = started.json()["id"]

    reply = client.post(
        f"/api/v1/ai/conversations/{conversation_id}/messages",
        headers=candidate,
        json={"message": "What jobs match my profile?"},
    )
    # No provider configured -> the completion layer raises
    # CompletionError -> the endpoint translates that to 503, not a
    # raw 500, and the user's message is still persisted either way.
    assert reply.status_code == 503

    history = client.get(f"/api/v1/ai/conversations/{conversation_id}/messages", headers=candidate)
    assert history.status_code == 200
    roles = [m["role"] for m in history.json()["messages"]]
    assert "user" in roles


def test_conversation_is_owned_by_creator_only(seeded):
    client, candidate = seeded["client"], seeded["candidate"]

    started = client.post("/api/v1/ai/conversations", headers=candidate, json={"session_key": "e2e-session-2"})
    conversation_id = started.json()["id"]

    other = _register_and_login(client, "v201-other@example.com", "V201 Other")
    forbidden = client.get(f"/api/v1/ai/conversations/{conversation_id}/messages", headers=other)
    assert forbidden.status_code == 404


def test_prompt_registry_api_roundtrip(seeded):
    client, admin = seeded["client"], seeded["admin"]

    listed = client.get("/api/v1/ai/prompts", headers=admin)
    assert listed.status_code == 200
    keys = {t["key"] for t in listed.json()["templates"]}
    assert "system.default_assistant" in keys

    created = client.post(
        "/api/v1/ai/prompts",
        headers=admin,
        json={"key": "api.test.template", "template": "Say hello to {name}", "variables": ["name"]},
    )
    assert created.status_code == 200
    assert created.json()["version"] == 1


def test_usage_and_logs_endpoints(seeded):
    client, admin = seeded["client"], seeded["admin"]

    usage = client.get("/api/v1/ai/usage", headers=admin)
    assert usage.status_code == 200
    assert "total_calls" in usage.json()

    logs = client.get("/api/v1/ai/usage/logs", headers=admin)
    assert logs.status_code == 200
    assert isinstance(logs.json()["logs"], list)


def test_config_endpoint_never_returns_api_keys(seeded):
    client, admin = seeded["client"], seeded["admin"]

    response = client.get("/api/v1/ai/config", headers=admin)
    assert response.status_code == 200
    body = response.json()
    assert "default_provider" in body
    serialized = str(body)
    for leaked_term in ("api_key", "_key"):
        assert leaked_term not in serialized.lower()
