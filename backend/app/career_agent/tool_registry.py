"""V25.4 — Tool registry (spec sections 3, 4, 17).

This is the whitelist: the only tools the Career Agent may ever call,
each with its risk classification and the parameter names/types it
accepts. ``intent.py`` may only ever propose a ``tool`` name that is a
key in ``TOOLS`` and ``params`` whose keys are a subset of that tool's
``params`` — anything else (an unknown tool name, an unexpected
parameter, a parameter of the wrong type) is rejected by
``validate_call`` before ``tools.py`` is ever invoked. This is what
"never trust tool parameters from the LLM without backend validation"
(spec section 17) means concretely.

Risk levels (spec section 4):
    READ        Executes automatically once selected — no candidate
                data is changed.
    WRITE       Requires confirmation before it runs.
    HIGH_RISK   Requires confirmation immediately before execution,
                and additionally never claims an external effect
                (a submission, a sent message) that didn't happen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.career_agent import tools

READ = "READ"
WRITE = "WRITE"
HIGH_RISK = "HIGH_RISK"


@dataclass(frozen=True)
class ToolParam:
    name: str
    type: type
    required: bool = False


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk: str
    handler: Callable
    params: tuple[ToolParam, ...] = field(default_factory=tuple)

    def param_names(self) -> set[str]:
        return {p.name for p in self.params}

    def required_param_names(self) -> set[str]:
        return {p.name for p in self.params if p.required}


TOOLS: dict[str, ToolSpec] = {
    "search_jobs": ToolSpec(
        "search_jobs", "Search published jobs/government recruitment/internships by role, skills, location.", READ,
        tools.search_jobs,
        (
            ToolParam("query", str), ToolParam("location", str), ToolParam("job_type", str),
            ToolParam("work_mode", str), ToolParam("skills", list), ToolParam("experience", str),
            ToolParam("limit", int),
        ),
    ),
    "get_job_details": ToolSpec(
        "get_job_details", "Get full details for one published job by id.", READ,
        tools.get_job_details, (ToolParam("job_id", int, required=True),),
    ),
    "get_job_recommendations": ToolSpec(
        "get_job_recommendations", "Get the candidate's personalized job recommendations (V21 engine).", READ,
        tools.get_job_recommendations, (ToolParam("limit", int), ToolParam("category", str)),
    ),
    "analyze_skill_gap": ToolSpec(
        "analyze_skill_gap", "Compute the candidate's unified skill gap, optionally against one target job.", READ,
        tools.analyze_skill_gap, (ToolParam("target_job_id", int),),
    ),
    "get_career_intelligence": ToolSpec(
        "get_career_intelligence", "Career overview: profile completeness, skills, activity, target role (V25.3).", READ,
        tools.get_career_intelligence, (ToolParam("target_role", str),),
    ),
    "get_application": ToolSpec(
        "get_application", "Get one of the candidate's own tracked applications by id.", READ,
        tools.get_application, (ToolParam("application_id", int, required=True),),
    ),
    "list_applications": ToolSpec(
        "list_applications", "List the candidate's own tracked applications, optionally filtered by status.", READ,
        tools.list_applications, (ToolParam("status", str), ToolParam("limit", int)),
    ),
    "get_application_timeline": ToolSpec(
        "get_application_timeline", "Get the status/event timeline for one of the candidate's own applications.", READ,
        tools.get_application_timeline, (ToolParam("application_id", int, required=True),),
    ),
    "create_application_task": ToolSpec(
        "create_application_task", "Create a task/reminder on one of the candidate's own applications.", WRITE,
        tools.create_application_task,
        (
            ToolParam("application_id", int, required=True), ToolParam("title", str, required=True),
            ToolParam("description", str), ToolParam("due_in_days", int),
        ),
    ),
    "schedule_follow_up": ToolSpec(
        "schedule_follow_up", "Create a follow-up reminder task N days from now on an application.", WRITE,
        tools.schedule_follow_up, (ToolParam("application_id", int, required=True), ToolParam("follow_up_in_days", int)),
    ),
    "prepare_interview": ToolSpec(
        "prepare_interview", "Generate interview preparation for an upcoming/specified interview on an application.", READ,
        tools.prepare_interview, (ToolParam("application_id", int, required=True), ToolParam("interview_id", int)),
    ),
    "analyze_resume": ToolSpec(
        "analyze_resume", "Analyze the candidate's own uploaded resume (scores, missing sections, suggestions).", READ,
        tools.analyze_resume, (ToolParam("refresh", bool),),
    ),
    "get_learning_recommendations": ToolSpec(
        "get_learning_recommendations", "Build a learning path from the candidate's current skill gap.", READ,
        tools.get_learning_recommendations, (ToolParam("target_job_id", int),),
    ),
    "get_saved_jobs": ToolSpec(
        "get_saved_jobs", "List the candidate's saved jobs.", READ,
        tools.get_saved_jobs, (ToolParam("limit", int),),
    ),
    "get_notifications": ToolSpec(
        "get_notifications", "List the candidate's own notifications.", READ,
        tools.get_notifications, (ToolParam("unread_only", bool), ToolParam("limit", int)),
    ),
    "summarize_career_progress": ToolSpec(
        "summarize_career_progress", "Deterministic summary of applications, deadlines, skills, and readiness.", READ,
        tools.summarize_career_progress, (),
    ),
    "submit_application": ToolSpec(
        "submit_application",
        "Prepare the external application link for a job. Never actually submits anything — CareerOS has no "
        "submission integration; this only surfaces the official apply link.",
        HIGH_RISK, tools.submit_application, (ToolParam("job_id", int, required=True),),
    ),
    "draft_followup_message": ToolSpec(
        "draft_followup_message",
        "Draft a follow-up message for the hiring team. Never sends anything — CareerOS has no connected send "
        "channel; this only returns a draft for the candidate to send themselves.",
        HIGH_RISK, tools.draft_followup_message, (ToolParam("application_id", int, required=True), ToolParam("tone", str)),
    ),
}


class ToolValidationError(ValueError):
    pass


def get_tool(name: str) -> ToolSpec | None:
    return TOOLS.get(name)


def list_tools_for_candidate() -> list[dict]:
    """Every tool here is candidate-safe by construction — see
    app.career_agent.permissions.FORBIDDEN_TOOL_KEYWORDS and its
    matching test. No role branching happens here because this
    registry has nothing else to branch away from."""

    return [{"name": t.name, "description": t.description, "risk": t.risk} for t in TOOLS.values()]


def validate_call(tool_name: str, raw_params: dict) -> dict:
    """Whitelists ``raw_params`` down to exactly this tool's declared
    parameters, checks required ones are present, and loosely coerces
    type (int/str/bool/list) — never evaluates, executes, or otherwise
    interprets a parameter value as code or a query fragment. Raises
    ToolValidationError on anything that doesn't fit; callers must not
    fall back to passing the raw params through on error."""

    spec = get_tool(tool_name)
    if spec is None:
        raise ToolValidationError(f"Unknown tool: {tool_name!r}")

    allowed = spec.param_names()
    unknown = set(raw_params) - allowed
    if unknown:
        raise ToolValidationError(f"Unexpected parameter(s) for {tool_name!r}: {sorted(unknown)}")

    missing = spec.required_param_names() - set(k for k, v in raw_params.items() if v is not None)
    if missing:
        raise ToolValidationError(f"Missing required parameter(s) for {tool_name!r}: {sorted(missing)}")

    cleaned: dict = {}
    by_name = {p.name: p for p in spec.params}
    for key, value in raw_params.items():
        if value is None:
            continue
        expected_type = by_name[key].type
        try:
            if expected_type is bool:
                cleaned[key] = value if isinstance(value, bool) else str(value).strip().lower() in {"1", "true", "yes"}
            elif expected_type is int:
                cleaned[key] = int(value)
            elif expected_type is list:
                cleaned[key] = list(value) if isinstance(value, (list, tuple)) else [str(value)]
            else:
                cleaned[key] = str(value)[:500]
        except (TypeError, ValueError) as exc:
            raise ToolValidationError(f"Parameter {key!r} for {tool_name!r} must be {expected_type.__name__}") from exc

    return cleaned
