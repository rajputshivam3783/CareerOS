"""Content moderation. Uses a configured provider's moderation
capability when available; otherwise falls back to a small,
conservative keyword screen so the service always returns a verdict
rather than raising when no provider is configured — same
zero-config-works posture as the rest of this layer. The fallback is
intentionally narrow (obvious high-severity terms only) since a
false "flagged" blocks a real user; it is not a substitute for a real
moderation provider in production and AI_CONFIGURATION.md says so.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai import observability
from app.ai.provider_router import AllProvidersFailedError, moderate as route_moderate
from app.ai.providers.base import ModerationResult
from app.core.config import settings

_FALLBACK_BLOCKLIST = (
    "kill myself",
    "child sexual",
    "how to make a bomb",
    "buy illegal weapons",
)


def _fallback_moderate(text: str) -> ModerationResult:
    lowered = text.lower()
    hits = [term for term in _FALLBACK_BLOCKLIST if term in lowered]
    return ModerationResult(flagged=bool(hits), categories=["keyword_match"] if hits else [], provider="fallback")


def moderate_text(db: Session, text: str, *, user_id: int | None = None) -> ModerationResult:
    if not settings.ai_moderation_enabled:
        return ModerationResult(flagged=False, categories=[], provider="disabled")

    try:
        result, routed = route_moderate(text)
    except AllProvidersFailedError:
        result = _fallback_moderate(text)
        observability.record_event(
            db,
            observability.UsageEvent(
                service="moderation",
                provider="fallback",
                model=None,
                operation="moderate",
                used_fallback=True,
                prompt_tokens=0,
                completion_tokens=0,
                cost_estimate_usd=0.0,
                latency_ms=0.0,
                success=True,
                user_id=user_id,
            ),
        )
        return result

    observability.record_event(
        db,
        observability.UsageEvent(
            service="moderation",
            provider=result.provider,
            model=None,
            operation="moderate",
            used_fallback=routed.used_fallback,
            prompt_tokens=0,
            completion_tokens=0,
            cost_estimate_usd=0.0,
            latency_ms=routed.latency_ms,
            success=True,
            user_id=user_id,
        ),
    )
    return result
