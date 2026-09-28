"""High-level "generate text" entry point. This is the function any
future feature (Resume AI, Interview AI, Career Copilot, ...) is
expected to call rather than touching app.ai.provider_router directly
— it adds context budgeting, usage logging, and a consistent error
shape on top of the router.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai import observability
from app.ai.context_builder import build_context
from app.ai.provider_router import AllProvidersFailedError, complete as route_complete
from app.ai.providers.base import ChatMessage, CompletionResult
from app.ai.token_counter import estimate_cost_usd
from app.core.config import settings


class CompletionError(RuntimeError):
    """Raised when every configured provider (primary + fallback)
    failed. Callers should catch this and degrade gracefully — e.g.
    app.services.career_ai's template-fallback pattern — rather than
    letting it surface as a raw 500."""


def generate(
    db: Session,
    *,
    operation: str,
    system_prompt: str | None = None,
    summary: str | None = None,
    history: list[ChatMessage] | None = None,
    user_message: str,
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    user_id: int | None = None,
) -> CompletionResult:
    """Builds a token-budgeted context, calls the provider router, and
    logs the outcome (success or failure) to AIUsageLog before
    returning or raising.

    ``operation`` is a short free-text label for *what feature/purpose*
    this call is for (e.g. "career_ai.advice", "resume_ai.rewrite") —
    it does not affect routing, only shows up in the admin usage
    dashboard so cost/latency can be broken down by feature.
    """
    messages = build_context(
        system_prompt=system_prompt,
        summary=summary,
        history=history or [],
        new_user_message=user_message,
        max_context_tokens=settings.ai_max_context_tokens,
    )

    try:
        result, routed = route_complete(
            messages, provider=provider, model=model, temperature=temperature, max_tokens=max_tokens
        )
    except AllProvidersFailedError as exc:
        observability.record_event(
            db,
            observability.UsageEvent(
                service="completion",
                provider=provider or settings.ai_default_provider,
                model=model,
                operation=operation,
                used_fallback=False,
                prompt_tokens=0,
                completion_tokens=0,
                cost_estimate_usd=0.0,
                latency_ms=0.0,
                success=False,
                error=str(exc),
                user_id=user_id,
            ),
        )
        raise CompletionError(str(exc)) from exc

    observability.record_event(
        db,
        observability.UsageEvent(
            service="completion",
            provider=result.provider,
            model=result.model,
            operation=operation,
            used_fallback=routed.used_fallback,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_estimate_usd=estimate_cost_usd(result.provider, result.prompt_tokens, result.completion_tokens),
            latency_ms=routed.latency_ms,
            success=True,
            user_id=user_id,
        ),
    )
    return result
