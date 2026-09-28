"""OpenAI adapter — plain REST via ``httpx`` (already a dependency)
rather than the ``openai`` SDK, to avoid adding a new package for one
provider. OpenRouter reuses this same request shape since it exposes
an OpenAI-compatible API (see openrouter_provider.py).
"""

from __future__ import annotations

import httpx

from app.ai.providers.base import (
    ChatMessage,
    CompletionResult,
    EmbeddingResult,
    LLMProvider,
    ModerationResult,
    ProviderError,
    ProviderNotConfiguredError,
)
from app.core.config import settings

_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(LLMProvider):
    name = "openai"

    def _api_key(self) -> str | None:
        return settings.ai_openai_api_key

    def is_configured(self) -> bool:
        return bool(self._api_key())

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key()}", "Content-Type": "application/json"}

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_seconds: float,
    ) -> CompletionResult:
        if not self.is_configured():
            raise ProviderNotConfiguredError(self.name, "AI_OPENAI_API_KEY is not set")

        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            response = httpx.post(
                f"{_BASE_URL}/chat/completions", json=payload, headers=self._headers(), timeout=timeout_seconds
            )
            response.raise_for_status()
            data = response.json()
            choice = data["choices"][0]
            usage = data.get("usage", {})
            return CompletionResult(
                text=choice["message"]["content"],
                provider=self.name,
                model=data.get("model", model),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                finish_reason=choice.get("finish_reason"),
                raw={"id": data.get("id")},
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(self.name, str(exc)) from exc

    def embed(self, texts: list[str], *, model: str, timeout_seconds: float) -> EmbeddingResult:
        if not self.is_configured():
            raise ProviderNotConfiguredError(self.name, "AI_OPENAI_API_KEY is not set")

        try:
            response = httpx.post(
                f"{_BASE_URL}/embeddings",
                json={"model": model, "input": texts},
                headers=self._headers(),
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            vectors = [row["embedding"] for row in sorted(data["data"], key=lambda r: r["index"])]
            usage = data.get("usage", {})
            return EmbeddingResult(
                vectors=vectors,
                provider=self.name,
                model=data.get("model", model),
                dimensions=len(vectors[0]) if vectors else 0,
                prompt_tokens=usage.get("prompt_tokens", 0),
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(self.name, str(exc)) from exc

    def moderate(self, text: str, *, timeout_seconds: float) -> ModerationResult:
        if not self.is_configured():
            raise ProviderNotConfiguredError(self.name, "AI_OPENAI_API_KEY is not set")

        try:
            response = httpx.post(
                f"{_BASE_URL}/moderations",
                json={"input": text},
                headers=self._headers(),
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            result = response.json()["results"][0]
            flagged_categories = [k for k, v in result.get("categories", {}).items() if v]
            return ModerationResult(
                flagged=result.get("flagged", False), categories=flagged_categories, provider=self.name
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(self.name, str(exc)) from exc
