"""Chat turn orchestrator: context -> grounded prompt ->
``app.ai.completion_service`` (the V20.1 AI Gateway — never a provider
directly). This is the only module in ``career_copilot`` that makes an
AI call; everything else in the package is deterministic.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai import completion_service, conversation_manager
from app.career_copilot import context_engine, system_prompt
from app.models.domain import AIConversation, Job


class CopilotError(RuntimeError):
    """Raised when no AI provider can answer this turn — the API layer
    turns this into a clear error response (not a raw 500) so the
    frontend's "Error recovery" state has something specific to show,
    per the chat-experience requirement."""


def _public_job_or_none(db: Session, job_id: int | None) -> Job | None:
    if not job_id:
        return None
    job = db.get(Job, job_id)
    return job if job and job.status == "published" else None


def send_message(
    db: Session, conversation: AIConversation, user_message: str, *, user_id: int, job_id: int | None = None
) -> dict:
    context = context_engine.build(db, user_id)
    context_text = context_engine.to_prompt_text(context)

    referenced_job = _public_job_or_none(db, job_id)
    extra_blocks = []
    if referenced_job:
        job_facts = (
            f"Referenced job: id={referenced_job.id}, title={referenced_job.title}, "
            f"organization={referenced_job.organization}, job_type={referenced_job.job_type}, "
            f"location={referenced_job.location}, deadline={referenced_job.deadline}, "
            f"status={referenced_job.status}"
        )
        extra_blocks.append(job_facts)
        extra_blocks.append(
            system_prompt.wrap_untrusted(
                f"job #{referenced_job.id} description/qualification",
                f"Description: {referenced_job.description}\nQualification: {referenced_job.qualification}",
            )
        )

    full_system_prompt = system_prompt.SYSTEM_PROMPT + "\n\n" + context_text + (
        ("\n\n" + "\n".join(extra_blocks)) if extra_blocks else ""
    )

    history = conversation_manager.get_history(db, conversation.id)
    chat_history = conversation_manager.history_as_chat_messages(history)

    try:
        result = completion_service.generate(
            db,
            operation="career_copilot.chat",
            system_prompt=full_system_prompt,
            summary=conversation.summary,
            history=chat_history,
            user_message=user_message,
            user_id=user_id,
        )
    except completion_service.CompletionError as exc:
        raise CopilotError(str(exc)) from exc

    return {
        "text": result.text,
        "provider": result.provider,
        "model": result.model,
        "context_used": {
            "has_profile": context.profile is not None,
            "has_preferences": context.preferences is not None,
            "has_resume": context.resume_summary is not None,
            "saved_jobs_count": len(context.saved_jobs),
            "applications_count": len(context.applications),
            "referenced_job_id": referenced_job.id if referenced_job else None,
        },
    }
