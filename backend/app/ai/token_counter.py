"""Token estimation.

No tokenizer library ships with this layer (avoids pulling in
``tiktoken``/model-specific tokenizers as a hard dependency for every
deployment, most of which don't need exact counts). Estimates use the
well-known "~4 characters per token" heuristic for English text, which
is accurate to within roughly 10-15% for the models this layer talks
to — good enough for context-window budgeting and cost estimation, not
guaranteed to match a provider's actual billed token count. Real
counts from a completion response (CompletionResult.prompt_tokens /
completion_tokens) always take precedence over an estimate wherever
both are available — see observability.py.
"""

from __future__ import annotations

from app.ai.providers.base import ChatMessage

_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def estimate_messages_tokens(messages: list[ChatMessage]) -> int:
    # +4 per message approximates the small per-turn role/formatting
    # overhead most chat APIs add on top of raw content.
    return sum(estimate_tokens(m.content) + 4 for m in messages)


# Rough, publicly-documented per-1K-token list prices in USD, current
# as of this layer's release. These are estimates for admin-dashboard
# cost visibility only — never used for billing, and intentionally
# easy to override in one place as vendor pricing changes.
_COST_PER_1K_TOKENS_USD: dict[str, tuple[float, float]] = {
    # (prompt, completion)
    "anthropic": (0.003, 0.015),
    "openai": (0.0005, 0.0015),
    "gemini": (0.000075, 0.0003),
    "openrouter": (0.001, 0.003),
}


def estimate_cost_usd(provider: str, prompt_tokens: int, completion_tokens: int) -> float:
    prompt_rate, completion_rate = _COST_PER_1K_TOKENS_USD.get(provider, (0.0, 0.0))
    return round((prompt_tokens / 1000) * prompt_rate + (completion_tokens / 1000) * completion_rate, 6)
