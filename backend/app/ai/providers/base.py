"""Common interface every LLM provider adapter implements.

Nothing in ``app.ai`` (or any future feature built on it) should ever
import a vendor SDK or call a vendor URL directly — every provider
speaks through this interface, so swapping OpenAI for Gemini for a
local model is a config change (``AI_DEFAULT_PROVIDER``), never a
call-site change. See LLM_PROVIDER_GUIDE.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ChatMessage:
    """One turn in a conversation. ``role`` is "system", "user", or
    "assistant" — the three roles every provider's chat API accepts in
    some form; adapters translate this into their own wire shape."""

    role: str
    content: str


@dataclass
class CompletionResult:
    text: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    provider: str
    model: str
    dimensions: int
    prompt_tokens: int = 0


@dataclass
class ModerationResult:
    flagged: bool
    categories: list[str]
    provider: str
    raw: dict = field(default_factory=dict)


class ProviderError(RuntimeError):
    """Raised by an adapter on a request failure (timeout, HTTP error,
    malformed response, ...). ``provider_router`` catches this to
    decide whether to fall back to a secondary provider."""

    def __init__(self, provider: str, message: str):
        super().__init__(f"[{provider}] {message}")
        self.provider = provider


class ProviderNotConfiguredError(ProviderError):
    """Raised when a provider is selected but has no API key/credentials
    set. Distinct from ProviderError so callers (and the admin health
    view) can tell "misconfigured" apart from "configured but failing"."""


class LLMProvider(ABC):
    """Base class for a single vendor adapter.

    Subclasses implement only what they support — ``embed`` and
    ``moderate`` may raise ``NotImplementedError`` for a
    completions-only provider (mirrors the "not_implemented" status
    convention already used by ``app.services.notification_channels``
    for channels without a real backend yet).
    """

    #: Short, stable identifier used in config, logs, and API responses.
    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether this provider has the credentials it needs to run."""

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_seconds: float,
    ) -> CompletionResult:
        raise NotImplementedError(f"{self.name} does not support completions")

    def embed(self, texts: list[str], *, model: str, timeout_seconds: float) -> EmbeddingResult:
        raise NotImplementedError(f"{self.name} does not support embeddings")

    def moderate(self, text: str, *, timeout_seconds: float) -> ModerationResult:
        raise NotImplementedError(f"{self.name} does not support moderation")

    def supports(self, capability: str) -> bool:
        """capability in {"complete", "embed", "moderate"}."""
        method = getattr(self, capability, None)
        if method is None:
            return False
        # A base-class method that only raises NotImplementedError is
        # not an override, so treat that as "unsupported" without
        # actually invoking it.
        return getattr(type(self), capability) is not getattr(LLMProvider, capability)


class StubProvider(LLMProvider):
    """Placeholder adapter for providers on the roadmap but not yet
    backed by a real integration (Local LLM, Ollama, Azure OpenAI —
    see LLM_PROVIDER_GUIDE.md "Future providers"). Registered in the
    router today so provider selection/config validation already know
    about them; calling one raises a clear, typed error rather than a
    generic 500 or a silent no-op.
    """

    def __init__(self, name: str):
        self.name = name

    def is_configured(self) -> bool:
        return False

    def complete(self, messages, *, model, temperature, max_tokens, timeout_seconds):
        raise ProviderNotConfiguredError(self.name, "not yet implemented — reserved for a future release")

    def embed(self, texts, *, model, timeout_seconds):
        raise ProviderNotConfiguredError(self.name, "not yet implemented — reserved for a future release")

    def moderate(self, text, *, timeout_seconds):
        raise ProviderNotConfiguredError(self.name, "not yet implemented — reserved for a future release")
