"""Assembles one user's authorized CareerOS data into a structured
``CareerContext`` — the single source every other module in this
package (and the chat prompt itself) reads from.

Every field is either a real value pulled from a table this user
already owns, or explicitly absent — collected into ``unknown_fields``
so the rest of the system (and the model, via ``to_prompt_text``) never
has to guess whether a gap means "not asked yet" or "confirmed empty."
This is what makes "clearly distinguish known information from unknown
information" structural: the context object itself carries that
distinction, not just the prose built from it.

Privacy: every query here is scoped to ``user_id`` — there is no
function in this module that can be called with one user's id and
return another's data. See AI_SAFETY.md's authorization section.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import Application, CareerPreference, Job, LearningPlan, Profile, ResumeAnalysis, SavedJob
from app.skill_intelligence import gap as gap_engine
from app.skill_intelligence import plans as plans_engine
from app.skill_intelligence import readiness as readiness_engine


@dataclass
class CareerContext:
    user_id: int
    profile: dict | None
    preferences: dict | None
    resume_summary: dict | None  # {technical_skills, missing_sections, overall_score, analyzed_at} or None
    saved_jobs: list[dict]
    applications: list[dict]
    upcoming_deadlines: list[dict]  # applications with next_deadline within 14 days
    skill_intelligence: dict | None  # {priority_skill_gaps, active_learning_plan, readiness} or None — see _skill_intelligence_summary
    unknown_fields: list[str] = field(default_factory=list)


def _profile_dict(profile: Profile | None) -> tuple[dict | None, list[str]]:
    if not profile:
        return None, [
            "candidate profile (location, qualification, skills)",
        ]
    unknown = []
    data = {
        "location": profile.location,
        "highest_qualification": profile.highest_qualification,
        "graduation_year": profile.graduation_year,
        "skills": profile.skills,
        "preferred_roles": profile.preferred_roles,
        "preferred_locations": profile.preferred_locations,
    }
    for key, value in data.items():
        if not value:
            unknown.append(f"profile.{key}")
    return data, unknown


def _preferences_dict(prefs: CareerPreference | None) -> tuple[dict | None, list[str]]:
    if not prefs:
        return None, ["career preferences (target role, industry, work mode, goals — not yet set)"]
    unknown = []
    data = {
        "target_role": prefs.target_role,
        "preferred_industry": prefs.preferred_industry,
        "preferred_location": prefs.preferred_location,
        "preferred_work_mode": prefs.preferred_work_mode,
        "experience_level": prefs.experience_level,
        "target_companies": prefs.target_companies,
        "salary_expectation": prefs.salary_expectation,
        "preferred_skills": prefs.preferred_skills,
        "learning_goals": prefs.learning_goals,
        "career_goal": prefs.career_goal,
    }
    for key, value in data.items():
        if not value:
            unknown.append(f"preferences.{key}")
    return data, unknown


def _resume_summary(analysis: ResumeAnalysis | None) -> tuple[dict | None, list[str]]:
    if not analysis:
        return None, ["resume (not uploaded, or not yet analyzed — see POST /resume and GET /resume-ai/analysis)"]
    profile = json.loads(analysis.profile_json)
    scores = json.loads(analysis.scores_json)
    return {
        "technical_skills": profile.get("technical_skills", []),
        "soft_skills": profile.get("soft_skills", []),
        "missing_sections": profile.get("missing_sections", []),
        "overall_score": scores.get("overall", {}).get("score"),
        "analyzed_at": analysis.analyzed_at.isoformat(),
    }, []


def _skill_intelligence_summary(db: Session, user_id: int) -> tuple[dict | None, list[str]]:
    """Reuses — never recomputes with different logic — the V20.5
    Phase 1-3 engines: unified skill gap, active learning plan
    progress, and career readiness. This is what lets the copilot
    explain "Learning Plan, Skill Gaps, Progress, Readiness, Next
    Steps" per the spec without a second AI career engine — it's just
    reading the same tables/services the /skill-intelligence/* and
    /learning-plans/* and /career-readiness endpoints already use."""

    unknown: list[str] = []
    gap_result = gap_engine.compute(db, user_id)
    top_gaps = [
        {"skill": item.display_name, "reason": item.reason, "priority_score": item.priority_score}
        for item in gap_result.priority_skills[:5]
    ]
    if not top_gaps:
        unknown.append("priority skill gaps (none identified yet — upload a resume and/or select a target job)")

    plan_row = db.execute(
        select(LearningPlan)
        .where(LearningPlan.user_id == user_id, LearningPlan.status == "active")
        .order_by(LearningPlan.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    active_plan = None
    if plan_row:
        p = plans_engine.progress(db, plan_row.id, user_id)
        active_plan = {
            "title": plan_row.title,
            "completion_percentage": p.completion_percentage,
            "completed_modules": p.completed,
            "total_modules": p.total_modules,
        }
    else:
        unknown.append("active learning plan (none — candidate hasn't created one yet)")

    readiness = readiness_engine.compute(db, user_id)
    readiness_data = {
        "role_readiness": readiness.role_readiness,
        "components": [
            {"name": c.name, "score": c.score, "reason": c.reason} for c in readiness.components if c.score is not None
        ],
    }
    if readiness.role_readiness == 0.0 and not readiness_data["components"]:
        unknown.append("career readiness score (not enough data yet)")

    return {
        "priority_skill_gaps": top_gaps,
        "unrecognized_skill_inputs": gap_result.unrecognized_inputs,
        "active_learning_plan": active_plan,
        "readiness": readiness_data,
    }, unknown


def build(db: Session, user_id: int) -> CareerContext:
    unknown: list[str] = []

    profile = db.get(Profile, user_id)
    profile_data, profile_unknown = _profile_dict(profile)
    unknown += profile_unknown

    prefs = db.get(CareerPreference, user_id)
    prefs_data, prefs_unknown = _preferences_dict(prefs)
    unknown += prefs_unknown

    resume_analysis = db.get(ResumeAnalysis, user_id)
    resume_data, resume_unknown = _resume_summary(resume_analysis)
    unknown += resume_unknown

    saved = db.execute(
        select(Job).join(SavedJob, SavedJob.job_id == Job.id).where(SavedJob.user_id == user_id).order_by(SavedJob.id.desc()).limit(20)
    ).scalars().all()
    saved_jobs = [{"id": j.id, "title": j.title, "organization": j.organization, "job_type": j.job_type, "deadline": j.deadline.isoformat() if j.deadline else None} for j in saved]

    applications = db.execute(
        select(Application).where(Application.user_id == user_id).order_by(Application.created_at.desc()).limit(30)
    ).scalars().all()
    applications_data = [
        {
            "id": a.id, "job_id": a.job_id, "company": a.company, "role": a.role, "status": a.status,
            "applied_on": a.applied_on.isoformat() if a.applied_on else None,
            "next_deadline": a.next_deadline.isoformat() if a.next_deadline else None,
        }
        for a in applications
    ]
    if not applications_data:
        unknown.append("job applications (none tracked yet)")

    skill_intel_data, skill_intel_unknown = _skill_intelligence_summary(db, user_id)
    unknown += skill_intel_unknown

    horizon = date.today() + timedelta(days=14)
    upcoming = [a for a in applications_data if a["next_deadline"] and a["next_deadline"] <= horizon.isoformat()]

    return CareerContext(
        user_id=user_id,
        profile=profile_data,
        preferences=prefs_data,
        resume_summary=resume_data,
        saved_jobs=saved_jobs,
        applications=applications_data,
        upcoming_deadlines=upcoming,
        skill_intelligence=skill_intel_data,
        unknown_fields=unknown,
    )


def to_prompt_text(context: CareerContext) -> str:
    """Renders the context into the clearly-delimited block the system
    prompt instructs the model to treat as the *only* source of truth
    about this candidate. See system_prompt.py."""
    lines = ["=== KNOWN CANDIDATE CONTEXT (verified from CareerOS records) ==="]

    if context.profile:
        lines.append(f"Profile: {context.profile}")
    if context.preferences:
        lines.append(f"Stated career preferences: {context.preferences}")
    if context.resume_summary:
        lines.append(f"Resume summary: {context.resume_summary}")
    if context.saved_jobs:
        lines.append(f"Saved jobs ({len(context.saved_jobs)}): {context.saved_jobs}")
    if context.applications:
        lines.append(f"Applications ({len(context.applications)}): {context.applications}")
    if context.upcoming_deadlines:
        lines.append(f"Deadlines in the next 14 days: {context.upcoming_deadlines}")
    if context.skill_intelligence:
        lines.append(f"Skill gap, learning plan, and readiness (from V20.5 Skill Intelligence): {context.skill_intelligence}")

    lines.append("=== UNKNOWN / NOT YET PROVIDED (do not assume or invent values for these) ===")
    lines.append(str(context.unknown_fields) if context.unknown_fields else "(nothing — all standard fields are populated)")
    lines.append("=== END CONTEXT ===")

    return "\n".join(lines)
