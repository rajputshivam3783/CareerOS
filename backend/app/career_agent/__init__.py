"""V25.4 — Advanced AI Career Agent & Automation.

A candidate-facing, user-controlled AI agent that sits on top of every
prior CareerOS system (V20 AI, V21 Search & Recommendations, V22
Application Tracking, V23 Communication & Notifications, V24 Recruiter
Intelligence — read-only from here, V25.1 Multi-Tenancy, V25.2 Platform
Governance, V25.3 Data Intelligence) without rewriting or duplicating
any of them.

Hard architectural rule (spec section 2): the LLM never talks to the
database. Every turn goes

    user message -> intent detection -> permission check -> tool
    selection -> existing CareerOS service -> structured result ->
    AI narrates the result -> (write/high-risk only) confirmation ->
    action

`intent.py` asks the model to choose *at most one* tool from a fixed,
whitelisted registry and to supply parameters for it; the model never
receives or produces SQL, and any parameter it proposes is validated
against that tool's schema before a single service function is called.
A turn executes at most one tool call — this version does not attempt
multi-step autonomous tool chains (see state_machine.py) — which is
what makes "must not repeatedly call the same tool indefinitely" and
"reasonable maximum tool iterations" (spec section 28) trivially true
by construction rather than by a runtime counter that could be wrong.

Layout:
    state_machine.py     The controlled agent states (IDLE ->
                          UNDERSTANDING -> PLANNING ->
                          WAITING_FOR_CONFIRMATION -> EXECUTING ->
                          COMPLETED/FAILED) and their legal transitions.
    permissions.py        Per-tool role/permission requirements and
                          READ/WRITE/HIGH_RISK risk classification —
                          the single source of truth for "can this
                          actor call this tool," checked on every call,
                          never trusted from the LLM.
    tool_registry.py      The whitelist of agent tools: name, risk
                          level, parameter schema, and handler. Nothing
                          the model proposes reaches a service function
                          unless it is a tool in this registry.
    tools.py               Handlers themselves — each one thin, each
                          one calling an existing V20-V25.3 service
                          function and returning a plain dict. No tool
                          here re-implements search, ranking, matching,
                          skill-gap, or eligibility logic.
    intent.py              Deterministic fast-path matching for common
                          phrasings, falling back to one structured
                          (JSON-only) AI call that must name a tool
                          from the registry or ask a clarifying
                          question — never free-form SQL or code.
    conversation_store.py CRUD for CareerAgentConversation/Message —
                          user-scoped throughout (spec section 15/34).
    actions.py              Lifecycle for CareerAgentAction: create
                          pending, confirm (execute), reject. Confirmed
                          actions are executed exactly once (idempotent
                          confirm — re-confirming an already-COMPLETED
                          action is a no-op, not a re-execution).
    agent_service.py       Orchestrates one chat turn end to end using
                          all of the above.
    preferences.py          CRUD for CareerAgentPreference (proactive
                          notification settings — distinct from the
                          existing CareerPreference career-goals row,
                          reused as-is for career data).
    brief.py                Deterministic "Career Brief" composition
                          (spec section 22) — no AI call.
    proactive.py            Deterministic proactive-notification
                          triggers on top of V23's notification
                          infrastructure, respecting quiet
                          hours/frequency/opt-out.
    system_prompt.py        The agent's grounding + safety system
                          prompt, reusing (not duplicating)
                          app.career_copilot.system_prompt's untrusted-
                          content wrapper.

Out of scope for this pass, per the brief: V25.5, any rewrite of
V20-V25.3, and any second recommendation/matching/eligibility engine.
See docs/V25_4_AI_CAREER_AGENT.md for the full design writeup.
"""
