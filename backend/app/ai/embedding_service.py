"""High-level "embed text" entry point.

``kind`` documents *what* is being embedded (resume / job / skill /
course) purely for usage-log labelling and future routing (e.g. a
different embedding model per kind) — this layer doesn't do anything
kind-specific yet, and doesn't persist vectors anywhere itself. Vector
storage/search is explicitly out of scope for this phase (see
"Future vector databases" in AI_ARCHITECTURE.md); a caller that needs
similarity search today should keep using
app.services.semantic_search's TF-IDF ranking, which needs no API key
and has no vector-store dependency.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai import observability
from app.ai.provider_router import AllProvidersFailedError, embed as route_embed
from app.ai.providers.base import EmbeddingResult
from app.ai.token_counter import estimate_cost_usd
from app.core.config import settings

EMBEDDING_KINDS = ("resume", "job", "skill", "course", "other")


class EmbeddingError(RuntimeError):
    pass


def embed_texts(
    db: Session,
    texts: list[str],
    *,
    kind: str = "other",
    provider: str | None = None,
    model: str | None = None,
    user_id: int | None = None,
) -> EmbeddingResult:
    if kind not in EMBEDDING_KINDS:
        raise ValueError(f"Unknown embedding kind '{kind}'. Expected one of {EMBEDDING_KINDS}")
    if not texts:
        raise ValueError("embed_texts requires at least one text")

    try:
        result, routed = route_embed(texts, provider=provider, model=model)
    except AllProvidersFailedError as exc:
        observability.record_event(
            db,
            observability.UsageEvent(
                service="embedding",
                provider=provider or settings.ai_default_provider,
                model=model,
                operation=f"embed.{kind}",
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
        raise EmbeddingError(str(exc)) from exc

    observability.record_event(
        db,
        observability.UsageEvent(
            service="embedding",
            provider=result.provider,
            model=result.model,
            operation=f"embed.{kind}",
            used_fallback=routed.used_fallback,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=0,
            cost_estimate_usd=estimate_cost_usd(result.provider, result.prompt_tokens, 0),
            latency_ms=routed.latency_ms,
            success=True,
            user_id=user_id,
        ),
    )
    return result
