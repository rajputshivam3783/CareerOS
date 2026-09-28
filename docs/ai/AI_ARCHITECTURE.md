# CareerOS â€” AI Architecture

## What this is

V20.1 adds the **AI foundation layer** â€” `backend/app/ai/` â€” a
provider-agnostic abstraction over LLM vendors plus the centralized
services any AI feature needs: prompts, completions, embeddings,
moderation, conversation memory, token accounting, and observability.

**This is infrastructure, not a feature.** Nothing in this pass
implements Resume AI, Interview AI, Career Copilot, Learning AI, or
Job Recommendations â€” those are V20.2+ *consumers* of this layer (see
`ROADMAP.md`). The one pre-existing exception is `app/services/
career_ai.py`, which predates this layer and was left exactly as
it was â€” it calls the `anthropic` SDK directly rather than going
through `app/ai/`. Migrating it onto this framework is a future,
separate, deliberate decision, not something this pass did implicitly.

## Layout

```
backend/app/ai/
â”œâ”€â”€ providers/
â”‚   â”œâ”€â”€ base.py              LLMProvider ABC, ChatMessage/CompletionResult/
â”‚   â”‚                        EmbeddingResult/ModerationResult, error types,
â”‚   â”‚                        StubProvider (for not-yet-built providers)
â”‚   â”œâ”€â”€ anthropic_provider.py
â”‚   â”œâ”€â”€ openai_provider.py
â”‚   â”œâ”€â”€ gemini_provider.py
â”‚   â”œâ”€â”€ openrouter_provider.py
â”‚   â””â”€â”€ __init__.py          PROVIDERS registry (name -> instance)
â”œâ”€â”€ provider_router.py       Selects a provider from config; retry + one
â”‚                            explicit fallback hop; provider_status()
â”œâ”€â”€ token_counter.py         Character-heuristic token/cost estimation
â”œâ”€â”€ prompt_service.py        Versioned, DB-backed prompt template registry
â”œâ”€â”€ context_builder.py       Token-budgeted message assembly
â”œâ”€â”€ conversation_manager.py  Session/user memory, history, auto-summarization
â”œâ”€â”€ completion_service.py    High-level "generate text" entry point
â”œâ”€â”€ embedding_service.py     High-level "embed text" entry point
â”œâ”€â”€ moderation_service.py    Content moderation (provider or keyword fallback)
â””â”€â”€ observability.py         Usage logging, live health, admin queries
```

## Request flow (a completion call)

```
caller (future feature, or /ai/conversations/{id}/messages)
  -> completion_service.generate(db, ...)
       -> context_builder.build_context(...)        # token-budgeted messages
       -> provider_router.complete(...)              # picks provider, retries, falls back
            -> providers.<vendor>.LLMProvider.complete(...)
       -> observability.record_event(...)             # AIUsageLog row, always (success or failure)
  <- CompletionResult | CompletionError
```

Every AI service (`completion_service`, `embedding_service`,
`moderation_service`) follows this same shape: call the router, log
the outcome via `observability.record_event`, and translate a router
failure into a typed service-level error (`CompletionError`,
`EmbeddingError`) rather than letting a raw `ProviderError` or HTTP
exception leak to the caller.

## Zero-config posture

With no `AI_*_API_KEY` set anywhere, the layer still starts, and every
endpoint still responds:

- `GET /ai/health` reports `"no_providers_configured"` rather than 500ing.
- A completion call raises `CompletionError`, which the API layer
  turns into a `503` with a clear message â€” never an unhandled
  exception.
- `conversation_manager`'s summarization falls back to a plain
  truncated concatenation (no model call) when no provider is
  configured, so conversation memory still works end to end.
- `moderation_service` returns `"disabled"` by default
  (`AI_MODERATION_ENABLED=false`); when enabled with no provider
  configured, it falls back to a narrow keyword screen rather than
  failing closed or open silently.

This mirrors the existing posture of V6 Career AI (template fallback
with no key) and V19.4 Notifications (channels register as
`not_implemented` rather than crashing) â€” see `KNOWN_LIMITATIONS.md`.

## Database

Four new, purely additive tables (`backend/migrations/
v20_1_ai_infrastructure.sql`; SQLite dev/test gets them for free via
`Base.metadata.create_all()`):

| Table | Purpose |
|---|---|
| `ai_conversations` | One row per conversation thread (session- or user-scoped), plus its rolling `summary`. |
| `ai_messages` | One row per turn, with real (assistant) or estimated (user) token counts. |
| `ai_prompt_templates` | Versioned prompt templates; only the highest-`version` `active=true` row per `key` is live. |
| `ai_usage_logs` | One row per provider call, success or failure â€” the durable source of truth for the admin Usage panel. |

No existing table is modified.

## Observability model

Two layers, deliberately mirroring `app/core/metrics.py`'s existing
split for HTTP request metrics:

1. **In-memory** (`observability.live_provider_health()`) â€” a rolling
   window of the last 50 outcomes per provider, for a cheap "is this
   provider healthy right now" signal with no DB query. Per-process;
   resets on restart, same tradeoff as `app/core/metrics.py`'s counters
   and `app/core/rate_limit.py`'s in-memory buckets.
2. **Durable** (`ai_usage_logs` + `observability.usage_summary()` /
   `recent_logs()`) â€” survives a restart, aggregatable by provider and
   service, backs the admin dashboard's Usage and Logs tabs.

## What's intentionally not here

- **Vector storage / similarity search** â€” `embedding_service` embeds
  text and returns vectors; it does not persist or index them. A
  feature that needs similarity search today should keep using
  `app/services/semantic_search.py`'s TF-IDF ranking (no API key, no
  vector-store dependency). A real vector database is a stated future
  extension (see "Future vector databases" in the original V20.1 spec
  and `ROADMAP.md`), not built in this pass.
- **Long-term, cross-conversation user memory** â€” `AIConversation` /
  `AIMessage` give per-thread memory; a persistent user-level memory
  that spans separate conversations is a future extension, not built here.
- **A real tokenizer** â€” `token_counter.py` uses the standard
  "~4 characters per token" heuristic rather than a
  model-specific tokenizer library, to avoid a hard dependency every
  deployment would otherwise carry. See `token_counter.py`'s docstring
  for the accuracy tradeoff.

See also `LLM_PROVIDER_GUIDE.md`, `PROMPT_ENGINE.md`, and
`AI_CONFIGURATION.md` for the adjacent detail this file doesn't cover.

