"""V9 Recruiter platform — authenticated recruiter accounts (role-gated
by app.core.security.require_recruiter, not the shared admin key) can
post and manage their own job listings and review applicants.

Recruiter-posted jobs still land in the review queue like every other
source in this project — a recruiter account doesn't bypass admin
verification before a listing goes public.
"""

import csv
import io
import json
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.recruiter_candidates import _load_candidate_rows
from app.core.validators import http_url_validator
from app.core.audit import log_audit
from app.core.constants import EMPLOYMENT_TYPES, JOB_TYPES, PIPELINE_STAGES, WORK_MODES
from app.core.security import require_recruiter
from app.core.team_access import team_owner_ids
from app.db.session import get_db
from app.ingestion.models.job_record import JobRecord
from app.ingestion.services.normalize import normalize_job
from app.ingestion.services.publisher import generate_slug, publish_to_review
from app.models.domain import (
    Applicant,
    ApplicantNote,
    CompanyTeamMember,
    Interview,
    Job,
    OfferLetter,
    Organization,
    Resume,
    User,
)
from app.recruiter_pipeline import service as pipeline_service
from app.search.hooks import sync_job
from app.services.email_service import send_email
from app.services.offer_letters import render_offer_letter

logger = logging.getLogger("careeros.recruiter")


def _notify_candidate_by_email(to: str, subject: str, body: str) -> None:
    """V23.5 fix (docs/V23_BUG_REPORT.md): these three candidate-facing
    emails (status change, interview scheduled, offer letter) are sent
    through the older, unqueued app.services.email_service.send_email
    (direct smtplib, no retry/queue) rather than V23.2's
    app.email.service — left as-is here since migrating a V16 recruiter
    flow onto the V23.2 queue is a larger change than this stabilization
    pass should make. What WAS a confirmed bug: every call site ran
    `db.commit()` for the actual recruiter action (status change,
    interview creation, offer send) BEFORE calling send_email with no
    try/except around it — so the business operation was never rolled
    back, but a transient SMTP failure still propagated out of the
    endpoint as an uncaught exception, turning an already-successful
    action into a 500 response to the recruiter (spec: "A failure in
    notification processing must NOT roll back the original business
    operation" — this wasn't a rollback, but it was exactly the failure-
    isolation gap that requirement exists to prevent). This wrapper
    gives all three call sites that isolation in one place rather than
    three separate try/excepts.
    """
    try:
        send_email(to, subject, body)
    except Exception:
        logger.error("Candidate notification email failed (to=%s, subject=%r)", to, subject, exc_info=True)

router = APIRouter()

_PRIVATE_JOB_TYPES = [t for t in JOB_TYPES if t != "Government"]

_APPLICANT_STATUSES = ("submitted", "shortlisted", "interview", "rejected", "hired")

# V18.2 — job lifecycle states a recruiter's own job can be in. Distinct
# from app.api.admin's review-queue vocabulary: a recruiter moves a job
# draft -> review (submit), and separately published -> closed/reopened
# or -> archived, all without touching the admin approval path itself.
_CLOSABLE_STATUSES = ("published",)
_REOPENABLE_STATUSES = ("closed",)


def _owned_job_or_404(db: Session, job_id: int, recruiter: User) -> Job:
    """V18.6: "owned" now means "owned by anyone on the same company
    team as `recruiter`", not just `recruiter` themselves — see
    app.core.team_access.team_owner_ids. A solo recruiter with no
    company/team sees exactly the same behavior as before this change.
    """
    job = db.get(Job, job_id)
    if not job or job.owner_user_id not in team_owner_ids(db, recruiter):
        raise HTTPException(404, "Job not found")
    return job


def _job_to_dict(db: Session, job: Job) -> dict:
    """V24.1 — the recruiter Jobs section (spec section 5) needs an
    application count and an "is this expired" flag alongside every
    plain Job column. Rather than adding either as a stored column
    (application count is already derivable from `applicants`; expiry
    is already derivable from `deadline`), this composes them onto a
    plain dict of the job's own columns, so every existing consumer of
    a recruiter Job response (edit form, wizard preview) still finds
    every field it already reads, unchanged."""
    data = {c.name: getattr(job, c.name) for c in Job.__table__.columns}
    application_count = db.scalar(select(func.count()).select_from(Applicant).where(Applicant.job_id == job.id)) or 0
    is_expired = bool(
        job.status == "published" and job.deadline is not None and job.deadline < datetime.utcnow().date()
    )
    data["application_count"] = application_count
    data["is_expired"] = is_expired
    # "Review status" (spec section 5) is the same value as `status` —
    # exposed under both names since that's the vocabulary section 5
    # asks for, without introducing a second, divergent status field.
    data["review_status"] = job.status
    return data


def _owned_applicant_or_404(db: Session, applicant_id: int, recruiter: User) -> Applicant:
    applicant = db.get(Applicant, applicant_id)
    if not applicant:
        raise HTTPException(404, "Applicant not found")
    _owned_job_or_404(db, applicant.job_id, recruiter)  # ownership check via the underlying job
    return applicant


