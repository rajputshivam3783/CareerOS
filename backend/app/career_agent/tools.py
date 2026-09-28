"""V25.4 — Career Agent tool handlers (spec sections 3, 5, 6, 9-13, 19-20).

Every function here has the shape ``handler(db, user, **params) -> dict``
and is registered in ``tool_registry.py`` under the same name. None of
these re-implement search, ranking, matching, skill-gap, eligibility,
or notification-delivery logic — each is a thin, privacy-scoped call
into the existing V20-V25.3 service layer, exactly as spec section 6
("Do not create a second recommendation algorithm") and section 25
("Job filtering -> V21 search... Do not call an LLM for deterministic
operations") require.

Ownership: every handler is passed the authenticated ``User`` and
either queries only rows with ``user_id == user.id`` or reads public
data (published jobs) — there is no parameter in any handler that
accepts another user's id. Tools that operate on an application or
task additionally go through the existing owned-row lookups in
``app.applications.service``/``app.applications.tasks``, which already
raise/404 on a mismatched id — a second copy of that check is not
duplicated here.

AI safety (spec section 23): every handler either returns data read
directly from CareerOS tables, or (analyze_resume, prepare_interview)
delegates to a module that already enforces "AI narrates, deterministic
logic decides" (app.resume_ai, app.applications.ai) — no handler here
asks a model "is this candidate eligible" or fabricates a result when
data is missing; missing data is returned as an explicit ``None``/empty
value, never guessed.
"""

from __future__ import annotations

import json as _json
from dataclasses import asdict
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.api.platform import get_public_job
from app.applications import service as applications_service
from app.applications import tasks as tasks_service
from app.applications import timeline as timeline_service
from app.applications.ai import context as app_ai_context
from app.applications.ai import followup as followup_service
from app.applications.ai import interview_prep as interview_prep_service
from app.applications.ai.signals import compute_signals
from app.career_copilot import context_engine
from app.intelligence import candidate as candidate_intel
from app.models.domain import (
    Application,
    ApplicationInterview,
    Job,
    Resume,
    ResumeAnalysis,
    SavedJob,
    User,
)
from app.notifications import service as notifications_service
from app.recommendations import service as recommendation_service
from app.resume_ai import pipeline as resume_pipeline
from app.resume_ai import recommendations as resume_recommendations
from app.search import service as search_service
from app.search.document import EntityType
from app.search.permissions import SearchActor
from app.search.provider import SearchFilters
from app.skill_intelligence import gap as gap_engine
from app.skill_intelligence import learning_path as learning_path_engine
from app.skill_intelligence import readiness as readiness_engine


class ToolInputError(ValueError):
    """A tool was called with parameters that don't make sense for
    this user's data (e.g. an application id they don't own). Always
    caught by agent_service and turned into a plain-language reply —
    never a raw 500 and never silently ignored."""


# ---------------------------------------------------------------------------
# READ — job discovery & recommendations (spec sections 5, 6)
# ---------------------------------------------------------------------------


def search_jobs(
    db,
    user: User,
    *,
    query: str = "",
    location: str | None = None,
    job_type: str | None = None,
    work_mode: str | None = None,
    skills: list[str] | None = None,
    experience: str | None = None,
    limit: int = 10,
) -> dict:
    """Converts already-structured filters (extracted by intent.py from
    the candidate's natural-language request — see that module's
    docstring for the extraction step) into a single call to the
    existing V21.1 search infrastructure. No SQL is built here or
    anywhere upstream of this call."""

    filters = SearchFilters(
        entity_types=[EntityType.JOB, EntityType.GOVERNMENT_RECRUITMENT, EntityType.INTERNSHIP, EntityType.APPRENTICESHIP],
        location=location,
        job_type=job_type,
        work_mode=work_mode,
        skills=skills or None,
        experience=experience,
    )
    result = search_service.run_search(
        db,
        query=query or "",
        filters=filters,
        entity_types=filters.entity_types,
        page=1,
        page_size=max(1, min(limit, 25)),
        sort="relevance",
        actor=SearchActor.from_user(user),
        log_analytics=True,
    )
    return {
        "total_count": result.total_count,
        "jobs": [item.model_dump(mode="json") for item in result.items],
    }


def get_job_details(db, user: User, *, job_id: int) -> dict:
    try:
        job = get_public_job(job_id, db)
    except HTTPException as exc:
        raise ToolInputError(str(exc.detail)) from exc
    return {
        "id": job.id,
        "title": job.title,
        "organization": job.organization,
        "job_type": job.job_type,
        "location": job.location,
        "work_mode": job.work_mode,
        "employment_type": job.employment_type,
        "salary": job.salary,
        "deadline": job.deadline.isoformat() if job.deadline else None,
        "qualification": job.qualification,
        "skills": job.skills,
        "apply_url": job.apply_url,
        "notification_url": job.notification_url,
        "description": job.description,
    }


