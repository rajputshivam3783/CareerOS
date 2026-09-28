"""V8 — resume-JD matching and a phased learning roadmap.

Blends the same two explainable signals used elsewhere in this
project: skill-token overlap (exact vocabulary matches) and TF-IDF
text similarity (see app/services/semantic_search.py) between the
resume text and the job's own text. No resume-parsing "AI" claims
beyond what's actually computed — this is the same deterministic
approach as V6 matching, just grounded in resume text instead of a
profile's typed-in skills field.
"""

from app.models.domain import Job
from app.services.career import SKILLS, job_text
from app.services.semantic_search import text_similarity


def match_resume_to_job(resume_text: str, resume_skills: list[str], job: Job) -> dict:
    job_skills = {s for s in SKILLS if s in job_text(job)}
    resume_skill_set = set(resume_skills)

    matched = sorted(resume_skill_set & job_skills)
    missing = sorted(job_skills - resume_skill_set)

    skill_score = (len(matched) / max(1, len(job_skills)) * 60) if job_skills else 30
    similarity = text_similarity(resume_text, job_text(job))
    similarity_score = similarity * 40

    overall = round(min(100, skill_score + similarity_score))

    return {
        "score": overall,
        "matched_skills": matched,
        "missing_skills": missing,
        "text_similarity": round(similarity, 3),
        "breakdown": {
            "skill_overlap_points": round(skill_score, 1),
            "text_similarity_points": round(similarity_score, 1),
        },
        "engine": "CareerOS resume matching v1 (skill overlap + TF-IDF similarity)",
    }


def learning_roadmap(missing_skills: list[str]) -> dict:
    """A phased, generic study plan built from the missing-skills list.

    Deliberately generic rather than linking specific courses: naming
    real course URLs/providers here would go stale and could look like
    an endorsement this project isn't in a position to make. Pointing
    to curated, admin-verified resources is handled separately by the
    exam-prep resources feature (ExamPrepResource) for exam-specific
    material, which is a different kind of claim (a link exists and
    was checked) than "this course is good" (an opinion this project
    shouldn't assert).
    """
    if not missing_skills:
        return {
            "immediate": [],
            "medium_term": ["Tailor your resume's wording to this job's listed requirements"],
            "long_term": ["Keep applying and tracking outcomes — see the Applications tracker"],
        }

    immediate = [f"Learn the basics of {skill}" for skill in missing_skills[:3]]
    medium_term = [f"Build one small project that uses {skill}" for skill in missing_skills[:3]]
    long_term = [
        "Add the new skills to your resume once you've used them in a project",
        "Practice explaining these projects out loud before interviews",
    ]

    return {"immediate": immediate, "medium_term": medium_term, "long_term": long_term}
