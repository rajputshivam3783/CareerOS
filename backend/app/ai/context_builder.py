"""Assembles a token-budgeted list of ChatMessage turns for a
completion call: an optional system prompt, a conversation summary (if
one exists, standing in for turns that were trimmed), and as much
recent history as fits under the budget.

Kept deliberately separate from ConversationManager: this module has
no DB dependency and only knows about in-memory message lists, so it's
directly unit-testable and reusable by a caller that isn't using
AIConversation/AIMessage persistence at all (e.g. a one-off completion
with a hand-built history).
"""

from __future__ import annotations

from app.ai.providers.base import ChatMessage
from app.ai.token_counter import estimate_tokens


def build_context(
    *,
    system_prompt: str | None,
    summary: str | None,
    history: list[ChatMessage],
    new_user_message: str,
    max_context_tokens: int,
) -> list[ChatMessage]:
    """Returns messages ordered [system?, summary-as-system?, ...history
    (newest-fitting), user]. History is walked newest-first and kept
    while it fits the budget, then re-reversed to chronological order
    — so a long thread degrades to "most recent turns" rather than
    being cut off mid-budget from the start.
    """
    reserved = estimate_tokens(new_user_message) + 4
    if system_prompt:
        reserved += estimate_tokens(system_prompt) + 4
    if summary:
        reserved += estimate_tokens(summary) + 4

    budget = max(0, max_context_tokens - reserved)
    kept: list[ChatMessage] = []
    used = 0
    for message in reversed(history):
        cost = estimate_tokens(message.content) + 4
        if used + cost > budget:
            break
        kept.append(message)
        used += cost
    kept.reverse()

    messages: list[ChatMessage] = []
    if system_prompt:
        messages.append(ChatMessage(role="system", content=system_prompt))
    if summary:
        messages.append(ChatMessage(role="system", content=f"Earlier conversation summary: {summary}"))
    messages.extend(kept)
    messages.append(ChatMessage(role="user", content=new_user_message))
    return messages