class RecruiterJobIn(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    organization: str = Field(min_length=1, max_length=220)
    department: str | None = None
    job_type: str = "Private"
    category: str | None = None
    employment_type: str | None = None
    work_mode: str | None = None
    industry: str | None = None
    experience_required: str | None = None
    location: str = "India"
    vacancies: int | None = Field(default=None, ge=0)
    qualification: str = "See job description"
    salary: str | None = None
    stipend: str | None = None
    duration: str | None = None
    deadline: date | None = None
    description: str = "See job description"
    apply_url: str | None = None
    _validate_urls = http_url_validator("apply_url", assume_https=True)
    # V18.2 — professional job creation wizard sections.
    responsibilities: str | None = Field(default=None, max_length=8000)
    requirements: str | None = Field(default=None, max_length=8000)
    skills: list[str] | None = None
    benefits: str | None = Field(default=None, max_length=4000)
    screening_questions: list[str] | None = None
    # If true, the job is saved to the recruiter's own draft list and
    # never enters the public admin review queue until they explicitly
    # submit it (POST /jobs/{id}/submit-for-review).
    save_as_draft: bool = False

    @field_validator("skills")
    @classmethod
    def skills_trimmed(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [s.strip() for s in value if s and s.strip()][:50]

    @field_validator("screening_questions")
    @classmethod
    def questions_trimmed(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [q.strip() for q in value if q and q.strip()][:20]

    @field_validator("job_type")
    @classmethod
    def job_type_must_be_private_category(cls, value: str) -> str:
        if value not in _PRIVATE_JOB_TYPES:
            raise ValueError(f"job_type must be one of {_PRIVATE_JOB_TYPES}")
        return value

    @field_validator("employment_type")
    @classmethod
    def employment_type_must_be_known(cls, value: str | None) -> str | None:
        if value is not None and value not in EMPLOYMENT_TYPES:
            raise ValueError(f"employment_type must be one of {EMPLOYMENT_TYPES}")
        return value

    @field_validator("work_mode")
    @classmethod
    def work_mode_must_be_known(cls, value: str | None) -> str | None:
        if value is not None and value not in WORK_MODES:
            raise ValueError(f"work_mode must be one of {WORK_MODES}")
        return value


_WIZARD_FIELDS = {"responsibilities", "requirements", "benefits"}


def _apply_wizard_fields(job: Job, payload: "RecruiterJobIn") -> None:
    """Copies the wizard-only fields (not part of app.ingestion.models.job_record.JobRecord,
    so publish_to_review/normalize_job never see them) onto a Job row."""
    for field in _WIZARD_FIELDS:
        setattr(job, field, getattr(payload, field))
    job.skills = json.dumps(payload.skills) if payload.skills else None
    job.screening_questions = json.dumps(payload.screening_questions) if payload.screening_questions else None


@router.post("/jobs", status_code=201)
def create_job(payload: RecruiterJobIn, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    base = payload.model_dump(exclude={"responsibilities", "requirements", "skills", "benefits", "screening_questions", "save_as_draft"})
    record = normalize_job(JobRecord(source_name=f"Recruiter: {recruiter.full_name}", **base))

    if payload.save_as_draft:
        # Drafts skip the public review queue/dedup entirely — a
        # recruiter should be able to save an incomplete or
        # work-in-progress listing without it ever being visible for
        # admin approval until they submit it.
        job = Job(
            slug=generate_slug(record),
            title=record.title, organization=record.organization, department=record.department,
            job_type=record.job_type, category=record.category, employment_type=record.employment_type,
            work_mode=record.work_mode, industry=record.industry, experience_required=record.experience_required,
            location=record.location, vacancies=record.vacancies, qualification=record.qualification,
            salary=record.salary, stipend=record.stipend, duration=record.duration, deadline=record.deadline,
            description=record.description, apply_url=record.apply_url,
            source_name=record.source_name, verified=False, status="draft", owner_user_id=recruiter.id,
        )
        _apply_wizard_fields(job, payload)
        db.add(job)
        log_audit(db, action="create_job_draft", entity_type="job", entity_id=None)
        db.commit()
        sync_job(db, job.id)  # V21.1 Phase 3 — keep search in near-real-time sync
        db.refresh(job)
        return job

    created, job = publish_to_review(db, record)
    if not created:
        raise HTTPException(409, "An equivalent listing already exists")

    job.owner_user_id = recruiter.id
    _apply_wizard_fields(job, payload)
    log_audit(db, action="create_job", entity_type="job", entity_id=str(job.id))
    db.commit()
    sync_job(db, job.id)  # V21.1 Phase 3
    db.refresh(job)
    return job


@router.get("/jobs")
def list_my_jobs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    jobs = db.scalars(
        select(Job)
        .where(Job.owner_user_id.in_(team_owner_ids(db, recruiter)))
        .order_by(Job.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [_job_to_dict(db, j) for j in jobs]


@router.get("/jobs/{job_id}")
def preview_my_job(job_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Full detail view of one of the recruiter's own jobs (any status,
    including draft) — the wizard "Preview" step and the edit form both
    read from this."""
    job = _owned_job_or_404(db, job_id, recruiter)
    return _job_to_dict(db, job)


@router.put("/jobs/{job_id}")
def update_my_job(
    job_id: int,
    payload: RecruiterJobIn,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    job = _owned_job_or_404(db, job_id, recruiter)
    incoming = payload.model_dump(exclude={"skills", "screening_questions", "save_as_draft"})
    material_fields = {
        "title", "organization", "department", "job_type", "category",
        "employment_type", "work_mode", "industry", "experience_required",
        "location", "vacancies", "qualification", "salary", "stipend",
        "duration", "deadline", "description", "apply_url",
        "responsibilities", "requirements", "benefits",
    }
    material_change = any(getattr(job, key, None) != incoming.get(key) for key in material_fields)
    for key, value in incoming.items():
        setattr(job, key, value)
    job.skills = json.dumps(payload.skills) if payload.skills else None
    job.screening_questions = json.dumps(payload.screening_questions) if payload.screening_questions else None
    # A recruiter must never be able to alter admin-approved content in place.
    # Any material edit sends the listing through verification again.
    if material_change and job.status == "published":
        job.status = "review"
        job.verified = False
    log_audit(db, action="update_job", entity_type="job", entity_id=str(job_id))
    db.commit()
    sync_job(db, job.id)  # V21.1 Phase 3
    db.refresh(job)
    return job


@router.delete("/jobs/{job_id}", status_code=204)
def delete_my_job(job_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    job = _owned_job_or_404(db, job_id, recruiter)
    # V25.6 (F-35): applicants.job_id is ON DELETE CASCADE, so deleting a job silently destroyed
    # every candidate's application record, pipeline history, interviews and notes for it - one
    # click by any team member, irreversible. A job that has received applications is closed
    # (POST .../close), never deleted; only never-applied-to jobs (drafts, mistakes) can be deleted.
    applicant_count = db.scalar(select(func.count()).select_from(Applicant).where(Applicant.job_id == job_id)) or 0
    if applicant_count:
        raise HTTPException(409, "This job has applicants and cannot be deleted. Close it instead to keep the hiring records.")
    db.delete(job)
    db.commit()
    sync_job(db, job_id)  # V21.1 Phase 3 — index_job() removes the now-stale search document


@router.post("/jobs/{job_id}/submit-for-review", status_code=200)
def submit_job_for_review(job_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Draft Mode -> Approval Workflow: moves a recruiter's draft into
    the same admin review queue every other job source goes through
    (app.api.admin.review / .publish). Nothing about that admin-side
    approval path is changed."""
    job = _owned_job_or_404(db, job_id, recruiter)
    if job.status != "draft":
        raise HTTPException(409, f"Only a draft job can be submitted for review (current status: '{job.status}')")
    job.status = "review"
    log_audit(db, action="submit_job_for_review", entity_type="job", entity_id=str(job_id))
    db.commit()
    sync_job(db, job.id)  # V21.1 Phase 3
    db.refresh(job)
    return job


@router.post("/jobs/{job_id}/close", status_code=200)
def close_my_job(job_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Stops accepting new applications without deleting the listing or
    its applicant history — distinct from Archive, which is meant to be
    permanent/out-of-the-way."""
    job = _owned_job_or_404(db, job_id, recruiter)
    if job.status not in _CLOSABLE_STATUSES:
        raise HTTPException(409, f"Only a published job can be closed (current status: '{job.status}')")
    job.status = "closed"
    job.closed_at = datetime.utcnow()
    log_audit(db, action="close_job", entity_type="job", entity_id=str(job_id))
    db.commit()
    sync_job(db, job.id)  # V21.1 Phase 3
    db.refresh(job)
    return job


@router.post("/jobs/{job_id}/reopen", status_code=200)
def reopen_my_job(job_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    job = _owned_job_or_404(db, job_id, recruiter)
    if job.status not in _REOPENABLE_STATUSES:
        raise HTTPException(409, f"Only a closed job can be reopened (current status: '{job.status}')")
    job.status = "published"
    job.closed_at = None
    log_audit(db, action="reopen_job", entity_type="job", entity_id=str(job_id))
    db.commit()
    sync_job(db, job.id)  # V21.1 Phase 3
    db.refresh(job)
    return job


@router.post("/jobs/{job_id}/archive", status_code=200)
def archive_my_job(job_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Archive is available from any status and, unlike close/reopen,
    has no way back through the API — a deliberate one-way door so
    "archived" reliably means "no longer active" everywhere it's read."""
    job = _owned_job_or_404(db, job_id, recruiter)
    if job.status == "archived":
        raise HTTPException(409, "Job is already archived")
    job.status = "archived"
    job.archived_at = datetime.utcnow()
    log_audit(db, action="archive_job", entity_type="job", entity_id=str(job_id))
    db.commit()
    sync_job(db, job.id)  # V21.1 Phase 3
    db.refresh(job)
    return job


@router.post("/jobs/{job_id}/clone", status_code=201)
def clone_my_job(job_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Copies every wizard field onto a brand-new draft job — lets a
    recruiter reuse a past posting (e.g. "Backend Engineer — Q2") as
    the starting point for a new one without re-typing it."""
    source = _owned_job_or_404(db, job_id, recruiter)
    clone_record = JobRecord(
        source_name=source.source_name or f"Recruiter: {recruiter.full_name}",
        title=f"{source.title} (Copy)", organization=source.organization, department=source.department,
        job_type=source.job_type, category=source.category, employment_type=source.employment_type,
        work_mode=source.work_mode, industry=source.industry, experience_required=source.experience_required,
        location=source.location, vacancies=source.vacancies, qualification=source.qualification,
        salary=source.salary, stipend=source.stipend, duration=source.duration,
        description=source.description, apply_url=source.apply_url,
    )
    clone = Job(
        slug=generate_slug(clone_record),
        title=clone_record.title, organization=clone_record.organization, department=clone_record.department,
        job_type=clone_record.job_type, category=clone_record.category, employment_type=clone_record.employment_type,
        work_mode=clone_record.work_mode, industry=clone_record.industry,
        experience_required=clone_record.experience_required, location=clone_record.location,
        vacancies=clone_record.vacancies, qualification=clone_record.qualification, salary=clone_record.salary,
        stipend=clone_record.stipend, duration=clone_record.duration, description=clone_record.description,
        apply_url=clone_record.apply_url, source_name=clone_record.source_name,
        responsibilities=source.responsibilities, requirements=source.requirements,
        skills=source.skills, benefits=source.benefits, screening_questions=source.screening_questions,
        verified=False, status="draft", owner_user_id=recruiter.id, cloned_from_job_id=source.id,
    )
    db.add(clone)
    log_audit(db, action="clone_job", entity_type="job", entity_id=str(job_id))
    db.commit()
    sync_job(db, clone.id)  # V21.1 Phase 3
    db.refresh(clone)
    return clone


@router.get("/jobs/{job_id}/applicants")
def list_applicants(
    job_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    _owned_job_or_404(db, job_id, recruiter)
    applicants = db.scalars(
        select(Applicant)
        .where(Applicant.job_id == job_id)
        .order_by(Applicant.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    result = []
    for a in applicants:
        candidate = db.get(User, a.user_id)
        result.append(
            {
                "id": a.id,
                "status": a.status,
                "reject_reason": a.reject_reason,
                "cover_note": a.cover_note,
                "resume_snapshot": a.resume_snapshot,
                "created_at": a.created_at,
                "candidate_name": candidate.full_name if candidate else None,
                "candidate_email": candidate.email if candidate else None,
                "pipeline_stage": a.pipeline_stage,
            }
        )
    return result


def _applicant_export_rows(db: Session, job_id: int) -> list[list]:
    """Shared row-building for the CSV and Excel applicant exports, so
    the two formats can never drift out of sync on column set/order."""
    applicants = db.scalars(
        select(Applicant).where(Applicant.job_id == job_id).order_by(Applicant.id.desc())
    ).all()
    rows = []
    for a in applicants:
        candidate = db.get(User, a.user_id)
        rows.append(
            [
                a.id,
                candidate.full_name if candidate else "",
                candidate.email if candidate else "",
                a.status,
                a.pipeline_stage,
                a.reject_reason or "",
                (a.cover_note or "").replace("\n", " "),
                a.created_at.isoformat() if a.created_at else "",
            ]
        )
    return rows


_EXPORT_HEADERS = [
    "Applicant ID", "Candidate name", "Candidate email", "Status", "Pipeline stage",
    "Reject reason", "Cover note", "Applied on",
]


@router.get("/jobs/{job_id}/applicants/export")
def export_applicants_csv(
    job_id: int,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    """Applicants CSV export for a single job — recruiter-owned only.
    Streamed rather than built as one big string so this stays cheap
    even for a job with a large applicant list."""
    job = _owned_job_or_404(db, job_id, recruiter)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_EXPORT_HEADERS)
    writer.writerows(_applicant_export_rows(db, job_id))
    buffer.seek(0)
    filename = f"applicants-job-{job.id}.csv"
    log_audit(db, action="export_applicants_csv", entity_type="job", entity_id=str(job_id))
    db.commit()
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/jobs/{job_id}/applicants/export.xlsx")
def export_applicants_excel(
    job_id: int,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    """V18.7 — same data as export_applicants_csv above, as a real
    .xlsx workbook (bold header row, auto-sized columns) instead of
    plain text, for recruiters who want to open it directly in Excel
    rather than import a CSV. Built in memory with openpyxl and
    streamed back, same as the CSV export — no temp file on disk."""
    job = _owned_job_or_404(db, job_id, recruiter)
    rows = _applicant_export_rows(db, job_id)

    wb = Workbook()
    ws = wb.active
    ws.title = "Applicants"
    ws.append(_EXPORT_HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append(row)

    for col_cells in ws.columns:
        longest = max((len(str(c.value)) for c in col_cells if c.value is not None), default=8)
        ws.column_dimensions[col_cells[0].column_letter].width = min(max(longest + 2, 10), 60)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    filename = f"applicants-job-{job.id}.xlsx"
    log_audit(db, action="export_applicants_excel", entity_type="job", entity_id=str(job_id))
    db.commit()
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/applicants/{applicant_id}")
def get_applicant_detail(
    applicant_id: int,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    """Full candidate profile for the recruiter-facing applicant detail
    view: application info, resume (whatever CareerOS already extracted
    for this candidate at upload time — see V8's `app.models.domain.Resume`),
    notes, interviews and offer, in one call instead of five."""
    applicant = _owned_applicant_or_404(db, applicant_id, recruiter)
    candidate = db.get(User, applicant.user_id)
    job = db.get(Job, applicant.job_id)
    resume = db.get(Resume, applicant.user_id)

    notes = db.scalars(
        select(ApplicantNote).where(ApplicantNote.applicant_id == applicant_id).order_by(ApplicantNote.id.desc())
    ).all()
    interviews = db.scalars(
        select(Interview).where(Interview.applicant_id == applicant_id).order_by(Interview.scheduled_at)
    ).all()
    offer = db.scalar(select(OfferLetter).where(OfferLetter.applicant_id == applicant_id))

    skills: list[str] = []
    if resume and resume.skills_detected:
        try:
            parsed = json.loads(resume.skills_detected)
            skills = parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            skills = [s.strip() for s in resume.skills_detected.split(",") if s.strip()]

    # A simple activity timeline stitched together from what this
    # applicant already has, newest first — not a separate audit table,
    # since notes/interviews/offer already carry their own timestamps.
    timeline = [{"type": "applied", "at": applicant.created_at, "detail": None}]
    for n in notes:
        timeline.append({"type": "note", "at": n.created_at, "detail": n.note})
    for i in interviews:
        timeline.append({"type": "interview_scheduled", "at": i.created_at, "detail": f"{i.round_name} ({i.status})"})
    if offer:
        timeline.append({"type": "offer", "at": offer.created_at, "detail": f"{offer.position_title} ({offer.status})"})
    timeline.sort(key=lambda e: e["at"] or applicant.created_at, reverse=True)

    return {
        "id": applicant.id,
        "job_id": applicant.job_id,
        "job_title": job.title if job else None,
        "candidate_name": candidate.full_name if candidate else None,
        "candidate_email": candidate.email if candidate else None,
        "status": applicant.status,
        "pipeline_stage": applicant.pipeline_stage,
        "reject_reason": applicant.reject_reason,
        "cover_note": applicant.cover_note,
        "resume_snapshot": applicant.resume_snapshot,
        "created_at": applicant.created_at,
        "resume": {
            "original_filename": resume.original_filename,
            "uploaded_at": resume.uploaded_at,
            "extracted_text": resume.extracted_text,
            "skills": skills,
        }
        if resume
        else None,
        "notes": [{"id": n.id, "note": n.note, "created_at": n.created_at} for n in notes],
        "interviews": interviews,
        "offer": offer,
        "timeline": timeline,
    }


@router.get("/jobs/{job_id}/pipeline")
def get_job_pipeline(job_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Kanban board data: every applicant for this job, grouped by
    pipeline_stage, in PIPELINE_STAGES column order.

    V24.3: cards are enriched with the same authorized profile fields
    V24.2's candidate discovery already exposes (headline, top skills,
    experience level, location) by reusing
    app.api.recruiter_candidates._load_candidate_rows rather than
    re-deriving them here — see spec section 10, "Do not duplicate
    candidate profiles." Match score is deliberately *not*
    recomputed per board load (spec section 32: "avoid ...
    recalculating match scores unnecessarily" is a named perf
    concern) — it's shown on the candidate detail panel instead
    (GET /recruiter/applicants/{id}), which is only ever fetched for
    one candidate at a time.
    """
    _owned_job_or_404(db, job_id, recruiter)
    applicants = db.scalars(select(Applicant).where(Applicant.job_id == job_id).order_by(Applicant.id.desc())).all()

    rows_by_user_id = {
        row.user.id: row for row in _load_candidate_rows(db, recruiter, {a.user_id for a in applicants})
    }

    columns: dict[str, list] = {stage: [] for stage in PIPELINE_STAGES}
    for a in applicants:
        candidate = db.get(User, a.user_id)
        row = rows_by_user_id.get(a.user_id)
        stage_time = pipeline_service.time_in_current_stage(db, a)
        card = {
            "id": a.id,
            "status": a.status,
            "candidate_name": candidate.full_name if candidate else None,
            "candidate_email": candidate.email if candidate else None,
            "headline": row.career.target_role if row and row.career else None,
            "top_skills": sorted(row.skills)[:8] if row else [],
            "experience_level": row.career.experience_level if row and row.career else None,
            "location": row.profile.location if row and row.profile else None,
            "created_at": a.created_at,
            "pipeline_stage": a.pipeline_stage or "new",
            "days_in_stage": stage_time["days_in_stage"],
        }
        columns.setdefault(a.pipeline_stage or "new", []).append(card)
    return {"job_id": job_id, "stages": PIPELINE_STAGES, "columns": columns}


class PipelineStageIn(BaseModel):
    pipeline_stage: str
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("pipeline_stage")
    @classmethod
    def stage_must_be_known(cls, value: str) -> str:
        if value not in PIPELINE_STAGES:
            raise ValueError(f"pipeline_stage must be one of {PIPELINE_STAGES}")
        return value


@router.patch("/applicants/{applicant_id}/stage")
def move_applicant_stage(
    applicant_id: int,
    payload: PipelineStageIn,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    """Drag-and-drop (and V24.3 non-drag "Change Stage") endpoint for
    the Kanban board — moves a candidate between pipeline columns
    independently of the coarser `status` field (which the recruiter
    still sets separately via PATCH /applicants/{id}).

    V24.3: now validates the transition and writes an immutable
    RecruiterPipelineHistory row via app.recruiter_pipeline.service —
    see that module for the transition policy. The request/response
    shape is unchanged from V18.2 (`reason` is new but optional), so
    the existing frontend board keeps working without changes.
    """
    applicant = _owned_applicant_or_404(db, applicant_id, recruiter)
    try:
        result = pipeline_service.change_stage(
            db, applicant, payload.pipeline_stage, actor_user_id=recruiter.id, reason=payload.reason
        )
    except pipeline_service.StageTransitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_audit(
        db,
        action="move_applicant_stage",
        entity_type="applicant",
        entity_id=str(applicant_id),
        detail=f"{result.history.old_stage} -> {result.history.new_stage}",
    )
    db.commit()
    return {
        "id": result.applicant.id,
        "pipeline_stage": result.applicant.pipeline_stage,
        "hired_at": result.applicant.hired_at,
        "history_id": result.history.id,
        "candidate_notified": result.candidate_notified,
    }


class ApplicantStatusIn(BaseModel):
    status: str
    reject_reason: str | None = Field(default=None, max_length=2000)

    @field_validator("status")
    @classmethod
    def status_must_be_known(cls, value: str) -> str:
        if value not in _APPLICANT_STATUSES:
            raise ValueError(f"status must be one of {_APPLICANT_STATUSES}")
        return value


_STATUS_NOTIFICATION_SUBJECTS = {
    "shortlisted": "You've been shortlisted",
    "interview": "You've been moved to interview stage",
    "rejected": "Update on your application",
    "hired": "Congratulations — offer details to follow",
}


@router.patch("/applicants/{applicant_id}")
def update_applicant_status(
    applicant_id: int,
    payload: ApplicantStatusIn,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    applicant = _owned_applicant_or_404(db, applicant_id, recruiter)

    # V16 — a rejection without a reason isn't useful to the candidate
    # (see GET /my-submissions, which now surfaces reject_reason) and
    # isn't useful to the recruiter's own hiring analytics later either.
    if payload.status == "rejected" and not payload.reject_reason:
        raise HTTPException(422, "reject_reason is required when rejecting an applicant")

    applicant.status = payload.status
    applicant.reject_reason = payload.reject_reason if payload.status == "rejected" else applicant.reject_reason
    log_audit(db, action="update_applicant_status", entity_type="applicant", entity_id=str(applicant_id), detail=payload.status)
    db.commit()

    candidate = db.get(User, applicant.user_id)
    job = db.get(Job, applicant.job_id)
    if candidate and job and payload.status in _STATUS_NOTIFICATION_SUBJECTS:
        body = f"Your application for {job.title} at {job.organization} has been updated: status is now '{payload.status}'."
        if payload.status == "rejected" and payload.reject_reason:
            body += f"\n\nReason: {payload.reject_reason}"
        _notify_candidate_by_email(candidate.email, _STATUS_NOTIFICATION_SUBJECTS[payload.status], body)

    return {"id": applicant_id, "status": applicant.status, "reject_reason": applicant.reject_reason}


_INTERVIEW_PIPELINE_STAGES = ("interview", "technical_round", "hr_round")


@router.get("/dashboard")
def recruiter_dashboard(recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """V24.1 (Recruiter Workspace) extends the V9 dashboard in place —
    same endpoint, richer response — with the statistics, pending
    actions and recent-activity feed the Overview section needs
    (spec sections 3–4, 13). Every number here is a real aggregate
    query over `jobs`/`applicants`/`offer_letters`; nothing is
    hard-coded or estimated. No new storage: "recent activity" is
    assembled from timestamps/status already on Job and Applicant
    rather than a new event log (spec section 4 explicitly asks not to
    duplicate an event system that isn't needed)."""
    owner_ids = team_owner_ids(db, recruiter)
    my_jobs = db.scalars(select(Job).where(Job.owner_user_id.in_(owner_ids))).all()
    job_ids = [j.id for j in my_jobs]
    today = datetime.utcnow().date()

    jobs_published = sum(1 for j in my_jobs if j.status == "published")
    jobs_expired = sum(1 for j in my_jobs if j.status == "published" and j.deadline is not None and j.deadline < today)

    applicants: list[Applicant] = []
    if job_ids:
        applicants = db.scalars(select(Applicant).where(Applicant.job_id.in_(job_ids))).all()
    total_applicants = len(applicants)
    new_applications = sum(1 for a in applicants if a.status == "submitted")
    candidates_in_interview = sum(
        1 for a in applicants if a.status == "interview" or a.pipeline_stage in _INTERVIEW_PIPELINE_STAGES
    )

    offers_count = 0
    applicant_ids = [a.id for a in applicants]
    if applicant_ids:
        offers_count = db.scalar(
            select(func.count()).select_from(OfferLetter).where(OfferLetter.applicant_id.in_(applicant_ids))
        ) or 0

    # Pending actions (spec section 13): things this recruiter can act
    # on right now, so a quiet dashboard doesn't hide work waiting for
    # them.
    pending_actions = []
    if new_applications:
        pending_actions.append(
            {"type": "new_applications", "count": new_applications, "message": f"{new_applications} new application(s) to review"}
        )
    pending_review_jobs = [j for j in my_jobs if j.status == "review"]
    if pending_review_jobs:
        pending_actions.append(
            {"type": "jobs_pending_review", "count": len(pending_review_jobs), "message": f"{len(pending_review_jobs)} job(s) awaiting admin review"}
        )
    rejected_jobs = [j for j in my_jobs if j.status == "rejected"]
    if rejected_jobs:
        pending_actions.append(
            {"type": "jobs_rejected", "count": len(rejected_jobs), "message": f"{len(rejected_jobs)} job(s) were rejected and need edits"}
        )
    if jobs_expired:
        pending_actions.append(
            {"type": "jobs_expired", "count": jobs_expired, "message": f"{jobs_expired} published job(s) are past their deadline"}
        )

    # Recent activity (spec section 4) — merged from Job and Applicant
    # timestamps already on those rows, newest first.
    activity: list[dict] = []
    for j in my_jobs:
        if j.status == "review":
            activity.append({"type": "job_submitted_for_review", "job_id": j.id, "job_title": j.title, "at": j.updated_at})
        elif j.status == "published":
            activity.append({"type": "job_approved", "job_id": j.id, "job_title": j.title, "at": j.published_at or j.updated_at})
        elif j.status == "rejected":
            activity.append({"type": "job_rejected", "job_id": j.id, "job_title": j.title, "at": j.updated_at})
        elif j.status == "closed":
            activity.append({"type": "job_closed", "job_id": j.id, "job_title": j.title, "at": j.closed_at or j.updated_at})
    for a in sorted(applicants, key=lambda a: a.created_at, reverse=True)[:50]:
        job = next((j for j in my_jobs if j.id == a.job_id), None)
        activity.append({
            "type": "new_application", "applicant_id": a.id, "job_id": a.job_id,
            "job_title": job.title if job else None, "at": a.created_at,
        })
        if a.updated_at and a.updated_at != a.created_at:
            activity.append({
                "type": "candidate_status_changed", "applicant_id": a.id, "job_id": a.job_id,
                "job_title": job.title if job else None, "status": a.status,
                "pipeline_stage": a.pipeline_stage, "at": a.updated_at,
            })
    activity.sort(key=lambda e: e["at"] or datetime.min, reverse=True)

    # Quick actions (spec section 13) — only show what current recruiter
    # state actually permits, so e.g. a pending/unapproved recruiter
    # never sees a misleading "Publish job" action.
    quick_actions = {
        "create_job": True,
        "manage_jobs": len(my_jobs) > 0,
        "review_applications": total_applicants > 0,
        "edit_company_profile": True,
    }

    return {
        "jobs_posted": len(my_jobs),
        "jobs_published": jobs_published,
        "jobs_in_review": sum(1 for j in my_jobs if j.status == "review"),
        "jobs_draft": sum(1 for j in my_jobs if j.status == "draft"),
        "jobs_closed": sum(1 for j in my_jobs if j.status == "closed"),
        "jobs_archived": sum(1 for j in my_jobs if j.status == "archived"),
        "jobs_rejected": sum(1 for j in my_jobs if j.status == "rejected"),
        "jobs_expired": jobs_expired,
        "total_applicants": total_applicants,
        "new_applications": new_applications,
        "candidates_in_interview": candidates_in_interview,
        "offers": offers_count,
        "pending_actions": pending_actions,
        "recent_activity": activity[:20],
        "quick_actions": quick_actions,
    }


class RecruiterProfileIn(BaseModel):
    """V24.1 — deliberately excludes `email` and `role`: identity/
    account ownership is the authentication system's responsibility
    (spec section 12), not something this endpoint can change."""

    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    phone: str | None = Field(default=None, max_length=32)


@router.get("/profile")
def get_recruiter_profile(recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Recruiter's own identity + which company they act for (spec
    section 12). Built entirely on the existing `users` row and V18.1
    `organizations`/`company_team_members` tables — no new table."""
    org = db.scalars(select(Organization).where(Organization.owner_user_id == recruiter.id)).first()
    company_role = "owner" if org is not None else None
    if org is None:
        membership = db.scalars(
            select(CompanyTeamMember).where(CompanyTeamMember.user_id == recruiter.id)
        ).first()
        if membership is not None:
            org = db.get(Organization, membership.company_id)
            company_role = membership.role
    return {
        "id": recruiter.id,
        "full_name": recruiter.full_name,
        "email": recruiter.email,
        "phone": recruiter.phone,
        "role": recruiter.role,
        "recruiter_status": recruiter.recruiter_status,
        "company_id": org.id if org else None,
        "company_name": org.name if org else recruiter.company_name,
        "company_role": company_role,
    }


@router.patch("/profile")
def update_recruiter_profile(
    payload: RecruiterProfileIn, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)
):
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "phone" in changes:
        existing = db.scalars(
            select(User).where(User.phone == changes["phone"], User.id != recruiter.id)
        ).first()
        if existing is not None:
            raise HTTPException(409, "Phone number already in use")
    for key, value in changes.items():
        setattr(recruiter, key, value)
    log_audit(db, action="update_recruiter_profile", entity_type="user", entity_id=str(recruiter.id), detail=str(changes))
    db.commit()
    db.refresh(recruiter)
    return {
        "id": recruiter.id, "full_name": recruiter.full_name, "email": recruiter.email,
        "phone": recruiter.phone, "role": recruiter.role, "recruiter_status": recruiter.recruiter_status,
    }


@router.get("/analytics")
def recruiter_analytics(recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """V18.3 — recruiter-level ATS analytics: pipeline distribution,
    per-stage conversion off of total applicants, average time-to-hire
    (applied -> accepted, in days, over applicants that reached
    "accepted"), and offer acceptance rate. Deliberately computed from
    data already on Applicant/OfferLetter rather than a new tracking
    table — this predates V24.3's `RecruiterPipelineHistory` (see
    app.api.recruiter_pipeline), so time-to-hire still uses
    `updated_at` on the hired applicant as a reasonable proxy for
    "when they were marked hired" rather than being rewritten here.
    V18.6: scoped
    to the whole team, same as everything else in this file."""
    my_jobs = db.scalars(select(Job).where(Job.owner_user_id.in_(team_owner_ids(db, recruiter)))).all()
    job_ids = [j.id for j in my_jobs]

    applicants: list[Applicant] = []
    if job_ids:
        applicants = db.scalars(select(Applicant).where(Applicant.job_id.in_(job_ids))).all()

    total = len(applicants)
    pipeline_counts = {stage: 0 for stage in PIPELINE_STAGES}
    for a in applicants:
        pipeline_counts[a.pipeline_stage or "new"] = pipeline_counts.get(a.pipeline_stage or "new", 0) + 1

    conversion = {
        stage: round((count / total) * 100, 1) if total else 0.0 for stage, count in pipeline_counts.items()
    }

    accepted = [a for a in applicants if a.pipeline_stage == "hired"]
    time_to_hire_days = None
    if accepted:
        deltas = [(a.updated_at - a.created_at).days for a in accepted if a.updated_at and a.created_at]
        deltas = [d for d in deltas if d >= 0]
        if deltas:
            time_to_hire_days = round(sum(deltas) / len(deltas), 1)

    offers: list[OfferLetter] = []
    applicant_ids = [a.id for a in applicants]
    if applicant_ids:
        offers = db.scalars(select(OfferLetter).where(OfferLetter.applicant_id.in_(applicant_ids))).all()
    offers_sent = sum(1 for o in offers if o.status in ("sent", "accepted", "declined"))
    offers_accepted = sum(1 for o in offers if o.status == "accepted")
    offer_acceptance_rate = round((offers_accepted / offers_sent) * 100, 1) if offers_sent else 0.0

    return {
        "jobs": len(my_jobs),
        "total_applicants": total,
        "pipeline": pipeline_counts,
        "conversion_pct": conversion,
        "time_to_hire_days": time_to_hire_days,
        "offers_sent": offers_sent,
        "offers_accepted": offers_accepted,
        "offer_acceptance_rate_pct": offer_acceptance_rate,
    }


# ---------------------------------------------------------------------------
# V16 — candidate notes, interview scheduling, offer letters.
# ---------------------------------------------------------------------------

class NoteIn(BaseModel):
    note: str = Field(min_length=1, max_length=4000)


@router.post("/applicants/{applicant_id}/notes", status_code=201)
def add_applicant_note(
    applicant_id: int,
    payload: NoteIn,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    """Private note visible only to the recruiter/admin who owns this
    applicant's job — never surfaced to the candidate (contrast with
    reject_reason, which is deliberately candidate-visible)."""
    _owned_applicant_or_404(db, applicant_id, recruiter)
    note = ApplicantNote(applicant_id=applicant_id, author_user_id=recruiter.id, note=payload.note)
    db.add(note)
    log_audit(db, action="add_applicant_note", entity_type="applicant", entity_id=str(applicant_id))
    db.commit()
    db.refresh(note)
    return {"id": note.id, "note": note.note, "created_at": note.created_at}


@router.get("/applicants/{applicant_id}/notes")
def list_applicant_notes(
    applicant_id: int,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    _owned_applicant_or_404(db, applicant_id, recruiter)
    notes = db.scalars(
        select(ApplicantNote).where(ApplicantNote.applicant_id == applicant_id).order_by(ApplicantNote.id.desc())
    ).all()
    return [{"id": n.id, "note": n.note, "author_user_id": n.author_user_id, "created_at": n.created_at} for n in notes]


_INTERVIEW_MODES = ("video", "phone", "onsite")
_INTERVIEW_STATUSES = ("scheduled", "completed", "cancelled", "rescheduled")


class InterviewIn(BaseModel):
    round_name: str = Field(default="Interview", max_length=120)
    mode: str = "video"
    scheduled_at: datetime
    location_or_link: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("mode")
    @classmethod
    def mode_must_be_known(cls, value: str) -> str:
        if value not in _INTERVIEW_MODES:
            raise ValueError(f"mode must be one of {_INTERVIEW_MODES}")
        return value


class InterviewUpdateIn(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def status_must_be_known(cls, value: str) -> str:
        if value not in _INTERVIEW_STATUSES:
            raise ValueError(f"status must be one of {_INTERVIEW_STATUSES}")
        return value


@router.post("/applicants/{applicant_id}/interviews", status_code=201)
def schedule_interview(
    applicant_id: int,
    payload: InterviewIn,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    applicant = _owned_applicant_or_404(db, applicant_id, recruiter)
    interview = Interview(applicant_id=applicant_id, **payload.model_dump())
    db.add(interview)
    # Scheduling an interview is a meaningful pipeline event even if the
    # recruiter hasn't separately PATCHed status="interview" yet — but
    # don't silently overwrite a later stage (e.g. already "hired").
    if applicant.status in ("submitted", "shortlisted"):
        applicant.status = "interview"
    log_audit(db, action="schedule_interview", entity_type="applicant", entity_id=str(applicant_id))
    db.commit()
    db.refresh(interview)

    candidate = db.get(User, applicant.user_id)
    job = db.get(Job, applicant.job_id)
    if candidate and job:
        _notify_candidate_by_email(
            candidate.email,
            f"Interview scheduled — {job.title}",
            f"An interview ({interview.round_name}) has been scheduled for your application to "
            f"{job.title} at {job.organization} on {interview.scheduled_at.isoformat()}."
            + (f"\nDetails: {interview.location_or_link}" if interview.location_or_link else ""),
        )
    return interview


@router.get("/applicants/{applicant_id}/interviews")
def list_interviews(
    applicant_id: int,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    _owned_applicant_or_404(db, applicant_id, recruiter)
    return db.scalars(
        select(Interview).where(Interview.applicant_id == applicant_id).order_by(Interview.scheduled_at)
    ).all()


@router.patch("/interviews/{interview_id}")
def update_interview(
    interview_id: int,
    payload: InterviewUpdateIn,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    interview = db.get(Interview, interview_id)
    if not interview:
        raise HTTPException(404, "Interview not found")
    _owned_applicant_or_404(db, interview.applicant_id, recruiter)
    interview.status = payload.status
    log_audit(db, action="update_interview_status", entity_type="interview", entity_id=str(interview_id), detail=payload.status)
    db.commit()
    db.refresh(interview)
    return interview


class OfferLetterIn(BaseModel):
    position_title: str = Field(min_length=2, max_length=220)
    salary: str | None = Field(default=None, max_length=120)
    start_date: date | None = None
    expiry_date: date | None = None


@router.post("/applicants/{applicant_id}/offer", status_code=201)
def create_offer_letter(
    applicant_id: int,
    payload: OfferLetterIn,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    """Creates (or replaces, while still a draft) an offer letter for
    this applicant. The letter text is generated deterministically —
    see app.services.offer_letters — from exactly these fields, never
    invented by an AI model."""
    applicant = _owned_applicant_or_404(db, applicant_id, recruiter)
    candidate = db.get(User, applicant.user_id)
    job = db.get(Job, applicant.job_id)
    if not candidate or not job:
        raise HTTPException(409, "Applicant's job or candidate record is missing")

    existing = db.scalar(select(OfferLetter).where(OfferLetter.applicant_id == applicant_id))
    if existing and existing.status != "draft":
        raise HTTPException(409, f"An offer already exists with status '{existing.status}' and can't be replaced")

    letter_text = render_offer_letter(
        candidate_name=candidate.full_name,
        organization=job.organization,
        position_title=payload.position_title,
        salary=payload.salary,
        start_date=payload.start_date,
        expiry_date=payload.expiry_date,
    )
    if existing:
        existing.position_title = payload.position_title
        existing.salary = payload.salary
        existing.start_date = payload.start_date
        existing.expiry_date = payload.expiry_date
        existing.letter_text = letter_text
        offer = existing
    else:
        offer = OfferLetter(applicant_id=applicant_id, letter_text=letter_text, **payload.model_dump())
        db.add(offer)
    log_audit(db, action="create_offer_letter", entity_type="applicant", entity_id=str(applicant_id))
    db.commit()
    db.refresh(offer)
    return offer


@router.get("/applicants/{applicant_id}/offer")
def get_offer_letter(
    applicant_id: int,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    _owned_applicant_or_404(db, applicant_id, recruiter)
    offer = db.scalar(select(OfferLetter).where(OfferLetter.applicant_id == applicant_id))
    if not offer:
        raise HTTPException(404, "No offer letter for this applicant")
    return offer


@router.post("/applicants/{applicant_id}/offer/send")
def send_offer_letter(
    applicant_id: int,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    """Moves a draft offer to "sent" and emails the candidate the
    letter text. Separate from creation so a recruiter can review/edit
    a draft (re-POST the same endpoint) before it goes out."""
    applicant = _owned_applicant_or_404(db, applicant_id, recruiter)
    offer = db.scalar(select(OfferLetter).where(OfferLetter.applicant_id == applicant_id))
    if not offer:
        raise HTTPException(404, "No offer letter for this applicant")
    if offer.status != "draft":
        raise HTTPException(409, f"Offer is already '{offer.status}'")

    offer.status = "sent"
    log_audit(db, action="send_offer_letter", entity_type="offer_letter", entity_id=str(offer.id))
    db.commit()
    db.refresh(offer)

    candidate = db.get(User, applicant.user_id)
    if candidate:
        _notify_candidate_by_email(candidate.email, f"Offer: {offer.position_title}", offer.letter_text)
    return offer


@router.post("/applicants/{applicant_id}/offer/withdraw")
def withdraw_offer_letter(
    applicant_id: int,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    _owned_applicant_or_404(db, applicant_id, recruiter)
    offer = db.scalar(select(OfferLetter).where(OfferLetter.applicant_id == applicant_id))
    if not offer:
        raise HTTPException(404, "No offer letter for this applicant")
    if offer.status not in ("draft", "sent"):
        raise HTTPException(409, f"Offer is already '{offer.status}' and can't be withdrawn")
    offer.status = "withdrawn"
    log_audit(db, action="withdraw_offer_letter", entity_type="offer_letter", entity_id=str(offer.id))
    db.commit()
    db.refresh(offer)
    return offer
