"""V5 Eligibility AI — "Am I eligible?"

Deliberately deterministic and explainable, not a black-box model: a
wrong "yes" here could cost someone an application fee and a missed
attempt at a different, actually-eligible exam, so every verdict must
trace back to a plain-English reason. Where the source data is too
vague to check (the extremely common "See official notification"
placeholder, or an unparsed age-limit string), this reports honest
uncertainty rather than guessing.
"""

import re
from datetime import date

from app.models.domain import Job, Profile

QUALIFICATION_LEVELS = [
    ("10th", ["10th", "matric"]),
    ("12th", ["12th", "intermediate"]),
    ("diploma", ["diploma"]),
    ("graduate", ["graduate", "bachelor", "b.tech", "b.e."]),
    ("postgraduate", ["postgraduate", "master", "m.tech", "m.sc", "mba"]),
]

# Indicative age-relaxation years commonly seen across Indian central
# government recruitment (SSC/UPSC-style conventions). These vary by
# exam and by year, so they're used only to produce an estimate, never
# a final answer — see the "always verify" note in every eligibility
# response below.
RESERVATION_RELAXATION_YEARS: dict[str, int] = {
    "general": 0,
    "ews": 0,
    "obc": 3,
    "sc": 5,
    "st": 5,
}
PWD_ADDITIONAL_RELAXATION_YEARS = 10


def _relaxation_years(category: str | None, is_pwd: bool) -> int:
    base = RESERVATION_RELAXATION_YEARS.get((category or "general").strip().lower(), 0)
    return base + (PWD_ADDITIONAL_RELAXATION_YEARS if is_pwd else 0)


def parse_age_range(age_limit_text: str | None) -> tuple[int | None, int | None]:
    """Best-effort extraction of (min_age, max_age) from free-text like
    "18-27 years", "Between 18 and 30 years", or "Not exceeding 30
    years". Returns (None, None) when the text doesn't match a
    recognized shape rather than guessing."""
    if not age_limit_text:
        return None, None

    text = age_limit_text.lower()

    range_match = re.search(r"(\d{1,2})\s*(?:-|to|and)\s*(\d{1,2})\s*years?", text)
    if range_match:
        return int(range_match.group(1)), int(range_match.group(2))

    max_only = re.search(r"(?:not exceeding|maximum|up to|below)\s*(\d{1,2})\s*years?", text)
    if max_only:
        return None, int(max_only.group(1))

    min_only = re.search(r"(?:minimum|at least|above)\s*(\d{1,2})\s*years?", text)
    if min_only:
        return int(min_only.group(1)), None

    return None, None


def compute_age(date_of_birth: date, as_on: date) -> int:
    years = as_on.year - date_of_birth.year
    had_birthday = (as_on.month, as_on.day) >= (date_of_birth.month, date_of_birth.day)
    return years if had_birthday else years - 1


def _check_qualification(job: Job, profile: Profile) -> tuple[bool | None, str]:
    required = (job.qualification or "").lower()
    candidate = (profile.highest_qualification or "").lower()

    if "see official" in required or not required:
        return None, "Qualification must be verified from the official notification"
    if not candidate:
        return None, "Add your highest qualification to your profile to check this"

    matches = [
        name
        for name, keywords in QUALIFICATION_LEVELS
        if any(k in candidate for k in keywords) and any(k in required for k in keywords)
    ]
    if matches:
        return True, f"Qualification matches ({', '.join(matches)})"
    return False, "No clear qualification match found — double-check against the notification"


def _check_age(job: Job, profile: Profile) -> tuple[bool | None, str, dict]:
    min_age, max_age = parse_age_range(job.age_limit)
    details: dict = {"min_age": min_age, "max_age": max_age, "relaxation_years_applied": 0}

    if min_age is None and max_age is None:
        return None, "Age limit must be verified from the official notification", details
    if not profile.date_of_birth:
        return None, "Add your date of birth to your profile to check age eligibility", details

    as_on = job.deadline or job.exam_date or date.today()
    age = compute_age(profile.date_of_birth, as_on)
    details["candidate_age_as_on"] = str(as_on)
    details["candidate_age"] = age

    relaxation = _relaxation_years(profile.reservation_category, profile.is_pwd)
    details["relaxation_years_applied"] = relaxation
    effective_max = (max_age + relaxation) if max_age is not None else None

    within_min = min_age is None or age >= min_age
    within_max = effective_max is None or age <= effective_max

    if within_min and within_max:
        note = f"Age {age} is within the {min_age or '—'}-{max_age or '—'} range"
        if relaxation:
            note += f" (including a {relaxation}-year relaxation estimate — confirm the exact figure for this exam)"
        return True, note, details

    return False, f"Age {age} falls outside the {min_age or '—'}-{max_age or '—'} range as on {as_on}", details


def eligibility(job: Job, profile: Profile | None) -> dict:
    """Combine the qualification check and the age check into one
    verdict. `eligible` is True only if neither check came back False
    and at least one came back True; None means "can't tell — verify
    manually"; False means at least one check clearly failed."""
    if not profile:
        return {
            "eligible": None,
            "reasons": ["Complete your profile first"],
            "confidence": 0,
            "qualification_check": None,
            "age_check": None,
        }

    qualification_ok, qualification_reason = _check_qualification(job, profile)
    age_ok, age_reason, age_details = _check_age(job, profile)

    reasons = [qualification_reason, age_reason]
    checks = [qualification_ok, age_ok]

    if False in checks:
        eligible = False
        confidence = 70
    elif all(c is True for c in checks):
        eligible = True
        confidence = 80
    else:
        eligible = None
        confidence = 35

    return {
        "eligible": eligible,
        "reasons": reasons,
        "confidence": confidence,
        "qualification_check": qualification_ok,
        "age_check": age_ok,
        "age_details": age_details,
        "disclaimer": "Indicative only — always confirm eligibility against the official notification before applying.",
    }
