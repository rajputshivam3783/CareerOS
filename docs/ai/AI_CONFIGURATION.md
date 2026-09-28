# CareerOS â€” AI Configuration

All settings below live in `backend/app/core/config.py` (the `Settings`
class), settable via environment variables of the same name in
upper-case. Every one has a default â€” nothing here is required to
start the app; with no `AI_*_API_KEY` set, the layer runs with all
providers reporting "not configured" (see `AI_ARCHITECTURE.md`
"Zero-config posture").

These are new, separate from V6's `career_ai_*` settings (e.g.
`CAREER_AI_ANTHROPIC_API_KEY`), which continue to configure
`app/services/career_ai.py` directly and are untouched by this pass.
As a convenience, `AnthropicProvider` falls back to
`CAREER_AI_ANTHROPIC_API_KEY` if `AI_ANTHROPIC_API_KEY` isn't set, so a
deployment that already configured V6 Career AI doesn't need to
duplicate the same key under a new name to also light up this layer's
Anthropic adapter.

## Provider selection & routing

| Setting | Default | Purpose |
|---|---|---|
| `AI_DEFAULT_PROVIDER` | `anthropic` | Provider used when a call doesn't specify one. |
| `AI_FALLBACK_PROVIDER` | *(unset)* | Single fallback hop if the default provider fails after retries. |
| `AI_REQUEST_TIMEOUT_SECONDS` | `30.0` | Per-request timeout passed to the vendor SDK/HTTP client. |
| `AI_MAX_RETRIES` | `1` | Retries against the *same* provider before falling back (0 = try once, no retry). |

## Model & generation defaults

| Setting | Default | Purpose |
|---|---|---|
| `AI_DEFAULT_MODEL` | `claude-sonnet-5` | Used if a provider-specific model default doesn't apply. |
| `AI_DEFAULT_TEMPERATURE` | `0.7` | Default sampling temperature. |
| `AI_DEFAULT_MAX_TOKENS` | `1024` | Default max completion tokens. |
| `AI_MAX_CONTEXT_TOKENS` | `8000` | Token budget `context_builder` trims conversation history to. |

## Per-provider credentials & models

| Setting | Default | Purpose |
|---|---|---|
| `AI_ANTHROPIC_API_KEY` | *(unset, falls back to `CAREER_AI_ANTHROPIC_API_KEY`)* | Anthropic API key. |
| `AI_ANTHROPIC_MODEL` | `claude-sonnet-5` | Model used for Anthropic completions. |
| `AI_OPENAI_API_KEY` | *(unset)* | OpenAI API key. |
| `AI_OPENAI_MODEL` | `gpt-4o-mini` | Model used for OpenAI completions. |
| `AI_OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Model used for OpenAI embeddings. |
| `AI_GEMINI_API_KEY` | *(unset)* | Google Gemini API key. |
| `AI_GEMINI_MODEL` | `gemini-1.5-flash` | Model used for Gemini completions. |
| `AI_OPENROUTER_API_KEY` | *(unset)* | OpenRouter API key. |
| `AI_OPENROUTER_MODEL` | `openrouter/auto` | Model used for OpenRouter completions. |

## Moderation

| Setting | Default | Purpose |
|---|---|---|
| `AI_MODERATION_ENABLED` | `false` | When `false`, `moderation_service.moderate_text` always returns "not flagged" without calling a provider. When `true` with no moderation-capable provider configured, falls back to a narrow keyword screen â€” see `moderation_service.py`'s docstring; this fallback is not a substitute for a real moderation provider in production. |

## Conversation memory

| Setting | Default | Purpose |
|---|---|---|
| `AI_CONVERSATION_HISTORY_MAX_MESSAGES` | `20` | Turns kept verbatim before being eligible for summarization. |
| `AI_CONVERSATION_SUMMARY_TRIGGER` | `30` | Message count at which older turns get compressed into `AIConversation.summary`. |

## Example `.env` block

```bash
AI_DEFAULT_PROVIDER=anthropic
AI_FALLBACK_PROVIDER=openai
AI_ANTHROPIC_API_KEY=sk-ant-...
AI_OPENAI_API_KEY=sk-...
AI_MODERATION_ENABLED=true
```

## Viewing active configuration

`GET /api/v1/ai/config` (admin-only) returns the current values above
â€” **API key values are never included** in the response, only
model/timeout/retry/threshold settings and a `provider_models` map.
The AI Admin dashboard's "Configuration" tab renders this endpoint
read-only; there is no in-app settings editor in this pass â€” every
value here is environment-configured, consistent with how the rest of
CareerOS's `Settings` class works.

