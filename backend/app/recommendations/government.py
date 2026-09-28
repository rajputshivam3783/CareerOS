"""GOVERNMENT RECOMMENDATIONS — wraps existing V5 eligibility, adds no
new eligibility logic of its own (spec: reuse, never re-derive
eligibility).

Wording rule, enforced in one place so it can't drift per call site:
never say "You are eligible" unless ``app.services.eligibility.eligibility``
returns ``eligible is True`` with a real profile on file. Everything
else — no profile, ``eligible is None`` (can't tell), or a partial
qualification/age match — is surfaced as "Potentially relevant" or
"Not clearly eligible", never a definitive positive claim. The
official source link is always preserved so the candidate can verify
directly, matching the GOVERNMENT RECOMMENDATIONS requirement.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.domain import Job, Profile
from app.services import eligibility as eligibility_service


@dataclass
class GovernmentRelevance:
    label: str  # "Eligible (indicative)" / "Potentially relevant" / "Not clearly eligible"
    reasons: list[str]
    confidence: int
    source_url: str | None
    disclaimer: str


def assess(job: Job, profile: Profile | None) -> GovernmentRelevance:
    verdict = eligibility_service.eligibility(job, profile)

    if verdict["eligible"] is True:
        label = "Eligible (indicative)"
    elif verdict["eligible"] is False:
        label = "Not clearly eligible"
    else:
        label = "Potentially relevant"

    return GovernmentRelevance(
        label=label,
        reasons=[r for r in verdict["reasons"] if r],
        confidence=verdict["confidence"],
        source_url=job.notification_url or job.apply_url,
        disclaimer=verdict.get(
            "disclaimer",
            "Indicative only — always confirm eligibility against the official notification before applying.",
        ),
    )
