"""Anthropic adapter — uses the ``anthropic`` SDK already vendored for
V6 Career AI (see app/services/career_ai.py). Imported lazily inside
each method, same as career_ai.py does, so a deployment that never
configures this provider never pays the import cost and the package
stays optional at runtime.
"""

from __future__ import annotations

from app.ai.providers.base import (
    ChatMessage,
    CompletionResult,
    LLMProvider,
    ModerationResult,
    ProviderError,
    ProviderNotConfiguredError,
)
from app.core.config import settings


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def _api_key(self) -> str | None:
        # Falls back to the V6 Career AI key so a deployment that
        # already configured that feature doesn't need to set the
        # same Anthropic key twice under a new name.
        return settings.ai_anthropic_api_key or settings.career_ai_anthropic_api_key

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
            raise ProviderNotConfiguredError(self.name, "AI_ANTHROPIC_API_KEY is not set")

        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds)
            system = "\n".join(m.content for m in messages if m.role == "system") or None
            turns = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
            response = client.messages.create(
                model=model,
                system=system,
                messages=turns,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
            usage = response.usage
            return CompletionResult(
                text=text,
                provider=self.name,
                model=model,
                prompt_tokens=getattr(usage, "input_tokens", 0) or 0,
                completion_tokens=getattr(usage, "output_tokens", 0) or 0,
                finish_reason=response.stop_reason,
                raw={"id": response.id},
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — normalize every SDK failure to ProviderError
            raise ProviderError(self.name, str(exc)) from exc

    def moderate(self, text: str, *, timeout_seconds: float) -> ModerationResult:
        # Anthropic has no dedicated moderation endpoint; a fast,
        # cheap completion call classifies instead. Callers that want
        # a real moderation-purpose API should configure OpenAI as
        # the moderation provider (see AI_CONFIGURATION.md).
        result = self.complete(
            [
                ChatMessage(
                    role="system",
                    content=(
                        "Classify the user text for policy violations (violence, hate, "
                        "self-harm, sexual content involving minors, weapons). Respond with "
                        "exactly one word: SAFE or FLAGGED."
                    ),
                ),
                ChatMessage(role="user", content=text[:4000]),
            ],
            model=settings.ai_anthropic_model,
            temperature=0,
            max_tokens=5,
            timeout_seconds=timeout_seconds,
        )
        flagged = "FLAGGED" in result.text.upper()
        return ModerationResult(flagged=flagged, categories=["flagged"] if flagged else [], provider=self.name)