def get_job_recommendations(db, user: User, *, limit: int = 10, category: str | None = None) -> dict:
    result = recommendation_service.get_recommendations(db, user, limit=limit, category=category)
    return {
        "is_cold_start": result.is_cold_start,
        "total_before_limit": result.total_before_limit,
        "items": [
            {
                "job_id": item.job_id,
                "title": item.title,
                "organization": item.organization,
                "location": item.location,
                "deadline": item.deadline,
                "overall_score": item.overall_score,
                "category": item.category,
                "explanation_summary": item.explanation_summary,
                "matched_skills": item.matched_skills,
                "missing_skills": item.missing_skills,
                "already_saved": item.already_saved,
                "already_applied": item.already_applied,
            }
            for item in result.items
        ],
    }


def get_saved_jobs(db, user: User, *, limit: int = 20) -> dict:
    rows = db.execute(
        select(Job)
        .join(SavedJob, SavedJob.job_id == Job.id)
        .where(SavedJob.user_id == user.id)
        .order_by(SavedJob.id.desc())
        .limit(max(1, min(limit, 50)))
    ).scalars().all()
    return {
        "saved_jobs": [
            {
                "id": j.id,
                "title": j.title,
                "organization": j.organization,
                "job_type": j.job_type,
                "deadline": j.deadline.isoformat() if j.deadline else None,
            }
            for j in rows
        ]
    }


# ---------------------------------------------------------------------------
# READ — skills & career intelligence (spec sections 5, 13)
# ---------------------------------------------------------------------------


def analyze_skill_gap(db, user: User, *, target_job_id: int | None = None) -> dict:
    result = gap_engine.compute(db, user.id, target_job_id)
    return {
        "priority_skills": [
            {"skill": item.display_name, "reason": item.reason, "priority_score": item.priority_score}
            for item in result.priority_skills
        ],
        "recommended_skills": [
            {"skill": item.display_name, "reason": item.reason} for item in result.recommended_skills
        ],
        "unrecognized_skill_inputs": result.unrecognized_inputs,
    }


def get_career_intelligence(db, user: User, *, target_role: str | None = None) -> dict:
    return candidate_intel.overview(db, user.id, explicit_role=target_role)


def get_learning_recommendations(db, user: User, *, target_job_id: int | None = None) -> dict:
    draft = learning_path_engine.build(db, user.id, target_job_id)
    return {
        "steps": [
            {
                "skill": step.skill.display_name,
                "reason": step.reason,
                "resource_title": step.resource.title if step.resource else None,
                "resource_url": step.resource.url if step.resource else None,
            }
            for step in draft.steps
        ],
        "unresourced_skill_names": draft.unresourced_skill_names,
    }


def summarize_career_progress(db, user: User) -> dict:
    """Deterministic composition of already-computed data — no new
    scoring, matches spec section 25 ("do not call an LLM for
    deterministic operations")."""

    context = context_engine.build(db, user.id)
    dashboard = applications_service.get_dashboard(db, user.id)
    readiness = readiness_engine.compute(db, user.id)
    return {
        "applications": dashboard,
        "saved_jobs_count": len(context.saved_jobs),
        "upcoming_deadlines": context.upcoming_deadlines,
        "skill_intelligence": context.skill_intelligence,
        "role_readiness": readiness.role_readiness,
        "unknown_fields": context.unknown_fields,
    }


# ---------------------------------------------------------------------------
# READ / WRITE — applications (spec sections 9, 10)
# ---------------------------------------------------------------------------


def get_application(db, user: User, *, application_id: int) -> dict:
    try:
        app_row = applications_service.get_application(db, user.id, application_id)
    except Exception as exc:  # service raises a not-found error subclass
        raise ToolInputError(f"Application {application_id} not found") from exc
    return _application_out(app_row)


def list_applications(db, user: User, *, status: str | None = None, limit: int = 20) -> dict:
    items, total = applications_service.list_applications(
        db, user.id, filters=applications_service.ApplicationFilters(status=status), limit=max(1, min(limit, 50))
    )
    return {"total": total, "applications": [_application_out(a) for a in items]}


def get_application_timeline(db, user: User, *, application_id: int) -> dict:
    try:
        applications_service.get_application(db, user.id, application_id)
    except Exception as exc:
        raise ToolInputError(f"Application {application_id} not found") from exc
    return {"timeline": timeline_service.get_timeline(db, user.id, application_id)}


def create_application_task(
    db, user: User, *, application_id: int, title: str, description: str | None = None, due_in_days: int | None = None
) -> dict:
    due_at = None
    if due_in_days is not None:
        due_at = datetime.utcnow() + timedelta(days=max(0, due_in_days))
    try:
        task = tasks_service.create_task(db, user.id, application_id, title=title, description=description, due_at=due_at)
    except (tasks_service.InvalidTaskError, applications_service.ApplicationNotFoundError) as exc:
        raise ToolInputError(str(exc)) from exc
    return {
        "task_id": task.id,
        "title": task.title,
        "due_at": task.due_at.isoformat() if task.due_at else None,
    }


