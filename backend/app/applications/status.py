"""STATUS LIFECYCLE — the canonical vocabulary and its rules.

    SAVED -> PLANNING_TO_APPLY -> APPLIED -> ASSESSMENT -> INTERVIEW
    -> OFFER -> ACCEPTED / REJECTED / WITHDRAWN

...with GHOSTED reachable from APPLIED onward (the recruiter simply
stopped responding) as the one status that doesn't fit the otherwise
linear happy path. This is documented as the *typical* journey, not an
enforced finite-state machine — a real job search is not always
linear (a candidate can be rejected straight after APPLIED with no
ASSESSMENT/INTERVIEW step, can reapply after WITHDRAWN, etc.), so
``service.py`` validates only that a status is one of the 10 known
values, never that a specific transition is "allowed." Every change is
still fully recorded via ApplicationStatusHistory regardless of how
unusual the jump looks.
"""

from __future__ import annotations

# Order matters only for display (e.g. a Kanban-style column order in
# a future version) — it is not an enforced sequence.
STATUS_VALUES: tuple[str, ...] = (
    "SAVED",
    "PLANNING_TO_APPLY",
    "APPLIED",
    "ASSESSMENT",
    "INTERVIEW",
    "OFFER",
    "ACCEPTED",
    "REJECTED",
    "WITHDRAWN",
    "GHOSTED",
)
VALID_STATUSES = set(STATUS_VALUES)

# TERMINAL statuses — a real end state for this application. Used only
# for stats/UI grouping (e.g. "active" vs. "closed" applications);
# never blocks a further status change (a candidate can still correct
# a mistaken REJECTED back to INTERVIEW, for example).
TERMINAL_STATUSES = {"ACCEPTED", "REJECTED", "WITHDRAWN", "GHOSTED"}

# Legacy V7 values (informal, lowercase, narrower set) -> canonical
# V22.1 value. Applied wherever a status is read or written so old
# API callers, old stored rows, and old filter values keep working
# without the rest of the codebase needing to know two vocabularies
# exist. Matches the one-time SQL backfill in
# migrations/v22_1_application_tracking.sql exactly — kept as a
# runtime fallback too, in case a row somehow still holds a
# pre-migration value (e.g. restored from an old backup).
_LEGACY_ALIASES: dict[str, str] = {
    "planned": "PLANNING_TO_APPLY",
    "applied": "APPLIED",
    "interview": "INTERVIEW",
    "offer": "OFFER",
    "rejected": "REJECTED",
    "accepted": "ACCEPTED",
    "withdrawn": "WITHDRAWN",
    "saved": "SAVED",
    "assessment": "ASSESSMENT",
    "ghosted": "GHOSTED",
}

DEFAULT_STATUS_FOR_EXTERNAL = "SAVED"
DEFAULT_STATUS_FOR_TRACK = "PLANNING_TO_APPLY"
DEFAULT_STATUS_FOR_MARK_APPLIED = "APPLIED"

# V22.2 STATUS TRANSITION RULES.
#
# V22.1 deliberately validated only that a new status is *a* known
# value, never that moving from A to B specifically makes sense — a
# real job search isn't linear (rejected straight after APPLIED with
# no ASSESSMENT/INTERVIEW step is common; so is reapplying). V22.2
# keeps exactly that philosophy for every *forward or lateral* move —
# nothing below blocks jumping ahead, skipping a stage, or moving
# sideways between non-terminal stages (e.g. INTERVIEW -> ASSESSMENT
# if a second screening round gets scheduled).
#
# The one new guardrail: once an application reaches a TERMINAL status
# (ACCEPTED/REJECTED/WITHDRAWN — GHOSTED stays freely reversible, since
# "the recruiter went quiet" is often just provisional, not a real
# outcome), moving it to anything else requires the caller to pass
# `reopen=True` explicitly (see app.applications.service.change_status
# and POST /applications/{id}/status). This is what the spec calls
# "allow reopening where appropriate through an explicit action" —
# a deliberate choice, not an accidental drag onto the wrong column.
#
# `ALLOWED_FORWARD_TRANSITIONS` documents the *typical* graph (used by
# the frontend to render Kanban drop targets sensibly) but is
# intentionally not the sole source of truth for what's blocked —
# can_transition() below allows any non-terminal -> non-terminal move
# regardless of whether it's listed here, since restricting *those* is
# exactly what "do not make the workflow unnecessarily restrictive"
# warns against. Only the terminal-state guardrail is actually enforced.
ALLOWED_FORWARD_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "SAVED": ("PLANNING_TO_APPLY", "APPLIED", "WITHDRAWN"),
    "PLANNING_TO_APPLY": ("APPLIED", "WITHDRAWN"),
    "APPLIED": ("ASSESSMENT", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN", "GHOSTED"),
    "ASSESSMENT": ("INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN", "GHOSTED"),
    "INTERVIEW": ("ASSESSMENT", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN", "GHOSTED"),
    "OFFER": ("ACCEPTED", "REJECTED", "WITHDRAWN"),
    "GHOSTED": ("ASSESSMENT", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"),
}


# Statuses that require an explicit reopen to move out of (V22.2). A
# narrower set than TERMINAL_STATUSES on purpose: TERMINAL_STATUSES
# already has an established meaning elsewhere (duplicate-prevention
# exemption in app.applications.service._find_duplicate, stats/UI
# grouping) that includes GHOSTED — reusing it here would silently
# change GHOSTED's duplicate-prevention behavior too. GHOSTED means
# "the recruiter went quiet," which is often provisional, not a real
# outcome, so it stays freely reversible without needing reopen.
REOPEN_REQUIRED_STATUSES = {"ACCEPTED", "REJECTED", "WITHDRAWN"}


class TerminalStatusReopenRequiredError(ValueError):
    """Raised when a caller tries to move an application out of a
    terminal status (ACCEPTED/REJECTED/WITHDRAWN) without explicitly
    passing reopen=True."""

    def __init__(self, current_status: str, attempted_status: str):
        self.current_status = current_status
        self.attempted_status = attempted_status
        super().__init__(
            f"'{current_status}' is a terminal status — pass reopen=true to explicitly move it to '{attempted_status}'"
        )


def can_transition(old_status: str | None, new_status: str, *, reopen: bool = False) -> bool:
    """True unless this would silently move an application out of a
    terminal status. `old_status=None` (a brand-new application) is
    always allowed. Moving a terminal status to itself (no-op) is
    always allowed without reopen."""
    if old_status is None or old_status == new_status:
        return True
    if old_status in REOPEN_REQUIRED_STATUSES:
        return reopen
    return True


class InvalidStatusError(ValueError):
    pass


def normalize(raw: str) -> str:
    """Maps any legacy or differently-cased input to the canonical
    uppercase value. Raises InvalidStatusError for anything that isn't
    a recognized status, legacy or current — never silently accepts an
    arbitrary string (a free-text status would break every filter/stat
    that groups by status)."""
    if raw is None:
        raise InvalidStatusError("status is required")
    candidate = raw.strip()
    if candidate.upper() in VALID_STATUSES:
        return candidate.upper()
    alias = _LEGACY_ALIASES.get(candidate.lower())
    if alias:
        return alias
    raise InvalidStatusError(f"'{raw}' is not a recognized status. Expected one of {STATUS_VALUES}")


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES
