"""V22.4 — AI Context Builder.

Assembles exactly the information an AI call about one application is
allowed to see: the application's own public-ish facts, its
deterministic signals (app.applications.ai.signals — computed once,
never recomputed by the model), a short slice of recent timeline
activity, recent notes, and (for interview prep) the target interview
plus whatever resume/profile summary the candidate has already
authorized Career Copilot to use (app.career_copilot.context_engine —
reused, not duplicated).

NEVER included, by construction (nothing in this module even has a
handle on these): passwords, hashed credentials, JWT/session tokens,
other users' data, another application's data, or raw system/internal
identifiers beyond ``application_id`` itself (needed for the
candidate's own reference). ``user_id`` is used only to *query* data —
it is never written into prompt text.

Bounded: notes are capped in count and per-note length (cost control,
spec section 17); everything else is already small (a handful of
scalar fields per signal/interview/event).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.applications.ai.signals import ApplicationSignals
from app.career_copilot.system_prompt import wrap_untrusted
from app.models.domain import Application, ApplicationInterview, ApplicationNote

MAX_NOTES = 5
MAX_NOTE_CHARS = 500
MAX_TIMELINE_EVENTS = 8


@dataclass
class ApplicationAIContext:
    application: Application
    signals: ApplicationSignals
    recent_notes: list[str]


def _recent_notes(db: Session, application_id: int) -> list[str]:
    rows = db.scalars(
        select(ApplicationNote.content)
        .where(ApplicationNote.application_id == application_id)
        .order_by(ApplicationNote.created_at.desc())
        .limit(MAX_NOTES)
    ).all()
    return [(c or "")[:MAX_NOTE_CHARS] for c in rows]


def build(db: Session, application: Application, signals: ApplicationSignals) -> ApplicationAIContext:
    return ApplicationAIContext(application=application, signals=signals, recent_notes=_recent_notes(db, application.id))


def facts_block(ctx: ApplicationAIContext) -> str:
    """Plain-text KNOWN FACTS block — every AI module here builds its
    user_message around this, same convention as
    app.interview_ai.context_builder.facts_block."""
    a = ctx.application
    s = ctx.signals
    lines = [
        f"Company: {a.company}",
        f"Job title: {a.job_title}",
        f"Status: {s.status}",
        f"Days since last activity: {s.days_since_last_activity if s.days_since_last_activity is not None else 'unknown'}",
        f"Deadline: {a.deadline.isoformat() if a.deadline else 'none on file'}",
        f"Health: {s.health.label} ({s.health.score}/100)",
        f"Priority: {s.priority}",
        f"Next best action (already computed deterministically — explain it, don't contradict it): {s.next_action.action} — {s.next_action.reason}",
        f"Follow-up timing (already computed deterministically): {s.follow_up_timing} — {s.follow_up_reason}",
        f"Overdue tasks: {s.overdue_task_count}",
    ]
    if s.upcoming_interview:
        iv = s.upcoming_interview
        lines.append(
            f"Upcoming interview: {iv.round_name or iv.interview_type} on {iv.scheduled_at.isoformat() if iv.scheduled_at else 'unscheduled'}"
        )
    if s.risks:
        lines.append("Known risks: " + "; ".join(f"{r.risk} ({r.severity})" for r in s.risks))
    facts = "\n".join(lines)

    if ctx.recent_notes:
        notes_text = "\n---\n".join(ctx.recent_notes)
        facts += "\n\n" + wrap_untrusted("candidate's own notes on this application", notes_text)

    return facts


def interview_facts_block(interview: ApplicationInterview) -> str:
    lines = [
        f"Interview type: {interview.interview_type}",
        f"Round: {interview.round_name or interview.interview_type}",
        f"Scheduled: {interview.scheduled_at.isoformat() if interview.scheduled_at else 'not scheduled yet'}",
    ]
    if interview.notes:
        lines.append("")
        lines.append(wrap_untrusted("candidate's own notes on this interview", interview.notes[:800]))
    return "\n".join(lines)