def schedule_follow_up(db, user: User, *, application_id: int, follow_up_in_days: int = 5) -> dict:
    """A follow-up "reminder" is an ApplicationTask with a due date —
    reusing V22.3 task infrastructure rather than inventing a second
    reminder system (spec section 10)."""

    app_row = get_application(db, user, application_id=application_id)
    return create_application_task(
        db,
        user,
        application_id=application_id,
        title=f"Follow up on application to {app_row['company']}",
        description="Follow-up reminder created by the Career Agent.",
        due_in_days=max(0, follow_up_in_days),
    )


def prepare_interview(db, user: User, *, application_id: int, interview_id: int | None = None) -> dict:
    try:
        app_row = applications_service.get_application(db, user.id, application_id)
    except Exception as exc:
        raise ToolInputError(f"Application {application_id} not found") from exc

    signals = compute_signals(db, app_row)
    interview = None
    if interview_id is not None:
        interview = db.get(ApplicationInterview, interview_id)
        if not interview or interview.application_id != application_id:
            raise ToolInputError(f"Interview {interview_id} not found on this application")
    else:
        interview = signals.upcoming_interview or db.scalar(
            select(ApplicationInterview)
            .where(ApplicationInterview.application_id == application_id)
            .order_by(ApplicationInterview.created_at.desc())
            .limit(1)
        )
    if interview is None:
        return {"available": False, "reason": "No interview is on file for this application yet."}

    ctx = app_ai_context.build(db, app_row, signals)
    result, from_cache = interview_prep_service.generate(db, ctx, interview, user_id=user.id, force=False)
    return {"available": True, "interview_id": interview.id, "from_cache": from_cache, **result}


# ---------------------------------------------------------------------------
# READ — resume (spec section 12)
# ---------------------------------------------------------------------------


def analyze_resume(db, user: User, *, refresh: bool = False) -> dict:
    resume = db.get(Resume, user.id)
    if not resume:
        return {"available": False, "reason": "No resume uploaded yet — upload one via the Resume page first."}

    existing = db.get(ResumeAnalysis, user.id) if not refresh else None
    if not existing:
        existing = resume_pipeline.run_and_persist(db, resume)

    profile = resume_pipeline.build_profile(resume)
    recs = resume_recommendations.generate(profile)
    return {
        "available": True,
        "scores": _json.loads(existing.scores_json),
        "missing_sections": _json.loads(existing.profile_json).get("missing_sections", []),
        "recommendations": [asdict(r) for r in recs],
    }


# ---------------------------------------------------------------------------
# READ — notifications (spec section 21)
# ---------------------------------------------------------------------------


def get_notifications(db, user: User, *, unread_only: bool = True, limit: int = 10) -> dict:
    items, total = notifications_service.list_notifications(db, user.id, unread_only=unread_only, limit=max(1, min(limit, 30)))
    return {
        "total": total,
        "notifications": [
            {
                "id": n.id,
                "title": n.title,
                "message": n.message,
                "category": n.category,
                "priority": n.priority,
                "created_at": n.created_at.isoformat(),
            }
            for n in items
        ],
    }


# ---------------------------------------------------------------------------
# HIGH_RISK — external actions (spec sections 19, 20)
#
# CareerOS currently supports only external application links
# (Job.apply_url) — there is no integration that actually submits an
# application or sends a message on the candidate's behalf. Both tools
# below are honest about that: they prepare information and, on
# confirmation, return it for the candidate to act on themselves —
# NEVER a claim of success for something that didn't happen (spec
# section 23).
# ---------------------------------------------------------------------------


def submit_application(db, user: User, *, job_id: int) -> dict:
    try:
        job = get_public_job(job_id, db)
    except HTTPException as exc:
        raise ToolInputError(str(exc.detail)) from exc
    if not job.apply_url:
        return {
            "submitted": False,
            "reason": "This job has no application link on file. Check the official notification directly.",
        }
    return {
        "submitted": False,
        "apply_url": job.apply_url,
        "note": (
            "CareerOS does not submit applications on your behalf. Opening the official application "
            "link is the next step — nothing has been submitted yet."
        ),
    }


def draft_followup_message(db, user: User, *, application_id: int, tone: str = "PROFESSIONAL") -> dict:
    try:
        app_row = applications_service.get_application(db, user.id, application_id)
    except Exception as exc:
        raise ToolInputError(f"Application {application_id} not found") from exc

    signals = compute_signals(db, app_row)
    ctx = app_ai_context.build(db, app_row, signals)
    result, from_cache = followup_service.generate(db, ctx, user_id=user.id, tone=tone)
    return {
        "sent": False,
        "draft": result,
        "recipient_on_file": app_row.recruiter_email,
        "note": (
            "CareerOS has no connected channel to send this automatically — the message above is a "
            "draft for you to review and send yourself."
        ),
    }


def _application_out(a: Application) -> dict:
    return {
        "id": a.id,
        "company": a.company,
        "job_title": a.job_title or a.role,
        "status": a.status,
        "deadline": a.deadline.isoformat() if a.deadline else None,
        "applied_at": a.applied_on.isoformat() if a.applied_on else None,
        "next_deadline": a.next_deadline.isoformat() if a.next_deadline else None,
    }
