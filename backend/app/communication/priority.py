"""V23.4 — deterministic communication priority.

Spec section 9: "Do not let an LLM arbitrarily determine urgency." AI
(nowhere in this package) has no role in the score itself — this is a
plain function of a handful of named, documented signals, always
reproducible, always explainable via ``reason``.

``score_by_days_until`` is the one function almost every action/
reminder in this package ultimately calls: it turns "how many days
(can be negative — already overdue/past) until this thing happens"
into one of the four communication-center priority levels. The
thresholds are named constants so a reviewer can trace every level
back to a single, obvious rule.
"""

from __future__ import annotations

from dataclasses import dataclass

PRIORITIES: tuple[str, ...] = ("LOW", "NORMAL", "HIGH", "URGENT")

# Thresholds, in days-until-the-event. Anything at or before
# URGENT_WITHIN_DAYS (including already-overdue, i.e. negative values)
# is URGENT; anything beyond FAR_OUT_DAYS is LOW.
URGENT_WITHIN_DAYS = 1
HIGH_WITHIN_DAYS = 3
NORMAL_WITHIN_DAYS = 7

# V22.4 application-health priority vocabulary (Low/Medium/High/
# Critical — see app.applications.ai.signals) -> this package's
# LOW/NORMAL/HIGH/URGENT vocabulary. A direct, documented mapping
# rather than a second scoring function, so an application-derived
# action's priority is always explainable by pointing at the same
# deterministic signals V22.4 already computed.
_APPLICATION_PRIORITY_MAP = {"Critical": "URGENT", "High": "HIGH", "Medium": "NORMAL", "Low": "LOW"}


@dataclass
class PriorityResult:
    level: str
    reason: str


def score_by_days_until(days_until: int | None, *, overdue_label: str = "overdue") -> PriorityResult:
    """``days_until`` is (target date/time - now), in days; negative
    means the target already passed. ``None`` (no date at all) is
    always LOW — nothing to be urgent about."""
    if days_until is None:
        return PriorityResult("LOW", "No date is set.")
    if days_until < 0:
        return PriorityResult("URGENT", f"Already {overdue_label} by {abs(days_until)} day(s).")
    if days_until <= URGENT_WITHIN_DAYS:
        return PriorityResult("URGENT", "Due today or tomorrow." if days_until >= 1 else "Due today.")
    if days_until <= HIGH_WITHIN_DAYS:
        return PriorityResult("HIGH", f"Due in {days_until} day(s).")
    if days_until <= NORMAL_WITHIN_DAYS:
        return PriorityResult("NORMAL", f"Due in {days_until} day(s).")
    return PriorityResult("LOW", f"Due in {days_until} day(s) — no immediate action needed.")


def from_application_priority(app_priority: str) -> PriorityResult:
    level = _APPLICATION_PRIORITY_MAP.get(app_priority, "NORMAL")
    return PriorityResult(level, f"Application intelligence rates this application '{app_priority}' priority.")


def max_priority(*levels: str) -> str:
    """Highest of several priority levels, by PRIORITIES' order."""
    ranked = [lvl for lvl in levels if lvl in PRIORITIES]
    if not ranked:
        return "NORMAL"
    return max(ranked, key=PRIORITIES.index)
