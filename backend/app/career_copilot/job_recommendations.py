"""Job recommendations for the Copilot.

Deliberately a thin wrapper, not a new engine: ranking is
``app.services.career.match_score`` — the exact same function
``GET /recommendations`` (V6/V9) already uses — called over the same
published-jobs pool. The only thing this module adds on top is an
explanation string per job (which of the four already-computed
sub-scores drove the ranking) and, when the candidate has stated
career preferences, a light re-sort nudge toward their stated target
role/location — never a second scoring formula.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import CareerPreference, Job, Profile
from app.services.career import match_score


def _explain(match: dict) -> str:
    breakdown = match["breakdown"]
    top = max(breakdown, key=breakdown.get)
    labels = {
        "skill_overlap": f"skill overlap ({', '.join(match['matched_skills']) or 'none'})",
        "semantic_similarity": "overall profile-to-job text similarity",
        "preferred_role": "matches a preferred role you listed",
        "preferred_location": "matches a preferred location you listed",
    }
    if breakdown[top] <= 0:
        return "Included as a general match — no strong signal in any single category yet."
    return f"Strongest signal: {labels.get(top, top)}."


def recommend(db: Session, user_id: int, *, limit: int = 10) -> list[dict]:
    profile = db.get(Profile, user_id)
    prefs = db.get(CareerPreference, user_id)

    jobs = db.execute(select(Job).where(Job.status == "published").limit(200)).scalars().all()
    ranked = []
    for job in jobs:
        match = match_score(job, profile)
        # Preferences nudge: a small, transparent bonus (not a hidden
        # re-weighting of match_score's own formula) when the job's
        # title/location echoes a preference the candidate explicitly
        # stated — surfaced in the explanation, never silently applied.
        nudge = 0
        nudge_reason = None
        if prefs and prefs.target_role and prefs.target_role.lower() in job.title.lower():
            nudge = 5
            nudge_reason = f"Title matches your stated target role '{prefs.target_role}'"
        ranked.append({"job": job, "match": match, "adjusted_score": min(100, match["score"] + nudge), "nudge_reason": nudge_reason})

    ranked.sort(key=lambda r: r["adjusted_score"], reverse=True)

    return [
        {
            "job_id": r["job"].id,
            "title": r["job"].title,
            "organization": r["job"].organization,
            "job_type": r["job"].job_type,
            "location": r["job"].location,
            "score": r["adjusted_score"],
            "base_score": r["match"]["score"],
            "explanation": _explain(r["match"]) + (f" {r['nudge_reason']}." if r["nudge_reason"] else ""),
            "matched_skills": r["match"]["matched_skills"],
        }
        for r in ranked[:limit]
    ]
