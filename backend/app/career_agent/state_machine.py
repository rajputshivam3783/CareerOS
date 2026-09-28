"""V25.4 — Agent state machine (spec section 26).

A plain enum plus a transition table — no behavior lives here. Every
state change in agent_service.py / actions.py goes through
``assert_transition`` so an illegal jump (e.g. straight from
UNDERSTANDING to EXECUTING for a write tool, skipping confirmation) is
a caught programming error in tests rather than a silent capability
that lets a high-risk action run unconfirmed.
"""

from __future__ import annotations


class AgentState:
    IDLE = "IDLE"
    UNDERSTANDING = "UNDERSTANDING"
    PLANNING = "PLANNING"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


ALL_STATES = frozenset(
    {
        AgentState.IDLE,
        AgentState.UNDERSTANDING,
        AgentState.PLANNING,
        AgentState.WAITING_FOR_CONFIRMATION,
        AgentState.EXECUTING,
        AgentState.COMPLETED,
        AgentState.FAILED,
    }
)

# Legal (from -> {to, ...}) transitions. A READ tool goes
# IDLE -> UNDERSTANDING -> PLANNING -> EXECUTING -> COMPLETED. A WRITE
# or HIGH_RISK tool goes ... -> PLANNING -> WAITING_FOR_CONFIRMATION,
# then (only on explicit user confirmation, in a later request)
# WAITING_FOR_CONFIRMATION -> EXECUTING -> COMPLETED, or
# WAITING_FOR_CONFIRMATION -> FAILED on rejection/expiry. Any state may
# fail.
_TRANSITIONS: dict[str, frozenset[str]] = {
    AgentState.IDLE: frozenset({AgentState.UNDERSTANDING}),
    AgentState.UNDERSTANDING: frozenset({AgentState.PLANNING, AgentState.COMPLETED, AgentState.FAILED}),
    AgentState.PLANNING: frozenset(
        {AgentState.EXECUTING, AgentState.WAITING_FOR_CONFIRMATION, AgentState.COMPLETED, AgentState.FAILED}
    ),
    AgentState.WAITING_FOR_CONFIRMATION: frozenset(
        {AgentState.EXECUTING, AgentState.FAILED, AgentState.WAITING_FOR_CONFIRMATION}
    ),
    AgentState.EXECUTING: frozenset({AgentState.COMPLETED, AgentState.FAILED}),
    AgentState.COMPLETED: frozenset(),
    AgentState.FAILED: frozenset(),
}


class IllegalTransitionError(RuntimeError):
    pass


def assert_transition(from_state: str, to_state: str) -> None:
    if from_state not in ALL_STATES:
        raise IllegalTransitionError(f"Unknown state: {from_state!r}")
    if to_state not in ALL_STATES:
        raise IllegalTransitionError(f"Unknown state: {to_state!r}")
    if to_state not in _TRANSITIONS[from_state]:
        raise IllegalTransitionError(f"Illegal transition: {from_state} -> {to_state}")


# Risk level -> the state a successfully-planned tool call moves to
# next. This is what forces every WRITE/HIGH_RISK tool through
# confirmation regardless of what the LLM's own output claims (spec
# section 18: "Do not interpret vague responses as confirmation").
NEXT_STATE_AFTER_PLANNING = {
    "READ": AgentState.EXECUTING,
    "WRITE": AgentState.WAITING_FOR_CONFIRMATION,
    "HIGH_RISK": AgentState.WAITING_FOR_CONFIRMATION,
}
