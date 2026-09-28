"""Google Gemini completion provider using the native Gemini REST API."""

from __future__ import annotations

import httpx

from app.ai.providers.base import (
    ChatMessage,
    CompletionResult,
    LLMProvider,
    ProviderError,
    ProviderNotConfiguredError,
)
from app.core.config import settings

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(LLMProvider):
    name = "gemini"

    def _api_key(self) -> str | None:
        return settings.ai_gemini_api_key

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
        api_key = self._api_key()
        if not api_key:
            raise ProviderNotConfiguredError(self.name, "AI_GEMINI_API_KEY is not set")

        system_parts = [m.content for m in messages if m.role == "system"]
        contents = []
        for m in messages:
            if m.role == "system":
                continue
            contents.append({
                "role": "model" if m.role == "assistant" else "user",
                "parts": [{"text": m.content}],
            })

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}

        # Mock Interview and other structured callers can request JSON by
        # explicitly mentioning JSON in the prompt. Gemini's native API
        # supports application/json structured output.
        if any("valid JSON" in m.content or "ONLY a single valid JSON" in m.content for m in messages):
            payload["generationConfig"]["responseMimeType"] = "application/json"

        try:
            response = httpx.post(
                f"{_BASE_URL}/{model}:generateContent",
                headers={
                    "x-goog-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()

            candidates = data.get("candidates") or []
            if not candidates:
                reason = (data.get("promptFeedback") or {}).get("blockReason")
                detail = "Gemini returned no candidates"
                if reason:
                    detail += f" (blockReason={reason})"
                raise ProviderError(self.name, detail)

            candidate = candidates[0]
            parts = (candidate.get("content") or {}).get("parts") or []
            text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
            if not text.strip():
                reason = candidate.get("finishReason")
                detail = "Gemini returned an empty response"
                if reason:
                    detail += f" (finishReason={reason})"
                raise ProviderError(self.name, detail)

            usage = data.get("usageMetadata") or {}
            return CompletionResult(
                text=text,
                provider=self.name,
                model=model,
                prompt_tokens=usage.get("promptTokenCount", 0),
                completion_tokens=usage.get("candidatesTokenCount", 0),
                finish_reason=candidate.get("finishReason"),
                raw={},
            )
        except ProviderError:
            raise
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json()
            except Exception:
                detail = exc.response.text
            raise ProviderError(
                self.name,
                f"Gemini API HTTP {exc.response.status_code}: {detail}",
            ) from exc
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise ProviderError(self.name, f"Gemini network error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(self.name, str(exc)) from exc
