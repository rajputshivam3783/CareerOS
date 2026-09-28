"""Public opportunity engine (V1-V3), personalization (V4-V5), matching
(V6), and application tracking (V7-V8) — grouped in one router since they
share the same public/candidate surface."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.core.security import current_user
from app.db.session import get_db
from app.models.domain import Alert, Applicant, Application, ExamPrepResource, Interview, Job, Notification, OfferLetter, Profile, RecruiterPipelineHistory, RecruitmentUpdate, Resume, ResumeAISuggestion, ResumeAnalysis, SavedJob
from app.services.career import match_score, skill_gap
from app.services.career_ai import generate_advice
from app.services.eligibility import eligibility as calc_eligibility
from app.services.resume_match import learning_roadmap, match_resume_to_job
from app.services.resume_parser import detect_skills, extract_resume_text
# V20.2 — AI Resume Intelligence. Import kept local to this one call
# site (not a top-level dependency of the whole module) since it's
# only needed for the one-time, upload-time layout signal below.
from app.services.semantic_search import rank_by_similarity

router = APIRouter()


def _escape_like(value: str) -> str:
    """Escape SQL LIKE wildcards so a search for e.g. "50%" or "a_b"
    matches literally instead of behaving like a wildcard pattern."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def get_public_job(job_id: int, db: Session) -> Job:
    job = db.get(Job, job_id)
    if not job or job.status != "published":
        raise HTTPException(404, "Job not found")
    return job


