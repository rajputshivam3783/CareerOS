"""V22.4 — AI Application Intelligence & Follow-ups.

Adds an AI-assisted intelligence layer on top of the existing
Application/Timeline/Notes/Interview/Task/Document systems (V22.1-
V22.3) — nothing here duplicates or replaces them.

    signals.py         — deterministic engine (health score, priority,
                          next-best-action, follow-up timing, risks,
                          action plan). NO LLM CALL. Always available,
                          always explainable, always the same output
                          for the same input — see its own docstring
                          for "why deterministic" per the spec's
                          explicit "do not let an LLM arbitrarily
                          generate the numeric score" requirement.
    context.py          — builds the bounded, privacy-safe context an
                          AI call is allowed to see for one
                          application (never secrets, never another
                          user's data, never unnecessary internal ids).
    cache.py             — content-hash cache of generated AI output,
                          reusing the exact pattern app.resume_ai.cache
                          already established, just keyed by
                          application_id instead of user_id.
    narrative.py         — POST .../ai/analyze: AI explanation of the
                          deterministic signals in natural language.
    followup.py          — POST .../ai/follow-up: AI-drafted email
                          (subject + body), never sent automatically.
    interview_prep.py    — POST .../ai/interview-prep: AI-generated,
                          clearly-labeled preparation suggestions.

Every AI-calling module here follows the same three-part shape
app.interview_ai.evaluation_engine already established: a JSON-only
system prompt, a `_parse_and_validate` that refuses to trust an
unparseable/incomplete response, and a deterministic degraded-fallback
result on any failure — so a provider outage, timeout, or malformed
response degrades this feature, never the application workspace
itself (see app.ai.completion_service.CompletionError).
"""
