"""JOB FEATURES — Stage 0b of the recommendation pipeline.

Derives a ``JobFeatures`` snapshot from one existing ``Job`` row (the
one and only job table — see app.models.domain.Job's docstring: JOB /
GOVERNMENT_RECRUITMENT / INTERNSHIP / APPRENTICESHIP are all the same
table, distinguished by ``job_type``, exactly as V21.1 search already
treats them). No new job data is stored or fabricated here — every
field is read straight off the existing row or derived with the same
shared skills vocabulary V6/V8/V20.2 already use
(``app.services.career.SKILLS`` + ``Job.skills``), so a job's detected
skill set is identical whether it's viewed via matching, resume
scoring, or recommendations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime

from app.models.domain import Job
from app.services.career import SKILLS, job_text


def _parse_job_skills_column(raw: str | None) -> set[str]:
    """``Job.skills`` is written in two different shapes depending on
    which path created the job: the V18.2 recruiter wizard
    (app.api.recruiter) JSON-encodes a list (``'["Python", "SQL"]'``),
    while manual/government ingestion (app.api.admin) never sets this
    column at all (``normalize_job``/``JobRecord`` has no `skills`
    field — see POST /admin/ingest, which explicitly excludes it).
    Neither existing matching engine (app.services.career,
    app.resume_ai.job_match) reads this column at all; both derive a
    job's skill set purely from the shared ``SKILLS`` vocabulary over
    ``job_text()``. This helper adds the recruiter-entered structured
    skills as a *bonus* signal on top of that same vocabulary scan
    (more coverage, e.g. multi-word or non-catalog skills a recruiter
    typed by hand), parsed defensively for both known shapes rather
    than assuming one."""
    if not raw:
        return set()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return {str(s).strip().lower() for s in parsed if str(s).strip()}
    except (ValueError, TypeError):
        pass
    return {s.strip().lower() for s in raw.split(",") if s.strip()}


@dataclass
class JobFeatures:
    job_id: int
    title: str
    organization: str
    organization_id: int | None
    job_type: str  # Government / Private / Internship / Apprenticeship / ...
    is_government: bool
    govt_level: str | None
    category: str | None
    employment_type: str | None
    work_mode: str | None
    industry: str | None
    experience_required: str | None
    location: str
    qualification: str
    salary: str | None
    deadline: date | None
    posted_date: datetime
    status: str
    skills: set[str] = field(default_factory=set)  # from shared SKILLS vocabulary + Job.skills column


def build(job: Job) -> JobFeatures:
    text = job_text(job)
    detected = {s for s in SKILLS if s in text}
    explicit = _parse_job_skills_column(job.skills)
    return JobFeatures(
        job_id=job.id,
        title=job.title,
        organization=job.organization,
        organization_id=job.organization_id,
        job_type=job.job_type,
        is_government=(job.job_type == "Government"),
        govt_level=job.govt_level,
        category=job.category,
        employment_type=job.employment_type,
        work_mode=job.work_mode,
        industry=job.industry,
        experience_required=job.experience_required,
        location=job.location,
        qualification=job.qualification,
        salary=job.salary,
        deadline=job.deadline,
        posted_date=job.created_at,
        status=job.status,
        skills=detected | explicit,
    )


def is_expired(job: Job, *, as_of: date | None = None) -> bool:
    """EXCLUDED JOBS — a deadline that has passed. Deadline passing
    does not automatically flip ``Job.status`` anywhere else in the
    codebase (confirmed against app.scheduler / app.services.automation
    — deadline changes only drive notifications, not status), so this
    must be checked explicitly rather than assumed from status."""
    today = as_of or date.today()
    return job.deadline is not None and job.deadline < today


def is_closed_or_unavailable(job: Job) -> bool:
    """EXCLUDED JOBS — closed, archived, or not yet published. Search
    retrieval (Stage 1) already narrows to visible rows for the actor,
    but this is checked again defensively at ranking time since a job
    fetched by id (e.g. for explanation/feedback endpoints) doesn't
    necessarily go through the search visibility filter."""
    return job.status not in ("published",)
