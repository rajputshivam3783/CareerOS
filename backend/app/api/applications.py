"""V22.1 — Application Tracking Infrastructure API.

Replaces the four bare-bones inline endpoints that used to live in
app/api/platform.py (POST/GET/PUT/DELETE /applications, added back in
V7) with the full production surface the spec calls for — same base
paths, so nothing that already knows "the applications API lives at
/applications" needs to change its base URL. The old `PUT` (full
replace) is superseded by `PATCH` (partial update) per this version's
own spec; nothing in this codebase's frontend used PUT (verified
before removing it — see docs/V22_1_APPLICATION_TRACKING.md).

SECURITY: every endpoint resolves the acting user from `current_user`
(the verified JWT) and passes only that ``u.id`` into
``app.applications.service`` — no endpoint accepts or trusts a
caller-supplied user id. Ownership is enforced inside the service
layer itself (``_get_owned``), not just at this layer, so a bug here
can't accidentally skip it.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.applications import service
from app.applications.status import STATUS_VALUES, InvalidStatusError, TerminalStatusReopenRequiredError
from app.core.security import current_user
from app.db.session import get_db

router = APIRouter()

_VALID_SORT_FIELDS = {"created_at", "updated_at", "applied_on", "deadline", "status_updated_at", "company"}


def _serialize(a) -> dict:
    return {
        "id": a.id,
        "user_id": a.user_id,
        "job_id": a.job_id,
        "company": a.company,
        "job_title": a.job_title or a.role,
        "job_url": a.job_url,
        "location": a.location,
        "employment_type": a.employment_type,
        "source": a.source,
        "salary": a.salary,
        "deadline": a.deadline.isoformat() if a.deadline else None,
        "recruiter_name": a.recruiter_name,
        "recruiter_email": a.recruiter_email,
        "external_reference": a.external_reference,
        "status": a.status,
        "applied_at": a.applied_on.isoformat() if a.applied_on else None,
        "next_deadline": a.next_deadline.isoformat() if a.next_deadline else None,
        "notes": a.notes,
        "status_updated_at": a.status_updated_at.isoformat() if a.status_updated_at else None,
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


def _history_out(h) -> dict:
    import json

    return {
        "id": h.id,
        "application_id": h.application_id,
        "old_status": h.old_status,
        "new_status": h.new_status,
        "changed_at": h.changed_at.isoformat(),
        "metadata": json.loads(h.metadata_json) if h.metadata_json else None,
    }


class ApplicationCreateIn(BaseModel):
    job_id: int | None = None
    company: str = Field(min_length=1, max_length=220)
    job_title: str = Field(min_length=1, max_length=220)
    status: str | None = None
    job_url: str | None = Field(default=None, max_length=1000)
    location: str | None = Field(default=None, max_length=160)
    employment_type: str | None = Field(default=None, max_length=60)
    source: str | None = Field(default=None, max_length=60)
    salary: str | None = Field(default=None, max_length=220)
    deadline: date | None = None
    applied_at: date | None = None
    next_deadline: date | None = None
    recruiter_name: str | None = Field(default=None, max_length=220)
    recruiter_email: str | None = Field(default=None, max_length=255)
    external_reference: str | None = Field(default=None, max_length=120)
    notes: str | None = None

    @field_validator("job_url", "external_reference")
    @classmethod
    def _strip(cls, v):
        return v.strip() if v else v

    @field_validator("job_url")
    @classmethod
    def _validate_url(cls, v):
        # URL VALIDATION — deliberately permissive (this is a
        # candidate's own free-text link, not a link CareerOS re-hosts
        # or redirects through), but must at least look like an
        # http(s) URL, not arbitrary text or another scheme
        # (javascript:, data:, file:, ...).
        if v and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("job_url must start with http:// or https://")
        return v


class ApplicationUpdateIn(BaseModel):
    """Every field optional — PATCH semantics: only fields the caller
    actually sends are changed."""

    job_id: int | None = None
    company: str | None = Field(default=None, min_length=1, max_length=220)
    job_title: str | None = Field(default=None, min_length=1, max_length=220)
    status: str | None = None
    job_url: str | None = Field(default=None, max_length=1000)
    location: str | None = Field(default=None, max_length=160)
    employment_type: str | None = Field(default=None, max_length=60)
    source: str | None = Field(default=None, max_length=60)
    salary: str | None = Field(default=None, max_length=220)
    deadline: date | None = None
    applied_at: date | None = None
    next_deadline: date | None = None
    recruiter_name: str | None = Field(default=None, max_length=220)
    recruiter_email: str | None = Field(default=None, max_length=255)
    external_reference: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    reopen: bool = Field(default=False, description="Required if this PATCH's status field would move a terminal application out of its terminal status.")

    @field_validator("job_url")
    @classmethod
    def _validate_url(cls, v):
        if v and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("job_url must start with http:// or https://")
        return v


class StatusChangeIn(BaseModel):
    status: str = Field(description=f"One of {STATUS_VALUES}")
    note: str | None = Field(default=None, max_length=500)
    reopen: bool = Field(
        default=False,
        description="Required to move an application out of a terminal status (ACCEPTED/REJECTED/WITHDRAWN) — see V22_2_APPLICATION_DASHBOARD.md's status transition rules.",
    )


@router.post("/applications", status_code=201)
def create_application(payload: ApplicationCreateIn, u=Depends(current_user), db: Session = Depends(get_db)):
    """EXTERNAL APPLICATIONS: create a manually-tracked application
    (job_id omitted/omitted -> NULL). For a CareerOS job, prefer
    ``POST /jobs/{job_id}/applications`` (APPLY FROM CAREEROS JOB),
    which auto-fills company/job_title/location/etc. from the job
    itself — this endpoint still accepts an explicit job_id too, for a
    caller that already has all the fields on hand."""
    try:
        record = service.create_application(
            db, u.id,
            job_id=payload.job_id,
            company=payload.company,
            job_title=payload.job_title,
            status=payload.status,
            job_url=payload.job_url,
            location=payload.location,
            employment_type=payload.employment_type,
            source=payload.source or ("careeros" if payload.job_id else "external"),
            salary=payload.salary,
            deadline=payload.deadline,
            applied_on=payload.applied_at,
            next_deadline=payload.next_deadline,
            recruiter_name=payload.recruiter_name,
            recruiter_email=payload.recruiter_email,
            external_reference=payload.external_reference,
            notes=payload.notes,
        )
    except service.ApplicationNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.DuplicateApplicationError as exc:
        raise HTTPException(409, str(exc)) from exc
    except InvalidStatusError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _serialize(record)


@router.post("/jobs/{job_id}/applications", status_code=201)
def track_application(
    job_id: int,
    mark_applied: bool = Query(default=False, description='true = "Mark as Applied", false = "Track Application"'),
    u=Depends(current_user),
    db: Session = Depends(get_db),
):
    """APPLY FROM CAREEROS JOB — "Track Application" or "Mark as
    Applied" from a job's own page. Does not touch the Job entity or
    create a recruiter-visible Applicant row (see
    POST /jobs/{job_id}/apply in app/api/platform.py for that,
    unrelated, flow) — this only creates/tracks the candidate's own
    private application record, linked via job_id."""
    try:
        record = service.create_from_job(db, u.id, job_id=job_id, mark_applied=mark_applied)
    except service.ApplicationNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.DuplicateApplicationError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _serialize(record)


@router.get("/applications")
def list_applications(
    status: str | None = Query(default=None),
    company: str | None = Query(default=None),
    source: str | None = Query(default=None),
    job_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200, description="SEARCH: matches company, job title, or location"),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    upcoming_days: int | None = Query(default=None, ge=1, le=365, description="Legacy V7 filter — kept for backward compatibility"),
    u=Depends(current_user),
    db: Session = Depends(get_db),
):
    if sort_by not in _VALID_SORT_FIELDS:
        raise HTTPException(422, f"sort_by must be one of {sorted(_VALID_SORT_FIELDS)}")

    if upcoming_days is not None:
        # V7 backward-compat shape: a flat list filtered to an
        # upcoming next_deadline window, no pagination envelope — kept
        # exactly as it worked before so nothing that already calls
        # `GET /applications?upcoming_days=30` breaks.
        from datetime import timedelta

        from sqlalchemy import select

        from app.models.domain import Application

        horizon = date.today() + timedelta(days=upcoming_days)
        rows = db.scalars(
            select(Application)
            .where(
                Application.user_id == u.id,
                Application.next_deadline.is_not(None),
                Application.next_deadline <= horizon,
            )
            .order_by(Application.next_deadline.asc(), Application.id.desc())
        ).all()
        return [_serialize(a) for a in rows]

    try:
        filters = service.ApplicationFilters(
            status=status, company=company, source=source, job_id=job_id, date_from=date_from, date_to=date_to, search=search,
        )
        items, total = service.list_applications(
            db, u.id, filters=filters, sort_by=sort_by, sort_dir=sort_dir, limit=limit, offset=offset,
        )
    except InvalidStatusError as exc:
        raise HTTPException(422, str(exc)) from exc

    return {
        "items": [_serialize(a) for a in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/applications/stats")
def application_stats(u=Depends(current_user), db: Session = Depends(get_db)):
    return service.get_stats(db, u.id)


@router.get("/applications/dashboard")
def application_dashboard(u=Depends(current_user), db: Session = Depends(get_db)):
    """V22.2 — the richer dashboard surface: everything /stats has,
    plus this-week/this-month counts, upcoming deadlines, and
    stage-conversion rates. Kept as a separate endpoint rather than
    changing /stats's existing response shape, since other callers
    (the candidate dashboard widget, V22.1's own tests) already depend
    on /stats returning exactly {total, by_status, recent_activity}."""
    return service.get_dashboard(db, u.id)


@router.get("/applications/upcoming-deadlines")
def upcoming_deadlines(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
    u=Depends(current_user),
    db: Session = Depends(get_db),
):
    return service.get_upcoming_deadlines(db, u.id, days=days, limit=limit)


@router.get("/applications/{application_id}")
def get_application(application_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        record = service.get_application(db, u.id, application_id)
    except service.ApplicationNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _serialize(record)


@router.patch("/applications/{application_id}")
def update_application(application_id: int, payload: ApplicationUpdateIn, u=Depends(current_user), db: Session = Depends(get_db)):
    fields = payload.model_dump(exclude_unset=True, exclude={"reopen"})
    if "applied_at" in fields:
        fields["applied_on"] = fields.pop("applied_at")
    try:
        record = service.update_application(db, u.id, application_id, reopen=payload.reopen, **fields)
    except service.ApplicationNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except InvalidStatusError as exc:
        raise HTTPException(422, str(exc)) from exc
    except TerminalStatusReopenRequiredError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _serialize(record)


@router.delete("/applications/{application_id}", status_code=204)
def delete_application(application_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        service.delete_application(db, u.id, application_id)
    except service.ApplicationNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/applications/{application_id}/status")
def change_status(application_id: int, payload: StatusChangeIn, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        record = service.change_status(
            db, u.id, application_id, payload.status,
            metadata={"note": payload.note} if payload.note else None,
            reopen=payload.reopen,
        )
    except service.ApplicationNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except InvalidStatusError as exc:
        raise HTTPException(422, str(exc)) from exc
    except TerminalStatusReopenRequiredError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _serialize(record)


@router.get("/applications/{application_id}/history")
def application_history(application_id: int, u=Depends(current_user), db: Session = Depends(get_db)):
    try:
        rows = service.get_history(db, u.id, application_id)
    except service.ApplicationNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return [_history_out(h) for h in rows]
