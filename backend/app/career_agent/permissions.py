"""V25.4 — Tool permission system (spec section 17).

Every tool call is checked here, server-side, regardless of what the
LLM proposed. A candidate can only ever be authenticated as a
candidate for this router (see app/api/career_agent.py, which depends
on ``current_user`` with no role branching) — so in this pass the
check that matters most is *ownership*, enforced by each tool handler
itself (every handler takes ``user`` and only ever queries that
user's rows — see tools.py), plus the explicit exclusion below of any
tool namespace this router must never expose.

Recruiter/admin tools are simply never registered in
``app.career_agent.tool_registry`` for the candidate agent — there is
no code path from this router to app.api.recruiter*, app.api.admin*,
or app.api.recruiter_analytics/recruiter_pipeline. The denylist below
is a second, explicit guard against the specific mistake of someday
registering one of those by name.
"""

from __future__ import annotations

# Tool-name prefixes/keywords that must never appear in the candidate
# agent's tool registry. Checked by a test (see
# tests/test_v25_4_ai_career_agent.py::test_no_recruiter_admin_tools)
# so an accidental future addition fails CI, not just review.
FORBIDDEN_TOOL_KEYWORDS = (
    "recruiter",
    "admin",
    "applicant",
    "pipeline",
    "platform_",
    "organization_manage",
)


def assert_candidate_safe_tool_name(tool_name: str) -> None:
    lowered = tool_name.lower()
    for keyword in FORBIDDEN_TOOL_KEYWORDS:
        if keyword in lowered:
            raise PermissionError(f"Tool {tool_name!r} is not permitted for the candidate Career Agent")


class ToolPermissionError(PermissionError):
    pass


def require_candidate(user) -> None:
    """Every Career Agent tool is candidate-facing. A recruiter or
    admin account can still be a *candidate* in this codebase's role
    model (role is a single string), but nothing here escalates a
    tool's effect beyond that user's own data — see each tool's
    ownership check in tools.py. This function exists as the one
    place a future role restriction (e.g. "recruiters can't use the
    candidate agent at all") would be added, so it's already the
    single call site every handler and the API layer go through."""

    if user is None:
        raise ToolPermissionError("Authentication required")
