"""OpenRouter adapter — OpenRouter exposes an OpenAI-compatible chat
completions endpoint, so this only needs its own base URL/headers/key;
the request/response shape matches OpenAIProvider.
"""

from __future__ import annotations

import httpx

from app.ai.providers.base import ChatMessage, CompletionResult, LLMProvider, ProviderError, ProviderNotConfiguredError
from app.core.config import settings

_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(LLMProvider):
    name = "openrouter"

    def _api_key(self) -> str | None:
        return settings.ai_openrouter_api_key

    def is_configured(self) -> bool:
        return bool(self._api_key())

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
            raise ProviderNotConfiguredError(self.name, "AI_OPENROUTER_API_KEY is not set")

        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
            # Optional but recommended by OpenRouter for attributing traffic.
            "HTTP-Referer": "https://careeros.example",
            "X-Title": "CareerOS",
        }
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            response = httpx.post(f"{_BASE_URL}/chat/completions", json=payload, headers=headers, timeout=timeout_seconds)
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
