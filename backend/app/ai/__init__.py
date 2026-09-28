"""V20.1 — AI Infrastructure & LLM Framework.

This package is the reusable AI *foundation* layer for CareerOS: a
provider-agnostic abstraction over LLM vendors, plus the centralized
services (prompts, completions, embeddings, moderation, conversation
memory, token accounting) that any future AI feature builds on.

Deliberately out of scope here (see ROADMAP.md V20.2+): Resume AI,
Interview AI, Career Copilot, Learning AI, Job Recommendations. Those
are *consumers* of this layer, not part of it — nothing in this
package implements a specific career feature. The one pre-existing
exception is ``app.services.career_ai`` (V6), which predates this
layer and is left exactly as it was — it is not migrated onto this
framework in this pass, matching "do not rewrite" for anything outside
the stated objective.

Layout:
    providers/          Vendor adapters behind one common interface.
    provider_router.py  Picks a provider from config; handles fallback.
    token_counter.py     Prompt/completion token estimation.
    prompt_service.py   Versioned prompt template registry.
    context_builder.py  Assembles a token-budgeted message context.
    conversation_manager.py  Session/user memory, history, summaries.
    completion_service.py    High-level "generate text" entry point.
    embedding_service.py     High-level "embed text" entry point.
    moderation_service.py    Content moderation, provider or fallback.
    observability.py    Usage/latency/cost/health tracking + admin queries.

Every service here is fully optional at runtime: with no provider API
keys configured, the layer still starts, its APIs still respond, and
callers get clear "not configured" results instead of exceptions —
the same zero-config-by-default posture as V6 Career AI and V19.4
Notifications.
"""
