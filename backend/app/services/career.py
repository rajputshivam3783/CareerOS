"""V6 Matching and V8 Skill-gap logic.

Deliberately deterministic and explainable (no black-box ML) so every
score can be traced back to a reason. See app/services/eligibility.py
for the V5 "Am I eligible?" engine, and app/services/semantic_search.py
for the V6 job-search-by-query engine (this module blends the same
TF-IDF technique into per-job matching, see `_text_similarity`).
"""

from app.models.domain import Job, Profile
from app.services.text_similarity import similarity_scores

SKILLS = [
    "java", "python", "sql", "javascript", "typescript", "react", "next.js",
    "fastapi", "spring boot", "aws", "azure", "docker", "kubernetes", "git",
    "data structures", "machine learning", "pandas", "power bi", "excel",
    "terraform",
]


def tokens(value: str | None) -> set[str]:
    return {x.strip().lower() for x in (value or "").split(",") if x.strip()}


def job_text(job: Job) -> str:
    return " ".join(
        filter(None, [job.title, job.description, job.qualification, job.category, job.selection_process])
    ).lower()


def _profile_text(profile: Profile | None) -> str:
    if not profile:
        return ""
    return " ".join(
        filter(
            None,
            [profile.skills, profile.preferred_roles, profile.highest_qualification, profile.preferred_locations],
        )
    )


def _text_similarity(text_a: str, text_b: str) -> float:
    """TF-IDF cosine similarity between two short texts, 0.0-1.0.

    With only two documents the IDF weighting is a limited signal
    (there's no larger corpus to weigh rarity against), but it still
    rewards genuine shared vocabulary over incidental word overlap
    better than a raw word-overlap count would. Returns 0.0 for
    empty/degenerate input rather than raising.
    """
    if not text_a.strip() or not text_b.strip():
        return 0.0
    try:
        return similarity_scores(text_a, [text_b])[0]
    except (IndexError, ValueError):
        return 0.0


def match_score(job: Job, profile: Profile | None) -> dict:
    my_skills = tokens(profile.skills if profile else None)
    text = job_text(job)
    job_skills = {s for s in SKILLS if s in text}
    matched = my_skills & job_skills

    # Explicit skill-token overlap — the most reliable signal when it's available.
    skill_score = (len(matched) / max(1, len(job_skills)) * 40) if job_skills else 20

    # TF-IDF similarity between the candidate's whole profile text and the
    # job's text — catches relevant overlap that the fixed SKILLS list
    # misses (tools, domains, phrasing) without claiming true semantic
    # understanding. See semantic_search.py's docstring for the same caveat.
    semantic_similarity = _text_similarity(_profile_text(profile), job_text(job))
    semantic_score = semantic_similarity * 30

    preferred_roles = (profile.preferred_roles or "").lower() if profile else ""
    role_score = 20 if any(x.strip() and x.strip() in job.title.lower() for x in preferred_roles.split(",")) else 0

    preferred_locations = (profile.preferred_locations or "").lower() if profile else ""
    location_score = 10 if job.location.lower() in preferred_locations or "india" in preferred_locations else 0

    return {
        "score": round(min(100, skill_score + semantic_score + role_score + location_score)),
        "matched_skills": sorted(matched),
        "job_skills": sorted(job_skills),
        "semantic_similarity": round(semantic_similarity, 4),
        "breakdown": {
            "skill_overlap": round(skill_score, 1),
            "semantic_similarity": round(semantic_score, 1),
            "preferred_role": role_score,
            "preferred_location": location_score,
        },
        "engine": "CareerOS deterministic matching v3 (skill-token overlap + TF-IDF text similarity)",
    }


def skill_gap(job: Job, profile: Profile | None) -> dict:
    my_skills = tokens(profile.skills if profile else None)
    job_skills = {s for s in SKILLS if s in job_text(job)}
    missing = sorted(job_skills - my_skills)

    roadmap = [f"Learn {s}" for s in missing[:5]]
    roadmap += (
        ["Build one role-relevant project", "Practice DSA and interviews", "Apply and track outcomes"]
        if missing
        else ["Build a role-relevant project", "Practice interviews", "Apply and track outcomes"]
    )

    return {"have": sorted(my_skills & job_skills), "learn": missing, "roadmap": roadmap}
