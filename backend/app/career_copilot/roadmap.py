"""Deterministic career roadmap: Current Position -> Target Role ->
Skill Gaps -> Learning Priorities -> Projects -> Interview Preparation
-> Applications.

No AI call — every step is composed from real profile/resume/skill-gap
data, reusing V20.2's resume-grounded skill gap engine
(``app.resume_ai.skill_gap``) when a resume exists, or the V6
profile-based one (``app.services.career.skill_gap``) otherwise.
Never a second skill-gap engine.
"""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy.orm import Session

from app.career_copilot import job_recommendations
from app.models.domain import CareerPreference, Job, Profile, Resume
from app.resume_ai import pipeline as resume_pipeline
from app.resume_ai import skill_gap as resume_skill_gap
from app.services.career import skill_gap as profile_skill_gap


def _pick_target_job(db: Session, user_id: int, job_id: int | None) -> Job | None:
    if job_id:
        return db.get(Job, job_id)
    recs = job_recommendations.recommend(db, user_id, limit=1)
    if not recs:
        return None
    return db.get(Job, recs[0]["job_id"])


def build(db: Session, user_id: int, *, job_id: int | None = None) -> dict:
    prefs = db.get(CareerPreference, user_id)
    profile = db.get(Profile, user_id)
    resume = db.get(Resume, user_id)
    target_job = _pick_target_job(db, user_id, job_id)

    current_position = {
        "highest_qualification": profile.highest_qualification if profile else None,
        "current_skills": [],
        "note": "Not found in profile or resume" if not profile and not resume else None,
    }

    if resume:
        normalized = resume_pipeline.build_profile(resume)
        current_position["current_skills"] = normalized.technical_skills
    elif profile and profile.skills:
        current_position["current_skills"] = [s.strip() for s in profile.skills.split(",") if s.strip()]

    target_role = (prefs.target_role if prefs and prefs.target_role else None) or (target_job.title if target_job else None)

    skill_gap_result: dict
    if target_job and resume:
        normalized = resume_pipeline.build_profile(resume)
        gap = resume_skill_gap.analyze(normalized, target_job)
        skill_gap_result = asdict(gap)
    elif target_job:
        skill_gap_result = profile_skill_gap(target_job, profile)
    else:
        skill_gap_result = {"missing_skills": [], "note": "No target job selected and no recommendation available — set a target role in preferences or save a job."}

    missing = skill_gap_result.get("missing_skills") or skill_gap_result.get("learn") or []
    learning_priorities = [f"Learn {s}" for s in missing[:5]]
    if prefs and prefs.learning_goals:
        learning_priorities.append(f"Your stated learning goal: {prefs.learning_goals}")

    projects = (
        [f"Build a project that demonstrates {s}" for s in missing[:3]]
        if missing
        else ["Consider a project that showcases your strongest current skills for this target role."]
    )

    interview_prep = ["Practice explaining your existing projects and experience clearly."]
    if target_job:
        interview_prep.append(f"Review the job description for {target_job.title} at {target_job.organization} and prepare examples matching its stated requirements.")
    if missing:
        interview_prep.append(f"Be ready to discuss how you're addressing these gaps: {', '.join(missing[:5])}.")

    applications_step = {
        "target_job": {"id": target_job.id, "title": target_job.title, "organization": target_job.organization} if target_job else None,
        "note": "Apply once your resume reflects the skills above" if missing else "Your skills look aligned — consider applying.",
    }

    return {
        "current_position": current_position,
        "target_role": target_role or "Not set — add a target role in Career Preferences",
        "skill_gaps": skill_gap_result,
        "learning_priorities": learning_priorities or ["No specific gaps identified against the target role."],
        "projects": projects,
        "interview_preparation": interview_prep,
        "applications": applications_step,
        "grounded_in": {
            "used_resume": resume is not None,
            "used_target_job_id": target_job.id if target_job else None,
            "used_stated_preferences": prefs is not None,
        },
    }
