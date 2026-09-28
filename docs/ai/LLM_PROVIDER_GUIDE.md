# CareerOS â€” LLM Provider Guide

How to configure, add, and reason about LLM providers in the V20.1 AI
Infrastructure layer.

## Supported providers

| Provider | Capabilities | Status |
|---|---|---|
| `anthropic` | complete, moderate (via classification call) | Live |
| `openai` | complete, embed, moderate | Live |
| `gemini` | complete | Live |
| `openrouter` | complete | Live |
| `local` | â€” | Stub (reserved, not implemented) |
| `ollama` | â€” | Stub (reserved, not implemented) |
| `azure_openai` | â€” | Stub (reserved, not implemented) |

Calling a stub provider raises `ProviderNotConfiguredError` with a
clear "not yet implemented" message â€” it never silently no-ops or
crashes with an unrelated error. Registering them now (in
`app/ai/providers/__init__.py`'s `PROVIDERS` dict) means provider
selection, config validation, and the admin "Provider Status" panel
already account for a future real integration landing later, without
an API shape change.

## No business logic depends on a specific provider

Every caller â€” `completion_service`, `embedding_service`,
`moderation_service`, and anything built on them later â€” goes through
`app.ai.provider_router`, never a vendor adapter directly. Switching
the default provider is a config change:

```bash
AI_DEFAULT_PROVIDER=openai
```

No call site anywhere in the codebase needs to change.

## Selecting a provider per-call

Every router function (`complete`, `embed`, `moderate`) and every
service function built on them accepts an optional `provider=` /
`model=` override, for the rare case a specific call needs a specific
vendor (e.g. a moderation call that should always use OpenAI even if
the default provider is Anthropic, since Anthropic has no dedicated
moderation endpoint):

```python
from app.ai import completion_service

result = completion_service.generate(
    db, operation="my_feature.something",
    user_message="...",
    provider="openai",   # optional override
    model="gpt-4o",      # optional override
)
```

Omit both to use `AI_DEFAULT_PROVIDER` / that provider's configured
default model.

## Fallback and retry

`provider_router` applies:

1. **Retry** â€” up to `AI_MAX_RETRIES` retries (default `1`, i.e. 2
   total attempts) against the *same* provider for a transient
   `ProviderError` (timeout, 5xx, malformed response). A
   `ProviderNotConfiguredError` is never retried â€” a missing API key
   won't fix itself on attempt 2.
2. **Fallback** â€” exactly one hop to `AI_FALLBACK_PROVIDER` (if set
   and different from the primary) once the primary is exhausted.
   This is deliberately a single explicit hop, not a cascade through
   every registered provider â€” an unbounded cascade would make
   failures slow and hard to reason about, and would silently route
   sensitive traffic to a provider nobody chose as a real fallback.

If every attempt across both providers fails, the router raises
`AllProvidersFailedError`, which the service layer converts into a
typed `CompletionError` / `EmbeddingError` (never a raw exception
reaching the API layer â€” see `AI_ARCHITECTURE.md`).

## Adding a new real provider

1. Add `backend/app/ai/providers/<name>_provider.py` implementing
   `LLMProvider` (see `providers/base.py`). Implement only the
   capabilities the vendor actually supports â€” leave `embed`/`moderate`
   unimplemented (don't override them) if the vendor doesn't offer
   them; `LLMProvider.supports(capability)` detects this automatically.
2. Register it in `providers/__init__.py`'s `PROVIDERS` dict,
   replacing (not adding alongside) the `StubProvider` entry if one
   already exists for it.
3. Add its API key / model settings to `app/core/config.py` following
   the `ai_<name>_api_key` / `ai_<name>_model` naming already used.
4. Document it in the provider table above and in
   `AI_CONFIGURATION.md`.

No other file needs to change â€” `provider_router.py`,
`completion_service.py`, `embedding_service.py`, `moderation_service.py`,
and every API endpoint are all written against the `LLMProvider`
interface, not against any specific vendor.

## Cost estimates

`token_counter.estimate_cost_usd(provider, prompt_tokens,
completion_tokens)` uses a small hardcoded per-1K-token price table in
`token_counter.py`. These are **rough, publicly-documented list
prices for admin-dashboard visibility only** â€” never used for billing,
and not guaranteed to track a vendor's current pricing. Update the
table in one place (`_COST_PER_1K_TOKENS_USD`) as vendor pricing
changes.

## Why REST via `httpx` instead of each vendor's SDK

`anthropic_provider.py` uses the `anthropic` SDK (already a dependency
for V6 Career AI). `openai_provider.py`, `gemini_provider.py`, and
`openrouter_provider.py` call each vendor's REST API directly via
`httpx` (already a dependency) rather than adding the `openai` and
`google-generativeai` SDKs as new hard dependencies for one provider
each. OpenRouter's API is OpenAI-compatible, so its adapter reuses the
same request/response shape as the OpenAI adapter with a different
base URL and headers.

