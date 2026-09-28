"""V20.2 — AI Resume Intelligence APIs.

Reuses, never rewrites: ``get_public_job`` (app.api.platform),
``current_user``/``require_recruiter`` (app.core.security),
``team_owner_ids`` (app.core.team_access), and the V8 ``Resume`` model
— all imported, none modified beyond the one additive column noted in
CHANGELOG_V20_2.md.

Auth split:
- Candidate endpoints (``/resume-ai/analysis``, ``/ats``,
  ``/job-match/*``, ``/skill-gap/*``, ``/recommendations``,
  ``/bullet-improve``, ``/summary``, ``/project-improve``,
  ``/job-advice/*``) operate only on the calling user's own stored
  resume — there is no "resume_id" parameter anywhere a candidate
  could pass someone else's.
- The recruiter endpoint (``/resume-ai/applicant/{applicant_id}``)
  reuses the exact ownership check recruiter.py's own endpoints use
  (a job owned by anyone on the recruiter's team, via
  ``team_owner_ids``) and reads only ``Applicant.resume_snapshot`` —
  never the candidate's live ``Resume`` row — the same privacy
  boundary ``Applicant``'s own docstring establishes. No new
  candidate PII is exposed beyond what recruiter.py already shows.
- ``/resume-ai/usage`` is admin-only, reusing ``app.api.admin.guard``
  exactly like ``app.api.ai``'s usage endpoints.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import observability
from app.api.admin import guard as admin_guard
from app.api.platform import get_public_job
from app.core.rate_limit import enforce_rate_limit
from app.core.security import current_user, require_recruiter
from app.core.team_access import team_owner_ids
from app.db.session import get_db
from app.models.domain import Applicant, Resume, ResumeAnalysis, ResumeJobMatch, User
from app.resume_ai import bullet_improver, cache, job_advice, job_match, pipeline, project_improver, recommendations, skill_gap, summary_generator

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _own_resume_or_404(db: Session, u: User) -> Resume:
    resume = db.get(Resume, u.id)
    if not resume:
        raise HTTPException(404, "Upload a resume first via POST /resume")
    return resume


def _owned_applicant_or_404(db: Session, applicant_id: int, recruiter: User) -> Applicant:
    """Mirrors app.api.recruiter._owned_applicant_or_404 exactly (team
    ownership via the underlying job) — kept as its own copy rather
    than importing recruiter.py's private helper, matching this
    codebase's existing convention that underscore-prefixed helpers
    are module-local, not shared."""
    from app.models.domain import Job

    applicant = db.get(Applicant, applicant_id)
    if not applicant:
        raise HTTPException(404, "Applicant not found")
    job = db.get(Job, applicant.job_id)
    if not job or job.owner_user_id not in team_owner_ids(db, recruiter):
        raise HTTPException(404, "Applicant not found")
    return applicant, job


# ---------------------------------------------------------------------------
# Analysis (candidate)
# ---------------------------------------------------------------------------


@router.get("/resume-ai/analysis")
def get_analysis(refresh: bool = False, u: User = Depends(current_user), db: Session = Depends(get_db)):
    resume = _own_resume_or_404(db, u)
    existing = db.get(ResumeAnalysis, u.id) if not refresh else None
    if not existing:
        existing = pipeline.run_and_persist(db, resume)
    return {
        "profile": json.loads(existing.profile_json),
        "scores": json.loads(existing.scores_json),
        "analyzed_at": existing.analyzed_at.isoformat(),
    }


@router.get("/resume-ai/ats")
def get_ats(refresh: bool = False, u: User = Depends(current_user), db: Session = Depends(get_db)):
    resume = _own_resume_or_404(db, u)
    existing = db.get(ResumeAnalysis, u.id) if not refresh else None
    if not existing:
        existing = pipeline.run_and_persist(db, resume)
    return json.loads(existing.scores_json)["ats"]


@router.get("/resume-ai/recommendations")
def get_recommendations(u: User = Depends(current_user), db: Session = Depends(get_db)):
    resume = _own_resume_or_404(db, u)
    profile = pipeline.build_profile(resume)
    recs = recommendations.generate(profile)
    return {"recommendations": [asdict(r) for r in recs]}


# ---------------------------------------------------------------------------
# Job match / skill gap (candidate)
# ---------------------------------------------------------------------------


def _compute_and_cache_match(db: Session, u: User, job_id: int) -> tuple[dict, dict]:
    job = get_public_job(job_id, db)
    resume = _own_resume_or_404(db, u)
    profile = pipeline.build_profile(resume)

    from app.models.domain import Profile

    candidate_profile = db.get(Profile, u.id)
    match_result = job_match.match(resume.extracted_text, profile, job, candidate_profile)
    gap_result = skill_gap.analyze(profile, job)

    row = db.execute(select(ResumeJobMatch).where(ResumeJobMatch.user_id == u.id, ResumeJobMatch.job_id == job_id)).scalar_one_or_none()
    row = row or ResumeJobMatch(user_id=u.id, job_id=job_id, overall_score=0, skills_score=0, experience_score=0, education_score=0, keywords_score=0, result_json="{}")
    row.overall_score = match_result.overall
    row.skills_score = match_result.skills.score
    row.experience_score = match_result.experience.score
    row.education_score = match_result.education.score
    row.keywords_score = match_result.keywords.score
    row.result_json = json.dumps({"match": asdict(match_result), "skill_gap": asdict(gap_result)})
    db.add(row)
    db.commit()

    return asdict(match_result), asdict(gap_result)


@router.get("/resume-ai/job-match/{job_id}")
def get_job_match(job_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    match_result, gap_result = _compute_and_cache_match(db, u, job_id)
    return {"match": match_result, "skill_gap": gap_result}


@router.get("/resume-ai/skill-gap/{job_id}")
def get_skill_gap(job_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    _, gap_result = _compute_and_cache_match(db, u, job_id)
    return gap_result


@router.get("/resume-ai/job-advice/{job_id}")
def get_job_advice(job_id: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    job = get_public_job(job_id, db)
    resume = _own_resume_or_404(db, u)
    profile = pipeline.build_profile(resume)

    from app.models.domain import Profile

    candidate_profile = db.get(Profile, u.id)
    match_result = job_match.match(resume.extracted_text, profile, job, candidate_profile)
    gap_result = skill_gap.analyze(profile, job)

    context_key = cache.make_context_key("job_advice", str(job_id), resume.extracted_text[:2000])
    cached = cache.get_cached(db, user_id=u.id, kind="job_advice", context_key=context_key)
    if cached:
        return {
            **_structured_advice_from_row(profile, match_result, gap_result),
            "narrative": cached.content,
            "source": "cache",
            "provider": cached.provider,
            "model": cached.model,
        }

    result = job_advice.build(db, profile, match_result, gap_result, user_id=u.id)
    if result.get("narrative"):
        cache.store(db, user_id=u.id, kind="job_advice", context_key=context_key, content=result["narrative"], provider=result.get("provider"), model=result.get("model"))
    return result


def _structured_advice_from_row(profile, match_result, gap_result) -> dict:
    return {
        "missing_keywords": gap_result.missing_skills,
        "recommended_keywords": gap_result.recommended_skills,
        "skills_to_highlight": match_result.matched_skills,
        "projects_to_highlight": profile.project_entries[:3],
        "experience_to_highlight": profile.experience_entries[:3],
        "sections_to_improve": [],
    }


# ---------------------------------------------------------------------------
# Generative endpoints (candidate) — rate-limited, cached
# ---------------------------------------------------------------------------


class BulletIn(BaseModel):
    bullet: str = Field(min_length=3, max_length=500)


class SummaryIn(BaseModel):
    target_role: str = Field(min_length=2, max_length=80)


class ProjectIn(BaseModel):
    project_text: str = Field(min_length=3, max_length=2000)


@router.post("/resume-ai/bullet-improve")
def post_bullet_improve(payload: BulletIn, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    enforce_rate_limit(request, "resume-ai-generate", limit=20, window=60)

    context_key = cache.make_context_key("bullet", payload.bullet)
    cached = cache.get_cached(db, user_id=u.id, kind="bullet_improve", context_key=context_key)
    if cached:
        return {"variants": json.loads(cached.content), "source": "cache", "provider": cached.provider, "model": cached.model}

    result = bullet_improver.improve(db, payload.bullet, user_id=u.id)
    if result["source"] == "ai":
        cache.store(db, user_id=u.id, kind="bullet_improve", context_key=context_key, content=json.dumps(result["variants"]), provider=result["provider"], model=result["model"])
    return result


@router.post("/resume-ai/summary")
def post_summary(payload: SummaryIn, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    enforce_rate_limit(request, "resume-ai-generate", limit=20, window=60)

    resume = _own_resume_or_404(db, u)
    profile = pipeline.build_profile(resume)

    context_key = cache.make_context_key("summary", payload.target_role.lower().strip(), resume.extracted_text[:2000])
    cached = cache.get_cached(db, user_id=u.id, kind="summary", context_key=context_key)
    if cached:
        return {"summary": cached.content, "source": "cache", "provider": cached.provider, "model": cached.model}

    result = summary_generator.generate(db, profile, payload.target_role, user_id=u.id)
    if result["source"] == "ai":
        cache.store(db, user_id=u.id, kind="summary", context_key=context_key, content=result["summary"], provider=result["provider"], model=result["model"])
    return result


@router.post("/resume-ai/project-improve")
def post_project_improve(payload: ProjectIn, request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    enforce_rate_limit(request, "resume-ai-generate", limit=20, window=60)

    context_key = cache.make_context_key("project", payload.project_text)
    cached = cache.get_cached(db, user_id=u.id, kind="project_improve", context_key=context_key)
    if cached:
        return {"suggestions": json.loads(cached.content), "source": "cache", "provider": cached.provider, "model": cached.model}

    result = project_improver.improve(db, payload.project_text, user_id=u.id)
    if result["source"] == "ai":
        cache.store(db, user_id=u.id, kind="project_improve", context_key=context_key, content=json.dumps(result["suggestions"]), provider=result["provider"], model=result["model"])
    return result


# ---------------------------------------------------------------------------
# Recruiter integration
# ---------------------------------------------------------------------------


@router.get("/resume-ai/applicant/{applicant_id}/analysis")
def get_applicant_analysis(applicant_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Recruiter view: analyzes the applicant's resume snapshot (as it
    was at the moment they applied — see Applicant.resume_snapshot)
    against the job they applied to. Never touches the candidate's
    live Resume row, and exposes nothing beyond what recruiter.py's
    own applicant endpoints already show this recruiter."""
    applicant, job = _owned_applicant_or_404(db, applicant_id, recruiter)
    if not applicant.resume_snapshot:
        raise HTTPException(404, "This applicant did not submit a resume")

    profile = pipeline.profile_from_text(applicant.resume_snapshot)
    scores = pipeline.analyze_and_score(profile, has_tables_or_columns=None)
    match_result = job_match.match(applicant.resume_snapshot, profile, job)
    gap_result = skill_gap.analyze(profile, job)

    return {
        "profile": asdict(profile),
        "scores": scores,
        "match": asdict(match_result),
        "skill_gap": asdict(gap_result),
    }


# ---------------------------------------------------------------------------
# AI usage (admin) — reuses V20.1 observability, filtered to resume_ai operations
# ---------------------------------------------------------------------------


@router.get("/resume-ai/usage", dependencies=[Depends(admin_guard)])
def resume_ai_usage(since_hours: int = Query(default=24, ge=1, le=24 * 30), db: Session = Depends(get_db)):
    summary = observability.usage_summary(db, since_hours=since_hours)
    logs = observability.recent_logs(db, limit=100)
    resume_ai_logs = [row for row in logs if (row.operation or "").startswith("resume_ai.")]
    return {
        "since_hours": since_hours,
        "overall_ai_usage": summary,
        "recent_resume_ai_calls": [
            {
                "operation": row.operation,
                "provider": row.provider,
                "model": row.model,
                "success": row.success,
                "latency_ms": row.latency_ms,
                "cost_estimate_usd": row.cost_estimate_usd,
                "created_at": row.created_at.isoformat(),
            }
            for row in resume_ai_logs
        ],
    }
