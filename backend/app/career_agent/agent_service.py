"""V25.4 — Career Agent turn orchestrator (spec section 2).

One call, ``handle_message``, walks the full controlled pipeline for
one user message:

    UNDERSTANDING (build context + detect intent)
      -> PLANNING (validate tool + params)
        -> EXECUTING (READ tools only) -> COMPLETED / FAILED
        -> WAITING_FOR_CONFIRMATION (WRITE/HIGH_RISK) — a later,
           separate call to ``confirm_pending_action`` is what moves
           this to EXECUTING -> COMPLETED/FAILED; this function never
           executes a write/high-risk tool itself.

Every transition goes through ``state_machine.assert_transition`` so
an attempt to skip confirmation for a write tool raises rather than
silently executing — this is enforced in code, not only by convention.

AI cost control (spec section 25): at most one AI Gateway call is made
per user message for intent detection (skipped entirely when
``intent.fast_path`` matches) and at most one more to narrate a result
or answer a grounded general question — never more than two, and never
one per tool "iteration" because a turn only ever selects one tool.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai import completion_service
from app.career_agent import actions, conversation_store, intent, system_prompt, tool_registry
from app.career_agent.state_machine import AgentState, NEXT_STATE_AFTER_PLANNING, assert_transition
from app.career_copilot import context_engine
from app.models.domain import CareerAgentConversation, User


class AgentError(RuntimeError):
    pass


def _confirmation_prompt(tool_name: str, params: dict, action_id: int) -> str:
    """Deterministic, template-based confirmation copy — never
    AI-generated, so a candidate is never shown confirmation wording
    the model invented (spec section 18's "I found 3 matching jobs.
    Would you like me to save them?" example is exactly this kind of
    fixed template)."""

    readable = ", ".join(f"{k}={v}" for k, v in params.items()) or "no additional details"
    templates = {
        "create_application_task": f"I can create the task \"{params.get('title', '')}\" on this application.",
        "schedule_follow_up": f"I can create a follow-up reminder in {params.get('follow_up_in_days', 5)} day(s).",
        "submit_application": "I can prepare the official application link for this job — I will not submit it for you.",
        "draft_followup_message": "I can draft a follow-up message for this application — I will not send it for you.",
    }
    base = templates.get(tool_name, f"I can run \"{tool_name}\" with {readable}.")
    return f"{base} Would you like me to proceed? (reply 'yes' to confirm action #{action_id}, or 'no' to cancel)"


def _grounded_context_text(db: Session, user: User) -> tuple[str, dict]:
    context = context_engine.build(db, user.id)
    return context_engine.to_prompt_text(context), {
        "has_profile": context.profile is not None,
        "applications_count": len(context.applications),
        "saved_jobs_count": len(context.saved_jobs),
    }


def _narrate(db: Session, user: User, user_message: str, context_text: str, *, tool_name: str | None, tool_result: dict | None) -> str:
    extra = ""
    if tool_name and tool_result is not None:
        extra = "\n\n" + system_prompt.wrap_tool_result(tool_name, tool_result)
    full_prompt = system_prompt.RESPONSE_SYSTEM_PROMPT + "\n\n" + context_text + extra
    try:
        result = completion_service.generate(
            db, operation="career_agent.chat", system_prompt=full_prompt, user_message=user_message, user_id=user.id,
        )
    except completion_service.CompletionError as exc:
        raise AgentError("Career Agent is currently unavailable. Please try again shortly.") from exc
    return result.text, result.provider, result.model


def handle_message(db: Session, user: User, conversation: CareerAgentConversation, user_message: str) -> dict:
    conversation_store.add_message(db, conversation, role="user", content=user_message)

    state = AgentState.IDLE
    assert_transition(state, AgentState.UNDERSTANDING)
    state = AgentState.UNDERSTANDING

    context_text, context_meta = _grounded_context_text(db, user)
    detected = intent.detect(db, user, user_message)

    if detected.tool_name is None:
        # No tool matched — either a clarifying question (deterministic,
        # from intent.py) or a general grounded chat answer.
        if detected.clarify:
            assert_transition(state, AgentState.COMPLETED)
            reply = detected.clarify
            provider = model = None
        else:
            try:
                reply, provider, model = _narrate(
                    db, user, user_message, context_text, tool_name=None, tool_result=None
                )
            except AgentError as exc:
                assert_transition(state, AgentState.FAILED)
                conversation_store.add_message(db, conversation, role="assistant", content=str(exc))
                return {"reply": str(exc), "state": AgentState.FAILED, "action": None}
            assert_transition(state, AgentState.COMPLETED)
        state = AgentState.COMPLETED
        message = conversation_store.add_message(
            db, conversation, role="assistant", content=reply, provider=provider, model=model,
            metadata={"state": state, "tool": None},
        )
        return {"reply": reply, "state": state, "action": None, "message_id": message.id}

    # A tool was selected — validate + classify risk before anything runs.
    spec = tool_registry.get_tool(detected.tool_name)
    if spec is None:  # defensive — intent.py already filters unknown tools
        raise AgentError("Selected tool is not registered")

    assert_transition(state, AgentState.PLANNING)
    state = AgentState.PLANNING
    next_state = NEXT_STATE_AFTER_PLANNING[spec.risk]
    assert_transition(state, next_state)

    if next_state == AgentState.EXECUTING:
        action = actions.run_action_now(
            db, user, conversation_id=conversation.id, tool_name=spec.name, params=detected.params
        )
        if action.status == "COMPLETED":
            import json as _json

            tool_result = _json.loads(action.result_json)
            try:
                reply, provider, model = _narrate(
                    db, user, user_message, context_text, tool_name=spec.name, tool_result=tool_result
                )
            except AgentError as exc:
                reply, provider, model = str(exc), None, None
            final_state = AgentState.COMPLETED
        else:
            reply = f"I couldn't complete that: {action.error or 'an unexpected error occurred.'}"
            provider = model = None
            final_state = AgentState.FAILED
        message = conversation_store.add_message(
            db, conversation, role="assistant", content=reply, provider=provider, model=model,
            metadata={"state": final_state, "tool": spec.name, "action_id": action.id, "risk": spec.risk},
        )
        return {
            "reply": reply, "state": final_state, "action": actions.action_out(action), "message_id": message.id,
        }

    # WRITE / HIGH_RISK — create the pending action, ask for confirmation, execute nothing.
    action = actions.create_action(
        db, user, conversation_id=conversation.id, tool_name=spec.name, params=detected.params, risk=spec.risk,
        status="PENDING_CONFIRMATION",
    )
    reply = _confirmation_prompt(spec.name, detected.params, action.id)
    message = conversation_store.add_message(
        db, conversation, role="assistant", content=reply,
        metadata={"state": AgentState.WAITING_FOR_CONFIRMATION, "tool": spec.name, "action_id": action.id, "risk": spec.risk},
    )
    return {
        "reply": reply, "state": AgentState.WAITING_FOR_CONFIRMATION, "action": actions.action_out(action),
        "message_id": message.id,
    }


def _completed_reply(action) -> str:
    """Accurate wording for a completed action.

    V25.6: HIGH_RISK tools here (submit_application, draft_followup_message) only PREPARE a
    link or a draft - their result carries ``submitted: False`` / ``sent: False``. The
    previous generic "Done - that's been completed" implied an external action had
    happened. Never claim an external effect that the tool result does not confirm."""
    import json as _json

    try:
        result = _json.loads(action.result_json) if action.result_json else {}
    except ValueError:
        result = {}
    if isinstance(result, dict) and (result.get("submitted") is False or result.get("sent") is False):
        return (
            "I've prepared that for you, but nothing has been submitted or sent on your behalf. "
            "Please use the link or draft shown to complete it yourself."
        )
    return "Done — that's been completed."


def confirm_pending_action(db: Session, user: User, conversation: CareerAgentConversation | None, action_id: int) -> dict:
    action = actions.confirm_action(db, user, action_id)
    if conversation is not None:
        if action.status == "COMPLETED":
            reply = _completed_reply(action)
        elif action.status == "REJECTED":
            reply = "Okay, I won't do that."
        else:
            reply = f"I couldn't complete that: {action.error or 'an unexpected error occurred.'}"
        conversation_store.add_message(
            db, conversation, role="assistant", content=reply,
            metadata={"state": action.status, "tool": action.action_type, "action_id": action.id},
        )
    return actions.action_out(action)


def reject_pending_action(db: Session, user: User, conversation: CareerAgentConversation | None, action_id: int) -> dict:
    action = actions.reject_action(db, user, action_id)
    if conversation is not None:
        conversation_store.add_message(
            db, conversation, role="assistant", content="Okay, I won't do that.",
            metadata={"state": action.status, "tool": action.action_type, "action_id": action.id},
        )
    return actions.action_out(action)