@router.get("/jobs")
def jobs(
    response: Response,
    search: str | None = None,
    job_type: str | None = None,
    location: str | None = None,
    category: str | None = None,
    verified: bool | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = select(Job).where(Job.status == "published")

    if search:
        term = f"%{_escape_like(search)}%"
        q = q.where(
            or_(
                Job.title.ilike(term, escape="\\"),
                Job.organization.ilike(term, escape="\\"),
                Job.description.ilike(term, escape="\\"),
                Job.qualification.ilike(term, escape="\\"),
            )
        )
    if job_type:
        q = q.where(Job.job_type.ilike(job_type, escape="\\"))
    if location:
        q = q.where(Job.location.ilike(f"%{_escape_like(location)}%", escape="\\"))
    if category:
        q = q.where(Job.category.ilike(f"%{_escape_like(category)}%", escape="\\"))
    if verified is not None:
        q = q.where(Job.verified == verified)

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    response.headers["X-Total-Count"] = str(total)

    return db.scalars(
        q.order_by(Job.deadline.asc().nullslast(), Job.id.desc()).offset(offset).limit(limit)
    ).all()


@router.get("/jobs/{job_id}")
def job(job_id: int, db: Session = Depends(get_db)):
    return get_public_job(job_id, db)


_GOVT_SECTIONS = {
    "latest-jobs": None,
    "results": "result",
    "admit-cards": "admit_card",
    "answer-keys": "answer_key",
    "admissions": "admission",
    "syllabus": "syllabus",
    "exam-dates": "exam_date",
    "important-notices": "notice",
    # V16 — the rest of a real recruitment's lifecycle, past the result.
    "cutoffs": "cutoff",
    "merit-lists": "merit_list",
    "document-verification": "dv",
    "counselling": "counselling",
    "joining": "joining",
    # V19.3 — Government Portal. Fills out the remaining lifecycle
    # stages already present in RECRUITMENT_UPDATE_TYPES since V19.1
    # but not yet exposed as their own section here.
    "medical-examination": "medical",
    "final-selection": "final_selection",
    "cancelled-recruitments": "cancelled",
    # V16 — these aren't lifecycle events on an existing recruitment;
    # they're their own opportunity listings, filtered by Job.category
    # instead of RecruitmentUpdate.update_type. A recruiter/admin marks
    # a Government-type job with one of these categories the same way
    # any other category is set today — no schema change.
    "scholarships": ("category", "Scholarship"),
    "government-internships": ("category", "Government Internship"),
    "research-fellowships": ("category", "Research Fellowship"),
    # V19.3 — a distinct third kind: filtered by Job.status/archived_at
    # rather than update_type or category. "archive" surfaces
    # recruitments that have run their course (closed or archived),
    # kept queryable rather than deleted.
    "archive": ("archived", None),
}



@router.get("/government/coverage")
def government_coverage():
    from app.ingestion.source_catalog import TIER_A, COVERAGE_TARGETS
    return {
        "implemented_official_collectors": TIER_A,
        "maintained_expansion_targets": COVERAGE_TARGETS,
        "policy": (
            "These collectors are implemented but not independently verified against "
            "today's live site markup, so none are enabled by default (see "
            "app/ingestion/sources.py) — an operator must confirm each source's current "
            "page structure before turning it on. Every discovered record enters admin "
            "review before publication either way; nothing here auto-publishes."
        ),
    }

@router.get("/government/filters")
def government_filters(db: Session = Depends(get_db)):
    """V19.3 — real facet values drawn from published Government jobs,
    not a hardcoded list. An operator's adapters ultimately decide
    what govt_level/category values exist; this reflects that data
    rather than assuming a fixed taxonomy that may not match what's
    actually been ingested (see 'Do NOT hardcode recruitment data')."""
    govt = Job.status == "published"
    government = Job.job_type.ilike("Government")
    govt_levels = db.scalars(
        select(Job.govt_level).where(govt, government, Job.govt_level.is_not(None)).distinct()
    ).all()
    categories = db.scalars(
        select(Job.category).where(govt, government, Job.category.is_not(None)).distinct()
    ).all()
    organizations = db.scalars(
        select(Job.organization).where(govt, government).distinct().order_by(Job.organization.asc())
    ).all()
    return {
        "govt_levels": sorted(v for v in govt_levels if v),
        "categories": sorted(v for v in categories if v),
        "organizations": sorted(v for v in organizations if v),
    }


@router.get("/government/search")
def government_advanced_search(
    response: Response,
    organization: str | None = None,
    exam: str | None = None,
    post: str | None = None,
    qualification: str | None = None,
    location: str | None = None,
    ad_number: str | None = None,
    govt_level: str | None = None,
    category: str | None = None,
    sort: str = Query("newest", pattern="^(newest|deadline|vacancies|organization)$"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """V19.3 — one advanced-search endpoint across every published
    Government job, by the fields a recruitment portal's users
    actually search by: organization, exam (title/category), post
    (title), qualification, location, and advertisement number.
    'exam' and 'post' both search Job.title — a recruitment listing
    doesn't distinguish the two as separate stored fields, so both
    terms narrow the same title match rather than requiring a second
    schema field."""
    q = select(Job).where(Job.status == "published", Job.job_type.ilike("Government"))
    if exam:
        term = f"%{_escape_like(exam)}%"
        q = q.where(or_(Job.title.ilike(term, escape="\\"), Job.category.ilike(term, escape="\\")))
    if post:
        q = q.where(Job.title.ilike(f"%{_escape_like(post)}%", escape="\\"))
    q = _apply_job_filters(q, None, organization, qualification, ad_number, location, govt_level, category)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    response.headers["X-Total-Count"] = str(total)
    return db.scalars(q.order_by(_SORT_COLUMNS[sort], Job.id.desc()).offset(offset).limit(limit)).all()


@router.get("/government/home")
def government_home(db: Session = Depends(get_db)):
    """Aggregated Sarkari-style government recruitment dashboard."""
    govt = Job.status == "published"
    government = Job.job_type.ilike("Government")
    latest = db.scalars(
        select(Job).where(govt, government).order_by(Job.id.desc()).limit(12)
    ).all()
    closing = db.scalars(
        select(Job).where(govt, government, Job.deadline.is_not(None), Job.deadline >= date.today())
        .order_by(Job.deadline.asc()).limit(12)
    ).all()
    counts = {"latest_jobs": db.scalar(select(func.count()).select_from(Job).where(govt, government))}
    for slug, typ in _GOVT_SECTIONS.items():
        if typ is None:
            continue
        if isinstance(typ, tuple):
            kind, value = typ
            if kind == "archived":
                counts[slug.replace("-", "_")] = db.scalar(
                    select(func.count()).select_from(Job)
                    .where(government, Job.status.in_(("archived", "closed")))
                )
            else:
                counts[slug.replace("-", "_")] = db.scalar(
                    select(func.count()).select_from(Job)
                    .where(govt, government, Job.category == value)
                )
        else:
            counts[slug.replace("-", "_")] = db.scalar(
                select(func.count()).select_from(RecruitmentUpdate)
                .join(Job, Job.id == RecruitmentUpdate.job_id)
                .where(Job.status == "published", Job.job_type.ilike("Government"),
                       RecruitmentUpdate.status == "published", RecruitmentUpdate.update_type == typ)
            )
    return {"counts": counts, "latest_jobs": latest, "closing_soon": closing}


_SORT_COLUMNS = {
    "newest": Job.id.desc(),
    "deadline": Job.deadline.asc().nullslast(),
    "vacancies": Job.vacancies.desc().nullslast(),
    "organization": Job.organization.asc(),
}


def _apply_job_filters(q, search, organization, qualification, ad_number, location, govt_level, category):
    if search:
        term = f"%{_escape_like(search)}%"
        q = q.where(or_(
            Job.title.ilike(term, escape="\\"), Job.organization.ilike(term, escape="\\"),
            Job.qualification.ilike(term, escape="\\"), Job.ad_number.ilike(term, escape="\\"),
        ))
    if organization:
        q = q.where(Job.organization.ilike(f"%{_escape_like(organization)}%", escape="\\"))
    if qualification:
        q = q.where(Job.qualification.ilike(f"%{_escape_like(qualification)}%", escape="\\"))
    if ad_number:
        q = q.where(Job.ad_number.ilike(f"%{_escape_like(ad_number)}%", escape="\\"))
    if location:
        q = q.where(Job.location.ilike(f"%{_escape_like(location)}%", escape="\\"))
    if govt_level:
        q = q.where(Job.govt_level.ilike(govt_level, escape="\\"))
    if category:
        q = q.where(Job.category.ilike(f"%{_escape_like(category)}%", escape="\\"))
    return q


@router.get("/government/sections/{section}")
def government_section(
    response: Response,
    section: str,
    search: str | None = None,
    organization: str | None = None,
    qualification: str | None = None,
    ad_number: str | None = None,
    location: str | None = None,
    govt_level: str | None = None,
    category: str | None = None,
    sort: str = Query("newest", pattern="^(newest|deadline|vacancies|organization)$"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    if section not in _GOVT_SECTIONS:
        raise HTTPException(404, "Unknown government section")
    typ = _GOVT_SECTIONS[section]

    if typ is None or (isinstance(typ, tuple) and typ[0] in ("category", "archived")):
        if isinstance(typ, tuple) and typ[0] == "archived":
            q = select(Job).where(Job.job_type.ilike("Government"), Job.status.in_(("archived", "closed")))
        else:
            q = select(Job).where(Job.status == "published", Job.job_type.ilike("Government"))
            if isinstance(typ, tuple):
                q = q.where(Job.category == typ[1])
        q = _apply_job_filters(q, search, organization, qualification, ad_number, location, govt_level, category)
        total = db.scalar(select(func.count()).select_from(q.subquery()))
        response.headers["X-Total-Count"] = str(total)
        return db.scalars(q.order_by(_SORT_COLUMNS[sort], Job.id.desc()).offset(offset).limit(limit)).all()

    q = (
        select(RecruitmentUpdate, Job)
        .join(Job, Job.id == RecruitmentUpdate.job_id)
        .where(Job.status == "published", Job.job_type.ilike("Government"),
               RecruitmentUpdate.status == "published", RecruitmentUpdate.update_type == typ)
    )
    if search:
        term=f"%{_escape_like(search)}%"
        q=q.where(or_(RecruitmentUpdate.title.ilike(term,escape="\\"),Job.title.ilike(term,escape="\\"),
                      Job.organization.ilike(term,escape="\\")))
    if organization:
        q=q.where(Job.organization.ilike(f"%{_escape_like(organization)}%",escape="\\"))
    if govt_level:
        q=q.where(Job.govt_level.ilike(govt_level,escape="\\"))
    if category:
        q=q.where(Job.category.ilike(f"%{_escape_like(category)}%",escape="\\"))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    response.headers["X-Total-Count"] = str(total)
    rows=db.execute(q.order_by(RecruitmentUpdate.event_date.desc().nullslast(),
                               RecruitmentUpdate.id.desc()).offset(offset).limit(limit)).all()
    return [{"update": u, "job": j} for u,j in rows]


@router.get("/jobs/{job_id}/timeline")
def recruitment_timeline(job_id: int, db: Session = Depends(get_db)):
    job = get_public_job(job_id, db)
    updates = db.scalars(
        select(RecruitmentUpdate)
        .where(RecruitmentUpdate.job_id == job_id, RecruitmentUpdate.status == "published")
        .order_by(RecruitmentUpdate.event_date.asc().nullsfirst(), RecruitmentUpdate.id.asc())
    ).all()
    return {"job": job, "updates": updates}


@router.get("/jobs/{job_id}/exam-prep")
def exam_prep(job_id: int, db: Session = Depends(get_db)):
    """V8 — admin-curated exam-prep links for this job (syllabus,
    previous-year papers, mock tests, cutoffs). Falls back to any
    resources curated for the same organization+exam name if none are
    tied to this specific posting, since prep material for a recurring
    exam usually outlives one year's job listing.
    """
    job = get_public_job(job_id, db)

    direct = db.scalars(
        select(ExamPrepResource).where(ExamPrepResource.job_id == job_id)
    ).all()
    if direct:
        return direct

    return db.scalars(
        select(ExamPrepResource).where(
            ExamPrepResource.job_id.is_(None),
            ExamPrepResource.organization == job.organization,
        )
    ).all()


@router.get("/search/semantic")
def semantic_search(
    q: str = Query(min_length=2, max_length=300),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """V6 semantic-ish search: ranks published jobs by TF-IDF cosine
    similarity to a free-text query rather than requiring an exact
    keyword match. See app/services/semantic_search.py for what
    "semantic" does and doesn't mean here.
    """
    candidate_jobs = db.scalars(select(Job).where(Job.status == "published").limit(500)).all()
    ranked = rank_by_similarity(q, candidate_jobs, top_k=limit)
    return [{"job": r["job"], "similarity": r["score"]} for r in ranked]


class ProfileIn(BaseModel):
    location: str | None = None
    highest_qualification: str | None = None
    graduation_year: int | None = Field(default=None, ge=1950, le=2100)
    skills: str | None = None
    preferred_roles: str | None = None
    preferred_locations: str | None = None
    date_of_birth: date | None = None
    # V5 — optional, self-reported, used only for an indicative age-relaxation
    # estimate in the eligibility check. Never required, never inferred.
    reservation_category: str | None = None
    is_pwd: bool = False
    # V24.2 — Candidate Discovery opt-in. Defaults False: leaving this
    # unset (or explicitly False) keeps a candidate visible to
    # recruiters only through the pre-existing channel (having applied
    # to that recruiter's job). Setting it True makes the candidate's
    # profile/skills/resume-derived signals discoverable by any
    # approved recruiter via GET /recruiter/candidates, independent of
    # any specific application. See docs/V24_2_CANDIDATE_DISCOVERY.md.
    candidate_searchable: bool = False


@router.get("/profile")
def get_profile(u=Depends(current_user), db: Session = Depends(get_db)):
    return db.get(Profile, u.id) or {"user_id": u.id}


@router.put("/profile")
def profile(payload: ProfileIn, request: Request, u=Depends(current_user), db: Session = Depends(get_db)):
    enforce_rate_limit(
        request, bucket="profile-update",
        limit=settings.profile_update_rate_limit_attempts,
        window=settings.profile_update_rate_limit_window_seconds,
    )
    record = db.get(Profile, u.id) or Profile(user_id=u.id)
    for key, value in payload.model_dump().items():
        setattr(record, key, value)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/eligibility/{job_id}")
def eligibility(job_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    return calc_eligibility(get_public_job(job_id, db), db.get(Profile, u.id))


@router.get("/match/{job_id}")
def match(job_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    return match_score(get_public_job(job_id, db), db.get(Profile, u.id))


@router.get("/skill-gap/{job_id}")
def gap(job_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    return skill_gap(get_public_job(job_id, db), db.get(Profile, u.id))


@router.get("/career-ai/{job_id}")
def career_ai(job_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    """V6 Career AI — one combined view: eligibility, match score, skill
    gap, and a short natural-language summary. The summary only
    narrates these three deterministic results (see
    app/services/career_ai.py) — it never overrides them.
    """
    job = get_public_job(job_id, db)
    profile = db.get(Profile, u.id)

    eligibility_result = calc_eligibility(job, profile)
    match_result = match_score(job, profile)
    skill_gap_result = skill_gap(job, profile)
    advice = generate_advice(job, profile, eligibility_result, match_result, skill_gap_result)

    return {
        "job": job,
        "eligibility": eligibility_result,
        "match": match_result,
        "skill_gap": skill_gap_result,
        "advice": advice,
    }


@router.post("/resume", status_code=201)
async def upload_resume(
    file: UploadFile = File(...),
    u=Depends(current_user),
    db: Session = Depends(get_db),
):
    """V8 — upload a PDF/DOCX resume for matching against jobs.
    Replaces any previously stored resume; extraction is best-effort
    (see app/services/resume_parser.py) and returns which skills were
    actually detected so you can see at a glance if something didn't
    come through — e.g. a scanned-image PDF with no text layer.
    """
    from app.core.config import settings
    from app.core.uploads import read_upload_limited
    file_bytes = await read_upload_limited(
        file,
        max_bytes=settings.resume_max_upload_mb * 1024 * 1024,
        # V20.2 — AI Resume Intelligence explicitly requires TXT support
        # alongside PDF/DOCX. `.txt` was already handled by
        # extract_resume_text's plain-text fallback (app.services.
        # resume_parser) but was rejected here before ever reaching it —
        # this closes that gap rather than changing any existing
        # accepted format's behavior.
        allowed_extensions={".pdf", ".docx", ".txt"},
        allowed_content_types={
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/octet-stream",
            "text/plain",
        },
    )

    text = extract_resume_text(file.filename or "", file_bytes)
    if not text.strip():
        raise HTTPException(
            422,
            "Could not extract any text from this file — it may be a scanned image without a text layer. "
            "Try a PDF/DOCX exported directly from a word processor.",
        )

    skills = detect_skills(text)
    record = db.get(Resume, u.id) or Resume(user_id=u.id, extracted_text="", original_filename="")
    record.original_filename = file.filename or "resume"
    record.extracted_text = text
    record.skills_detected = ", ".join(skills)
    # V20.2 — AI Resume Intelligence: the tables/columns layout signal
    # can only be computed from the raw file bytes, which are never
    # persisted (only extracted_text is) — so it's captured here, once,
    # while file_bytes is still in memory, or not at all. Wrapped
    # defensively so a detection failure never breaks the upload itself
    # (the field just stays whatever it already was — None on a first
    # upload). Existing upload behavior/response is unchanged.
    try:
        from app.resume_ai.extraction import detect_tables_or_columns

        record.has_tables_or_columns = detect_tables_or_columns(file.filename or "", file_bytes)
    except Exception:
        pass
    db.add(record)
    db.commit()

    return {
        "filename": record.original_filename,
        "characters_extracted": len(text),
        "skills_detected": skills,
    }


@router.get("/resume")
def get_resume(u=Depends(current_user), db: Session = Depends(get_db)):
    record = db.get(Resume, u.id)
    if not record:
        raise HTTPException(404, "No resume uploaded yet")
    return {
        "filename": record.original_filename,
        "uploaded_at": record.uploaded_at,
        "skills_detected": (record.skills_detected or "").split(", ") if record.skills_detected else [],
        "characters_extracted": len(record.extracted_text),
    }


@router.delete("/resume", status_code=204)
def delete_resume(u=Depends(current_user), db: Session = Depends(get_db)):
    """Deletes the candidate's resume AND every piece of AI-derived
    data computed from it (V20.6 AI_DATA_RETENTION fix — these three
    tables key off user_id rather than the resume row itself, so they
    previously survived a resume deletion, leaving a full derived
    profile/score/AI-suggestion history behind after the candidate
    explicitly asked to delete their resume. See AI_PRIVACY_GUIDE.md.
    resume_job_matches (V20.2 job-match scores) is intentionally left
    alone — those rows are computed per-job and re-derivable, and
    deleting them isn't part of "delete my resume"; only the
    resume-derived analysis and AI suggestion content, which have no
    meaning without the resume, are removed."""
    record = db.get(Resume, u.id)
    if record:
        db.delete(record)
    analysis = db.get(ResumeAnalysis, u.id)
    if analysis:
        db.delete(analysis)
    db.query(ResumeAISuggestion).filter(ResumeAISuggestion.user_id == u.id).delete(synchronize_session=False)
    db.commit()


@router.get("/resume-match/{job_id}")
def resume_match(job_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    """V8 — match the candidate's stored resume against a specific
    job's description/qualification text, plus a phased learning
    roadmap for whatever's missing. Requires a resume to already be
    uploaded via POST /resume.
    """
    job = get_public_job(job_id, db)
    resume = db.get(Resume, u.id)
    if not resume:
        raise HTTPException(404, "Upload a resume first via POST /resume")

    skills = (resume.skills_detected or "").split(", ") if resume.skills_detected else []
    result = match_resume_to_job(resume.extracted_text, skills, job)
    result["roadmap"] = learning_roadmap(result["missing_skills"])
    return result


@router.get("/recommendations")
def recommendations(
    limit: int = Query(10, ge=1, le=50),
    u=Depends(current_user),
    db: Session = Depends(get_db),
):
    profile = db.get(Profile, u.id)
    candidate_jobs = db.scalars(select(Job).where(Job.status == "published").limit(200)).all()
    ranked = [{"job": j, "match": match_score(j, profile)} for j in candidate_jobs]
    ranked.sort(key=lambda x: x["match"]["score"], reverse=True)
    return ranked[:limit]


@router.post("/saved-jobs/{job_id}", status_code=201)
def save_job(job_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    get_public_job(job_id, db)
    record = SavedJob(user_id=u.id, job_id=job_id)
    db.add(record)
    try:
        db.commit()
        db.refresh(record)
    except IntegrityError:
        db.rollback()
        record = db.scalar(select(SavedJob).where(SavedJob.user_id == u.id, SavedJob.job_id == job_id))
    return record


@router.get("/saved-jobs")
def saved(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    u=Depends(current_user),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(Job)
        .join(SavedJob, SavedJob.job_id == Job.id)
        .where(SavedJob.user_id == u.id)
        .order_by(SavedJob.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.delete("/saved-jobs/{job_id}", status_code=204)
def unsave(job_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    record = db.scalar(select(SavedJob).where(SavedJob.user_id == u.id, SavedJob.job_id == job_id))
    if record:
        db.delete(record)
        db.commit()


# NOTE — V22.1: the previous inline application-tracking endpoints
# that lived here (POST/GET/PUT/DELETE /applications, V7) have moved
# to app/api/applications.py, backed by a proper service layer
# (app.applications.service) with richer fields, immutable status
# history, and a canonical status vocabulary. Same base URL
# (/applications) — nothing that already points at this API's base
# path needs to change. See docs/V22_1_APPLICATION_TRACKING.md.


class AlertIn(BaseModel):
    alert_type: str = "job"
    query: str | None = None
    enabled: bool = True


@router.post("/alerts", status_code=201)
def add_alert(payload: AlertIn, u=Depends(current_user), db: Session = Depends(get_db)):
    record = Alert(user_id=u.id, **payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/alerts")
def alerts(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    u=Depends(current_user),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(Alert).where(Alert.user_id == u.id).order_by(Alert.id.desc()).limit(limit).offset(offset)
    ).all()


@router.delete("/alerts/{alert_id}", status_code=204)
def delete_alert(alert_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    record = db.scalar(select(Alert).where(Alert.id == alert_id, Alert.user_id == u.id))
    if not record:
        raise HTTPException(404, "Alert not found")
    db.delete(record)
    db.commit()


# --- V7 notifications --------------------------------------------------------
#
# V23.5 FIX (docs/V23_BUG_REPORT.md): this section used to define its
# own GET /notifications, GET /notifications/unread-count,
# POST /notifications/{id}/read, and POST /notifications/read-all.
# Because this router is included before app.api.notifications (V23.1)
# and app.api.notification_engine (V19.4) in app.api.routes, these
# four older, narrower V7 routes silently WON every request to those
# paths — the richer V23.1/V19.4 implementations of the exact same
# paths were dead code, never actually reachable. The frontend
# (src/lib/notifications.ts) was built against the V23.1/V19.4 response
# shapes (`{items, total, unread_count, has_more}`,
# `{unread_count: n}`, a full updated Notification object from
# mark-read), not these — so in production the notifications page was
# silently receiving the wrong shape from three of these four
# endpoints. Removed here; GET /notifications, GET
# /notifications/unread-count, and POST /notifications/{id}/read now
# resolve to app.api.notifications' versions, and POST
# /notifications/read-all resolves to app.api.notification_engine's.
# See those two modules for the current implementations.


# --- V9 applying to a CareerOS-hosted job (recruiter platform) --------------

class ApplyIn(BaseModel):
    cover_note: str | None = None


@router.post("/jobs/{job_id}/apply", status_code=201)
def apply_to_job(job_id: int, payload: ApplyIn, u=Depends(current_user), db: Session = Depends(get_db)):
    """Apply to a job actually posted through CareerOS (i.e. it has a
    recruiter owner). This is distinct from the personal Applications
    tracker (POST /applications), which is a private list of roles a
    candidate is pursuing anywhere and isn't visible to anyone else —
    an Applicant row here is deliberately visible to the job's owner.
    """
    job = get_public_job(job_id, db)
    if job.owner_user_id is None:
        raise HTTPException(
            409,
            "This listing isn't hosted for direct applications through CareerOS — use its official apply link.",
        )

    existing = db.scalar(select(Applicant).where(Applicant.job_id == job_id, Applicant.user_id == u.id))
    if existing:
        raise HTTPException(409, "You've already applied to this job")

    resume = db.get(Resume, u.id)
    applicant = Applicant(
        job_id=job_id,
        user_id=u.id,
        cover_note=payload.cover_note,
        resume_snapshot=resume.extracted_text if resume else None,
    )
    db.add(applicant)
    db.commit()
    db.refresh(applicant)
    # V24.3 — every Applicant starts with one RecruiterPipelineHistory
    # row (old_stage=None -> new_stage="new") so "complete candidate
    # hiring history" (spec section 7) is true from the moment they
    # apply, not just for applicants a later migration backfilled.
    # changed_by_user_id is None — this is the system, not a recruiter
    # action.
    db.add(RecruiterPipelineHistory(applicant_id=applicant.id, old_stage=None, new_stage="new", changed_by_user_id=None, direction="initial"))
    db.commit()
    return {"id": applicant.id, "status": applicant.status}


@router.get("/my-submissions")
def my_submissions(u=Depends(current_user), db: Session = Depends(get_db)):
    applicants = db.scalars(
        select(Applicant).where(Applicant.user_id == u.id).order_by(Applicant.id.desc())
    ).all()
    return [
        {
            "id": a.id,
            "job_id": a.job_id,
            "status": a.status,
            "reject_reason": a.reject_reason,
            "created_at": a.created_at,
        }
        for a in applicants
    ]


def _own_applicant_or_404(db: Session, applicant_id: int, user) -> Applicant:
    applicant = db.get(Applicant, applicant_id)
    if not applicant or applicant.user_id != user.id:
        raise HTTPException(404, "Application not found")
    return applicant


@router.get("/my-submissions/{applicant_id}/interviews")
def my_interviews(applicant_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    """V16 — a candidate's own view of interviews scheduled against
    their application. Recruiter-side scheduling lives in
    app.api.recruiter; this is the read-only candidate mirror of it."""
    _own_applicant_or_404(db, applicant_id, u)
    rows = db.scalars(
        select(Interview).where(Interview.applicant_id == applicant_id).order_by(Interview.scheduled_at)
    ).all()
    return [
        {
            "id": r.id, "round_name": r.round_name, "mode": r.mode,
            "scheduled_at": r.scheduled_at, "location_or_link": r.location_or_link,
            "status": r.status,
        }
        for r in rows
    ]


@router.get("/my-submissions/{applicant_id}/offer")
def my_offer(applicant_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    """V16 — a candidate's own view of an offer letter, if any. Offers
    still in "draft" (not yet sent by the recruiter) aren't shown —
    a draft is an internal working copy, not a real offer yet."""
    _own_applicant_or_404(db, applicant_id, u)
    offer = db.scalar(select(OfferLetter).where(OfferLetter.applicant_id == applicant_id))
    if not offer or offer.status == "draft":
        raise HTTPException(404, "No offer available")
    return {
        "id": offer.id, "position_title": offer.position_title, "salary": offer.salary,
        "start_date": offer.start_date, "expiry_date": offer.expiry_date,
        "letter_text": offer.letter_text, "status": offer.status,
    }


class OfferResponseIn(BaseModel):
    accept: bool


@router.post("/my-submissions/{applicant_id}/offer/respond")
def respond_to_offer(applicant_id: int, payload: OfferResponseIn, u=Depends(current_user), db: Session = Depends(get_db)):
    """V16 — a candidate accepting or declining an offer. Only valid
    while the offer is "sent" — an already-accepted/declined offer, or
    one still in "draft", can't be responded to again."""
    _own_applicant_or_404(db, applicant_id, u)
    offer = db.scalar(select(OfferLetter).where(OfferLetter.applicant_id == applicant_id))
    if not offer or offer.status != "sent":
        raise HTTPException(409, "No pending offer to respond to")
    offer.status = "accepted" if payload.accept else "declined"
    log_audit(db, action="offer_response", entity_type="offer_letter", entity_id=str(offer.id), detail=offer.status)
    db.commit()
    return {"id": offer.id, "status": offer.status}


@router.delete("/jobs/{job_id}/apply", status_code=204)
def withdraw_application(job_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    applicant = db.scalar(select(Applicant).where(Applicant.job_id == job_id, Applicant.user_id == u.id))
    if applicant:
        db.delete(applicant)
        db.commit()


@router.get("/dashboard")
def dashboard(u=Depends(current_user), db: Session = Depends(get_db)):
    upcoming_deadline_horizon = date.today() + timedelta(days=7)

    # V22.1 DASHBOARD INTEGRATION — reuses app.applications.service's
    # own stats query (one grouped-count query, no N+1) rather than
    # hand-rolling a second application-counting query here. The
    # pre-existing "applications" (bare total) key is left exactly as
    # it was so nothing already reading it breaks; "application_stats"
    # is additive.
    from app.applications import service as application_service

    app_stats = application_service.get_stats(db, u.id)

    return {
        "saved_jobs": db.scalar(select(func.count()).select_from(SavedJob).where(SavedJob.user_id == u.id)),
        "applications": db.scalar(
            select(func.count()).select_from(Application).where(Application.user_id == u.id)
        ),
        "application_stats": app_stats,
        "alerts": db.scalar(
            select(func.count()).select_from(Alert).where(Alert.user_id == u.id, Alert.enabled == True)  # noqa: E712
        ),
        "unread_notifications": db.scalar(
            select(func.count()).select_from(Notification).where(Notification.user_id == u.id, Notification.read == False)  # noqa: E712
        ),
        "upcoming_deadlines": db.scalar(
            select(func.count())
            .select_from(Application)
            .where(
                Application.user_id == u.id,
                Application.next_deadline.is_not(None),
                Application.next_deadline <= upcoming_deadline_horizon,
            )
        ),
        "profile_complete": db.get(Profile, u.id) is not None,
    }
