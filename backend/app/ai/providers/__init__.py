"""Vendor adapters. Import ``PROVIDERS`` rather than an individual
adapter class in almost all cases — see app.ai.provider_router."""

from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.ibm_watsonx_provider import (
    IBMWatsonXProvider,
)
from app.ai.providers.base import (
    ChatMessage,
    CompletionResult,
    EmbeddingResult,
    LLMProvider,
    ModerationResult,
    ProviderError,
    ProviderNotConfiguredError,
    StubProvider,
)
from app.ai.providers.gemini_provider import GeminiProvider
from app.ai.providers.openai_provider import OpenAIProvider
from app.ai.providers.openrouter_provider import OpenRouterProvider

#: Every provider CareerOS knows about, keyed by the identifier used in
#: config (AI_DEFAULT_PROVIDER=...) and API responses. "local" / "ollama"
#: / "azure_openai" are registered as stubs per ROADMAP.md so provider
#: selection/admin status already account for them ahead of a real
#: integration landing in a later version.
PROVIDERS: dict[str, LLMProvider] = {
    "anthropic": AnthropicProvider(),
    "openai": OpenAIProvider(),
    "gemini": GeminiProvider(),
    "openrouter": OpenRouterProvider(),
    "ibm": IBMWatsonXProvider(),
    "local": StubProvider("local"),
    "ollama": StubProvider("ollama"),
    "azure_openai": StubProvider("azure_openai"),
}

__all__ = [
    "PROVIDERS",
    "LLMProvider",
    "ChatMessage",
    "CompletionResult",
    "EmbeddingResult",
    "ModerationResult",
    "ProviderError",
    "ProviderNotConfiguredError",
]
