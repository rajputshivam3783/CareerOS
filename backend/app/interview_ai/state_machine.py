"""V20.4 — Interview status state machine.

The one and only place `MockInterviewSession.status` is allowed to
change. Every transition is looked up in `_TRANSITIONS`, a plain dict
— there is no branching logic, no AI, no hidden state, so this module
is trivially unit-testable and its behavior is fully determined by its
input (current status + requested action). API code must call
`transition()` rather than setting `.status` directly; nothing else in
this package imports `MockInterviewSession.status = ...`.
"""

from __future__ import annotations

from datetime import datetime

from app.models.domain import MockInterviewSession

STATUSES = {"draft", "ready", "in_progress", "paused", "completed", "cancelled"}

# (current_status, action) -> next_status. Anything not listed here is
# an illegal transition and raises IllegalTransitionError — e.g. you
# cannot "pause" a "draft" session, or "resume" a "completed" one.
_TRANSITIONS: dict[tuple[str, str], str] = {
    ("draft", "mark_ready"): "ready",
    ("ready", "start"): "in_progress",
    ("in_progress", "pause"): "paused",
    ("paused", "resume"): "in_progress",
    ("in_progress", "complete"): "completed",
    ("draft", "cancel"): "cancelled",
    ("ready", "cancel"): "cancelled",
    ("in_progress", "cancel"): "cancelled",
    ("paused", "cancel"): "cancelled",
}


def _bump_paused_seconds(session, seconds: int) -> None:
    session.total_paused_seconds = (session.total_paused_seconds or 0) + seconds


class IllegalTransitionError(ValueError):
    def __init__(self, current_status: str, action: str):
        super().__init__(f"Cannot {action!r} a session in status {current_status!r}")
        self.current_status = current_status
        self.action = action


def transition(session: MockInterviewSession, action: str) -> MockInterviewSession:
    """Mutates `session.status` (and the matching timestamp field) in
    place per `_TRANSITIONS`. Does not commit — callers own the
    transaction, same as every other write in this codebase."""
    key = (session.status, action)
    if key not in _TRANSITIONS:
        raise IllegalTransitionError(session.status, action)

    session.status = _TRANSITIONS[key]
    now = datetime.utcnow()

    if action == "start":
        session.started_at = now
    elif action == "pause":
        session.paused_at = now
    elif action == "resume" and session.paused_at:
        _bump_paused_seconds(session, int((now - session.paused_at).total_seconds()))
        session.paused_at = None
    elif action == "complete":
        session.completed_at = now
    return session


def can(session: MockInterviewSession, action: str) -> bool:
    return (session.status, action) in _TRANSITIONS


def restart_config(session: MockInterviewSession) -> dict:
    """Not a transition on `session` itself — "Restart" means creating
    a *new* draft session with the same configuration (see
    app.api.interview_ai's restart endpoint), so an in-progress
    session's own history is never mutated or lost. Returns the
    field values a fresh MockInterviewSession should be created with."""
    return {
        "user_id": session.user_id,
        "job_id": session.job_id,
        "interview_type": session.interview_type,
        "target_role": session.target_role,
        "experience_level": session.experience_level,
        "difficulty": session.difficulty,
        "duration_minutes": session.duration_minutes,
        "planned_question_count": session.planned_question_count,
        "focus_skills": session.focus_skills,
        "programming_language": session.programming_language,
        "current_difficulty": session.difficulty,
    }
