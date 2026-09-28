"""V16 — offer letter generation.

Deliberately template-based, not AI-generated: the same reasoning V8's
exam-prep resources already use in this codebase applies here too — a
confidently wrong number in a real offer (salary, start date) is a
serious problem, not a cosmetic one, so this only ever echoes back
exactly the structured fields the recruiter entered.
"""

from __future__ import annotations

from datetime import date


def render_offer_letter(
    *,
    candidate_name: str,
    organization: str,
    position_title: str,
    salary: str | None,
    start_date: date | None,
    expiry_date: date | None,
) -> str:
    lines = [
        f"Offer of Employment — {organization}",
        "",
        f"Dear {candidate_name},",
        "",
        f"We are pleased to offer you the position of {position_title} at {organization}.",
    ]
    if salary:
        lines.append(f"Compensation: {salary}.")
    if start_date:
        lines.append(f"Proposed start date: {start_date.isoformat()}.")
    if expiry_date:
        lines.append(f"This offer is valid until {expiry_date.isoformat()}; please respond by then.")
    lines += [
        "",
        "This letter is a summary of terms and does not constitute a complete "
        "employment contract. Final terms will be confirmed in your formal "
        "employment agreement.",
        "",
        "We look forward to your response.",
    ]
    return "\n".join(lines)
