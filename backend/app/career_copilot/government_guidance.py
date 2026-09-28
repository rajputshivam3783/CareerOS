"""Government-job guidance for the Copilot: eligibility, deadlines,
and preparation — all grounded in the existing V5 eligibility engine
(``app.services.eligibility.eligibility``). This module never computes
its own eligibility verdict; it only packages that function's output
plus the job's own stated fields (deadline, exam_date, official links)
into a Copilot-friendly, still-fully-grounded answer.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.domain import Job, Profile
from app.services.eligibility import eligibility as calc_eligibility


def guidance(db: Session, user_id: int, job: Job) -> dict:
    profile = db.get(Profile, user_id)
    verdict = calc_eligibility(job, profile)

    if verdict["eligible"] is None:
        eligibility_statement = (
            "Eligibility cannot be confirmed with the information currently on file. "
            + " ".join(verdict["reasons"])
        )
    elif verdict["eligible"] is False:
        eligibility_statement = "Based on your profile, you likely do NOT meet at least one stated requirement: " + " ".join(verdict["reasons"])
    else:
        eligibility_statement = "Based on your profile, you likely meet the stated requirements: " + " ".join(verdict["reasons"])

    preparation = []
    if job.selection_process:
        preparation.append(f"Selection process: {job.selection_process}")
    if job.exam_date:
        preparation.append(f"Exam date: {job.exam_date.isoformat()}")
    else:
        preparation.append("Exam date not yet announced — check the official notification for updates.")
    if job.admit_card_url:
        preparation.append(f"Admit card: {job.admit_card_url}")

    return {
        "job": {"id": job.id, "title": job.title, "organization": job.organization},
        "eligibility": verdict,
        "eligibility_statement": eligibility_statement,
        "deadline": job.deadline.isoformat() if job.deadline else "Not stated — verify against the official notification",
        "preparation": preparation,
        "official_verification": {
            "notification_url": job.notification_url,
            "official_url": job.official_url,
            "note": "Always verify eligibility, deadlines, and exam details against this official notification before making decisions — this guidance is indicative only.",
        },
    }
