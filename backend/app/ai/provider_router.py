"""Picks a provider from configuration and applies retry + fallback.

This is the one place in the codebase that knows "which provider runs
by default" and "what to try next if it fails" — every AI service
(completion_service, embedding_service, moderation_service) goes
through here rather than reaching into app.ai.providers.PROVIDERS
directly, so that policy stays in one place.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.ai.providers import PROVIDERS, ChatMessage, CompletionResult, EmbeddingResult, ModerationResult
from app.ai.providers.base import LLMProvider, ProviderError, ProviderNotConfiguredError
from app.core.config import settings


@dataclass
class RoutedResult:
    """Wraps a provider result with routing metadata the caller (and
    observability.py) needs: how long it took, whether the primary
    provider was used or a fallback kicked in, and how many attempts
    it took."""

    attempts: int
    latency_ms: float
    used_fallback: bool
    provider_name: str


class AllProvidersFailedError(RuntimeError):
    def __init__(self, errors: list[ProviderError]):
        detail = "; ".join(str(e) for e in errors)
        super().__init__(f"All configured providers failed: {detail}")
        self.errors = errors


def get_provider(name: str) -> LLMProvider:
    provider = PROVIDERS.get(name)
    if provider is None:
        raise ValueError(f"Unknown AI provider '{name}'. Known providers: {sorted(PROVIDERS)}")
    return provider


def _provider_order(preferred: str | None) -> list[str]:
    """Primary provider first, then the configured fallback (if set
    and different), so a fallback is only ever a single explicit hop
    — no silent cascading through every registered provider."""
    primary = preferred or settings.ai_default_provider
    order = [primary]
    if settings.ai_fallback_provider and settings.ai_fallback_provider != primary:
        order.append(settings.ai_fallback_provider)
    return order


def _with_retry_and_fallback(capability: str, provider_names: list[str], call):
    """Runs ``call(provider)`` for each provider in order, retrying a
    given provider up to ``ai_max_retries`` times before moving to the
    next one. Returns (result, RoutedResult) or raises
    AllProvidersFailedError if every provider/attempt failed."""
    errors: list[ProviderError] = []
    attempts = 0
    started = time.monotonic()

    for idx, name in enumerate(provider_names):
        provider = get_provider(name)
        if not provider.is_configured():
            errors.append(ProviderNotConfiguredError(name, "not configured"))
            continue
        if not provider.supports(capability):
            errors.append(ProviderError(name, f"does not support {capability}"))
            continue

        for attempt in range(1, settings.ai_max_retries + 2):  # +1 initial try, +ai_max_retries retries
            attempts += 1
            try:
                result = call(provider)
                latency_ms = (time.monotonic() - started) * 1000
                return result, RoutedResult(
                    attempts=attempts, latency_ms=latency_ms, used_fallback=idx > 0, provider_name=name
                )
            except ProviderNotConfiguredError as exc:
                errors.append(exc)
                break  # retrying won't help a missing key
            except ProviderError as exc:
                errors.append(exc)
                continue  # try again, up to ai_max_retries

    raise AllProvidersFailedError(errors)


def complete(
    messages: list[ChatMessage],
    *,
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout_seconds: float | None = None,
) -> tuple[CompletionResult, RoutedResult]:
    order = _provider_order(provider)

    def _call(p: LLMProvider) -> CompletionResult:
        return p.complete(
            messages,
            model=model or _default_model_for(p.name),
            temperature=settings.ai_default_temperature if temperature is None else temperature,
            max_tokens=settings.ai_default_max_tokens if max_tokens is None else max_tokens,
            timeout_seconds=settings.ai_request_timeout_seconds if timeout_seconds is None else timeout_seconds,
        )

    return _with_retry_and_fallback("complete", order, _call)


def embed(
    texts: list[str], *, provider: str | None = None, model: str | None = None, timeout_seconds: float | None = None
) -> tuple[EmbeddingResult, RoutedResult]:
    order = _provider_order(provider)

    def _call(p: LLMProvider) -> EmbeddingResult:
        return p.embed(
            texts,
            model=model or _default_embedding_model_for(p.name),
            timeout_seconds=settings.ai_request_timeout_seconds if timeout_seconds is None else timeout_seconds,
        )

    return _with_retry_and_fallback("embed", order, _call)


def moderate(text: str, *, provider: str | None = None, timeout_seconds: float | None = None) -> tuple[ModerationResult, RoutedResult]:
    order = _provider_order(provider)

    def _call(p: LLMProvider) -> ModerationResult:
        return p.moderate(
            text, timeout_seconds=settings.ai_request_timeout_seconds if timeout_seconds is None else timeout_seconds
        )

    return _with_retry_and_fallback("moderate", order, _call)


def _default_model_for(provider_name: str) -> str:
    return {
        "anthropic": settings.ai_anthropic_model,
        "openai": settings.ai_openai_model,
        "gemini": settings.ai_gemini_model,
        "openrouter": settings.ai_openrouter_model,
        "ibm": settings.ai_watsonx_model,
    }.get(provider_name, settings.ai_default_model)


def _default_embedding_model_for(provider_name: str) -> str:
    return {"openai": settings.ai_openai_embedding_model}.get(provider_name, "unknown")


def provider_status() -> list[dict]:
    """Configuration snapshot for every registered provider — used by
    the admin dashboard's "Provider Status" panel. Does not make any
    network call; "configured" only reflects whether credentials are
    present, not whether the vendor is currently reachable (that's
    what observability.py's rolling health stats are for)."""
    return [
        {
            "name": name,
            "configured": provider.is_configured(),
            "capabilities": [c for c in ("complete", "embed", "moderate") if provider.supports(c)],
            "is_default": name == settings.ai_default_provider,
            "is_fallback": name == settings.ai_fallback_provider,
        }
        for name, provider in PROVIDERS.items()
    ]
