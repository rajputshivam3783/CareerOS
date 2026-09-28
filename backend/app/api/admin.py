"""V9 Admin — review queue, publish/reject/delete, manual ingestion, stats."""

import secrets
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.validators import http_url_validator
from app.core.audit import log_audit
from app.core.config import settings
from app.core.constants import RECRUITMENT_UPDATE_TYPES
from app.core.rate_limit import enforce_rate_limit
from app.core.request_context import Actor, set_actor
from app.core.hardening import safe_equals
from app.core.security import access_token_session_is_active, decode_access_token, hash_password
from app.core.security_events import SecurityEvent, record_security_event
from app.core.sessions import list_active_sessions, revoke_session_by_id_admin
from app.db.session import get_db
from app.ingestion.adapters.generic_metadata import GenericMetadataAdapter
from app.ingestion.ingest import run_all_enabled_sources, run_ingestion
from app.ingestion.models.job_record import JobRecord
from app.ingestion.services.normalize import normalize_job
from app.ingestion.services.pdf_parser import parse_notification_fields
from app.ingestion.services.publisher import publish_to_review
from app.ingestion.sources import SOURCES
from app.models.domain import (
    Application,
    AuditLog,
    ExamPrepResource,
    IngestionRun,
    Job,
    Partner,
    RecruitmentUpdate,
    User,
)
from app.services.job_moderation import approve_job, reject_job
from app.search.hooks import sync_company, sync_job

router = APIRouter()


async def guard(
    request: Request,
    x_admin_key: str = Header(default=""),
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> None:
    """V16 — dual-mode admin auth, kept backward compatible.

    Every admin route in this file has always authenticated with one
    shared static key (``X-Admin-Key``) rather than a per-admin login
    — there's no admin login page, and the frontend admin panel only
    ever asks for that one key (see ``frontend/src/app/admin/page.tsx``).
    That's still accepted as-is here, unchanged, so nothing that relies
    on it today breaks.

    What's new: a request can *instead* authenticate as a logged-in
    User with role="admin" via a normal ``Authorization: Bearer``
    JWT (the same token issued by ``/auth/login``). Neither path is
    required over the other — whichever credential is present is
    checked. This exists so audit rows can name a real admin user
    (``app.core.request_context.set_actor``) instead of only ever
    recording "the shared key was used", which is true today for
    every single admin action regardless of which human triggered it.

    The static key itself is rate-limited (a wrong X-Admin-Key was
    previously accepted with unlimited retries — this closes that
    brute-force gap the same way login/register already are).
    """
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            claims = decode_access_token(token)
            user = db.get(User, int(claims["sub"]))
            # V25.6: a revoked session's token no longer grants admin access.
            if user is not None and not access_token_session_is_active(db, claims):
                user = None
        except Exception:
            user = None
        if user and user.active and user.role in ("admin", "super_admin"):
            set_actor(Actor(actor_type="user", actor_id=str(user.id), label=user.email))
            return
        raise HTTPException(403, "Admin role required")

    enforce_rate_limit(request, bucket="admin-key")
    # V25.6: the shared key can be switched off (ADMIN_KEY_AUTH_ENABLED=false) once named
    # admin accounts exist; comparison is bytes-safe so a non-ASCII header is a 401, not a 500.
    if not settings.admin_key_auth_enabled or not safe_equals(x_admin_key, settings.admin_api_key):
        raise HTTPException(401, "Invalid admin key")
    set_actor(Actor(actor_type="admin_key", actor_id=None, label="shared admin key"))


def _current_actor_user_id() -> int | None:
    """The logged-in administrator's user id, or None when the request
    authenticated with the shared X-Admin-Key (which has no user row).

    ``guard`` above already put the actor in request context; reading
    it back here avoids changing any route signature to thread a User
    through purely so moderation records can be attributed.
    """
    from app.core.request_context import get_actor

    actor = get_actor()
    if actor is None or actor.actor_type != "user" or not actor.actor_id:
        return None
    try:
        return int(actor.actor_id)
    except (TypeError, ValueError):
        return None


@router.get("/review", dependencies=[Depends(guard)])
def review(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    return db.scalars(
        select(Job).where(Job.status == "review").order_by(Job.id.desc()).limit(limit).offset(offset)
    ).all()


@router.post("/jobs/{job_id}/publish", dependencies=[Depends(guard)])
def publish(job_id: int, db: Session = Depends(get_db)):
    """V9 publish. Unchanged contract (same path, same response body).

    V25.2 — the body of the transition moved into
    ``app.services.job_moderation.approve_job``, which this now calls,
    so this route and the new POST /admin/jobs/{id}/approve are one
    publication system rather than two implementations that could
    drift (spec section 8). The V24.1 published_at rule lives there
    now and is unchanged.
    """
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    approve_job(db, job, actor_user_id=_current_actor_user_id())
    log_audit(db, action="publish_job", entity_type="job", entity_id=str(job_id))
    db.commit()
    sync_job(db, job_id)  # V21.1 Phase 3
    return {"published": True, "id": job_id}


class JobLifecycleUpdate(BaseModel):
    """V7 — fields that typically arrive *after* initial publication as
    a recruitment moves through its lifecycle. All optional: send only
    the fields that changed."""

    deadline: date | None = None
    exam_date: date | None = None
    admit_card_url: str | None = None
    admit_card_date: date | None = None
    result_url: str | None = None
    result_date: date | None = None
    _validate_urls = http_url_validator("admit_card_url", "result_url")


@router.patch("/jobs/{job_id}", dependencies=[Depends(guard)])
def update_job_lifecycle(job_id: int, payload: JobLifecycleUpdate, db: Session = Depends(get_db)):
    """Update exam-lifecycle fields on an existing posting (e.g. once
    admit cards or results are announced) without re-creating it as a
    new listing. Triggers a notification scan afterward so anyone who
    saved/applied to this job hears about the update — see
    app/services/notifications.py."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(job, key, value)

    log_audit(db, action="update_job_lifecycle", entity_type="job", entity_id=str(job_id), detail=str(changes))
    db.commit()
    sync_job(db, job_id)  # V21.1 Phase 3

    from app.services.notifications import scan_and_notify

    scan_and_notify(db)

    return {"updated": True, "id": job_id, "changes": changes}


class RejectJobIn(BaseModel):
    """V25.2 — the structured moderation reason spec section 9 asks
    for, as an OPTIONAL body so every pre-V25.2 caller that posts to
    this route with no body at all keeps working unchanged (see
    tests/test_v21_1_unified_search.py, which does exactly that).

    ``note`` is the administrator's internal note. It is stored on the
    job but never returned by any recruiter- or candidate-facing
    endpoint — see app.services.job_moderation.
    """

    reason: str = "other"
    note: str | None = Field(default=None, max_length=4000)


@router.post("/jobs/{job_id}/reject", dependencies=[Depends(guard)])
def reject(job_id: int, payload: RejectJobIn | None = None, db: Session = Depends(get_db)):
    """V9 reject, extended in place rather than duplicated.

    Spec section 29 forbids a second route for this; section 9 asks
    for a structured reason. Both are satisfied by making the reason
    an optional body on the existing path, defaulting to "other" so a
    caller that sends nothing still produces a valid, if unspecific,
    moderation record instead of a NULL one.
    """
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    reason = payload.reason if payload else "other"
    note = payload.note if payload else None
    reject_job(db, job, reason=reason, actor_user_id=_current_actor_user_id(), note=note)
    log_audit(db, action="reject_job", entity_type="job", entity_id=str(job_id), detail=f"reason={reason}")
    db.commit()
    sync_job(db, job_id)  # V21.1 Phase 3
    return {"rejected": True, "id": job_id, "reason": reason}


@router.delete("/jobs/{job_id}", dependencies=[Depends(guard)], status_code=204)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    log_audit(db, action="delete_job", entity_type="job", entity_id=str(job_id))
    db.delete(job)
    db.commit()
    sync_job(db, job_id)  # V21.1 Phase 3 — index_job() removes the now-stale search document


class ManualJob(BaseModel):
    title: str
    organization: str
    description: str = "See official notification"
    qualification: str = "See official notification"
    location: str = "India"
    job_type: str = "Government"
    source_name: str = "Manual Admin"
    source_reference: str | None = None
    official_url: str | None = None
    notification_url: str | None = None
    apply_url: str | None = None
    deadline: date | None = None
    skills: str | None = None
    # V19.1 — Government Recruitment Core. Optional; omitting these
    # keeps ManualJob behaving exactly as it did before V19.1.
    ad_number: str | None = None
    answer_key_url: str | None = None
    organization_id: int | None = None
    _validate_urls = http_url_validator("official_url", "notification_url", "apply_url", "answer_key_url")


@router.post("/ingest", dependencies=[Depends(guard)], status_code=201)
def ingest(payload: ManualJob, db: Session = Depends(get_db)):
    record = normalize_job(JobRecord(**payload.model_dump(exclude={"skills"})))
    from app.ingestion.services.enrichment import enrich_record
    record = normalize_job(enrich_record(record, db))
    created, job = publish_to_review(db, record)
    if created:
        log_audit(db, action="manual_ingest", entity_type="job", entity_id=str(job.id))
        db.commit()
        sync_job(db, job.id)  # V21.1 Phase 3
    return {"created": created, "job_id": job.id if job else None}


@router.post("/ingest/bulk", dependencies=[Depends(guard)], status_code=201)
def ingest_bulk(payload: list[ManualJob], db: Session = Depends(get_db)):
    """V16 — batch version of POST /ingest, for curating a whole batch
    of hand-verified government notices (e.g. a state PSC's weekly
    notice list) in one call instead of one request per record. Each
    item goes through the exact same normalize -> deduplicate ->
    review pipeline as a single manual entry — nothing here
    auto-publishes, and one bad record in the batch doesn't fail the
    rest (its error is reported per-item instead)."""
    if len(payload) > 200:
        raise HTTPException(422, "Bulk ingest is limited to 200 records per request")

    results = []
    created_count = 0
    for i, item in enumerate(payload):
        try:
            record = normalize_job(JobRecord(**item.model_dump(exclude={"skills"})))
            from app.ingestion.services.enrichment import enrich_record
            record = normalize_job(enrich_record(record, db))
            created, job = publish_to_review(db, record)
            if created:
                created_count += 1
                sync_job(db, job.id)  # V21.1 Phase 3
            results.append({"index": i, "created": created, "job_id": job.id if job else None})
        except Exception as exc:  # noqa: BLE001 — one bad record shouldn't sink the batch
            results.append({"index": i, "created": False, "error": str(exc)})

    log_audit(db, action="manual_ingest_bulk", entity_type="job", detail=f"{created_count}/{len(payload)} created")
    db.commit()
    return {"total": len(payload), "created": created_count, "results": results}


@router.get("/stats", dependencies=[Depends(guard)])
def stats(db: Session = Depends(get_db)):
    return {
        "users": db.scalar(select(func.count()).select_from(User)),
        "jobs": db.scalar(select(func.count()).select_from(Job)),
        "review": db.scalar(select(func.count()).select_from(Job).where(Job.status == "review")),
        "published": db.scalar(select(func.count()).select_from(Job).where(Job.status == "published")),
        "applications": db.scalar(select(func.count()).select_from(Application)),
    }


# --- V2 automated collection -------------------------------------------------


@router.get("/ingest/sources", dependencies=[Depends(guard)])
def list_sources():
    """List configured V2 collection sources and whether each is enabled.

    See app/ingestion/sources.py to enable one — each carries a note on
    what must be re-verified against the live site first.
    """
    return [{"name": s.name, "enabled": s.enabled, "notes": s.notes} for s in SOURCES]


@router.post("/ingest/run", dependencies=[Depends(guard)])
def run_ingest_now(source: str | None = None, db: Session = Depends(get_db)):
    """Trigger an ingestion pass immediately, instead of waiting for the
    scheduled interval. Pass ``?source=<name>`` to run just one enabled
    source, or omit it to run every enabled source."""
    if source:
        match = next((s for s in SOURCES if s.name == source), None)
        if not match:
            raise HTTPException(404, "Unknown source")
        if not match.enabled:
            raise HTTPException(409, "Source is disabled — enable it in app/ingestion/sources.py first")
        results = [run_ingestion(db, match.build())]
    else:
        results = run_all_enabled_sources(db)

    log_audit(db, action="ingest_run", entity_type="ingestion", detail=str(results)[:2000])
    db.commit()
    return {"runs": results}


@router.get("/ingest/runs", dependencies=[Depends(guard)])
def ingest_run_history(db: Session = Depends(get_db)):
    return db.scalars(select(IngestionRun).order_by(IngestionRun.id.desc()).limit(50)).all()


# --- V7 notifications ---------------------------------------------------------


@router.post("/notifications/scan", dependencies=[Depends(guard)])
def run_notification_scan(db: Session = Depends(get_db)):
    """Trigger a deadline/admit-card/result notification scan
    immediately, instead of waiting for the hourly schedule — mirrors
    `POST /admin/ingest/run` for the V2 pipeline."""
    from app.services.notifications import scan_and_notify

    return scan_and_notify(db)


# --- V3 private-careers partners ---------------------------------------------


class PartnerIn(BaseModel):
    name: str
    contact_email: str


@router.post("/partners", dependencies=[Depends(guard)], status_code=201)
def create_partner(payload: PartnerIn, db: Session = Depends(get_db)):
    """Register an employer/aggregator as a V3 submission partner.

    Returns the plaintext API key exactly once — only its hash is
    stored, so if it's lost the only recovery is issuing a new one.
    """
    api_key = secrets.token_urlsafe(32)
    partner = Partner(
        name=payload.name,
        contact_email=payload.contact_email,
        api_key_hash=hash_password(api_key),
    )
    db.add(partner)
    log_audit(db, action="create_partner", entity_type="partner", entity_id=payload.name)
    db.commit()
    db.refresh(partner)
    return {
        "id": partner.id,
        "name": partner.name,
        "api_key": api_key,
        "note": "Store this key now — it will not be shown again.",
    }


@router.get("/partners", dependencies=[Depends(guard)])
def list_partners(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    partners = db.scalars(select(Partner).order_by(Partner.id.desc()).limit(limit).offset(offset)).all()
    return [{"id": p.id, "name": p.name, "contact_email": p.contact_email, "active": p.active} for p in partners]


@router.post("/partners/{partner_id}/deactivate", dependencies=[Depends(guard)])
def deactivate_partner(partner_id: int, db: Session = Depends(get_db)):
    partner = db.get(Partner, partner_id)
    if not partner:
        raise HTTPException(404, "Partner not found")
    partner.active = False
    log_audit(db, action="deactivate_partner", entity_type="partner", entity_id=str(partner_id))
    db.commit()
    return {"deactivated": True, "id": partner_id}


# --- V5 notification PDF parsing ---------------------------------------------


@router.post("/ingest/pdf", dependencies=[Depends(guard)], status_code=201)
async def ingest_pdf(
    title: str = Form(...),
    organization: str = Form(...),
    source_name: str = Form("Manual PDF upload"),
    job_type: str = Form("Government"),
    official_url: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a notification PDF; best-effort extract qualification, age
    limit, vacancies, fee, and dates from its text, then send the
    result into the normal review queue.

    This is heuristic extraction (see app/ingestion/services/pdf_parser.py)
    — the response's ``extraction.fields_found`` list shows exactly
    which fields were actually detected so a reviewer knows what still
    needs manual entry, and the created job always lands in `review`,
    never published automatically.
    """
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(400, "Expected a PDF file")

    from app.core.config import settings
    from app.core.uploads import read_upload_limited

    pdf_bytes = await read_upload_limited(
        file,
        max_bytes=settings.notification_pdf_max_upload_mb * 1024 * 1024,
        allowed_extensions={".pdf"},
        allowed_content_types={"application/pdf", "application/octet-stream"},
    )
    extracted = parse_notification_fields(pdf_bytes)

    record = {
        "title": title,
        "organization": organization,
        "official_url": official_url,
        "notification_url": official_url,
        "qualification": extracted["qualification"] or "See official notification",
        "age_limit": extracted["age_limit"],
        "vacancies": extracted["vacancies"],
        "application_fee": extracted["application_fee"],
        "deadline": extracted["deadline"],
        "exam_date": extracted["exam_date"],
        "description": (
            f"Extracted from uploaded PDF '{file.filename}'. "
            f"Fields detected: {', '.join(extracted['fields_found']) or 'none'}."
        ),
    }

    adapter = GenericMetadataAdapter(source_name=source_name, job_type=job_type, records=[record])
    result = run_ingestion(db, adapter)
    log_audit(db, action="pdf_ingest", entity_type="job", detail=f"file={file.filename}")
    db.commit()
    return {**result, "extraction": extracted}


# --- V8 exam-prep resource curation ------------------------------------------


class ExamPrepIn(BaseModel):
    organization: str
    exam_name: str
    resource_type: str  # syllabus / previous_papers / mock_test / cutoff / study_material
    title: str
    url: str
    description: str | None = None
    job_id: int | None = None


@router.post("/exam-prep", dependencies=[Depends(guard)], status_code=201)
def create_exam_prep_resource(payload: ExamPrepIn, db: Session = Depends(get_db)):
    """Curate an exam-prep link (syllabus/previous papers/mock test/
    cutoff/study material). Deliberately admin-curated rather than
    generated — see the docstring on ExamPrepResource in
    app/models/domain.py for why."""
    if payload.job_id and not db.get(Job, payload.job_id):
        raise HTTPException(404, "Job not found")

    resource = ExamPrepResource(**payload.model_dump())
    db.add(resource)
    log_audit(db, action="create_exam_prep", entity_type="exam_prep_resource", entity_id=payload.title)
    db.commit()
    db.refresh(resource)
    return resource


@router.get("/exam-prep", dependencies=[Depends(guard)])
def list_exam_prep_resources(
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db)
):
    return db.scalars(select(ExamPrepResource).order_by(ExamPrepResource.id.desc()).limit(limit).offset(offset)).all()


@router.delete("/exam-prep/{resource_id}", dependencies=[Depends(guard)], status_code=204)
def delete_exam_prep_resource(resource_id: int, db: Session = Depends(get_db)):
    resource = db.get(ExamPrepResource, resource_id)
    if not resource:
        raise HTTPException(404, "Resource not found")
    db.delete(resource)
    log_audit(db, action="delete_exam_prep", entity_type="exam_prep_resource", entity_id=str(resource_id))
    db.commit()


# --- V9 recruiter role management ---------------------------------------------

_VALID_ROLES = ("candidate", "recruiter", "admin", "super_admin")


class RoleIn(BaseModel):
    role: str


@router.post("/users/{user_id}/role", dependencies=[Depends(guard)])
def set_user_role(user_id: int, payload: RoleIn, db: Session = Depends(get_db)):
    """Grant or revoke the recruiter/admin role for a registered user.

    Deliberately admin-only: a candidate can't self-elevate by
    registering with a chosen role (POST /auth/register always creates
    a plain "candidate") — someone has to actually vet and grant
    recruiter access, the same trust boundary V3's partner onboarding
    already uses.
    """
    if payload.role not in _VALID_ROLES:
        raise HTTPException(400, f"role must be one of {_VALID_ROLES}")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    user.role = payload.role
    if payload.role == "recruiter":
        user.recruiter_status = "approved"
    elif payload.role == "candidate":
        user.recruiter_status = None
    log_audit(db, action="set_user_role", entity_type="user", entity_id=str(user_id), detail=payload.role)
    db.commit()
    return {"id": user_id, "role": user.role}


class CreateAdminUser(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = "admin"


@router.post("/create-admin-user", dependencies=[Depends(guard)], status_code=201)
def create_admin_user(payload: CreateAdminUser, db: Session = Depends(get_db)):
    """V17.1 — the only way an admin or super_admin account comes into
    existence. Deliberately not reachable without the same credential
    every other route in this file requires (shared X-Admin-Key, or a
    Bearer JWT for an existing admin/super_admin user) — there is no
    public admin registration endpoint anywhere in app.api.auth.

    Password is validated with the same policy as public registration
    (see app.api.auth.Register) so admin accounts aren't held to a
    lower bar than everyone else's.
    """
    if payload.role not in ("admin", "super_admin"):
        raise HTTPException(400, "role must be 'admin' or 'super_admin'")

    email = payload.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already registered")

    if len(payload.password) < settings.password_min_length:
        raise HTTPException(400, f"Password must be at least {settings.password_min_length} characters")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        role=payload.role,
        active=True,
        # Admin-provisioned accounts are trusted at creation time —
        # there's no public signup step to gate behind email OTP.
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_audit(db, action="create_admin_user", entity_type="user", entity_id=str(user.id), detail=payload.role)
    db.commit()
    return {"id": user.id, "email": user.email, "role": user.role}


# V25.2 — ``GET /admin/users`` moved to app.api.admin_platform, where it
# gained search, filtering, pagination and explicit platform-admin
# authorization. It was NOT duplicated there (spec section 29 forbids a
# second route for the same thing): the path is identical and every
# field this version returned (id, email, full_name, role, active) is
# still present on each result, now inside the standard
# {total, limit, offset, results} envelope. Removed from this file so
# exactly one handler owns the path — with both registered, FastAPI
# would silently serve whichever router was mounted first.


# ---------------------------------------------------------------------------
# V17.2 — account lockout admin controls, failed-login/security visibility,
# and session management. See app.core.account_lockout and
# app.core.security_events for the underlying mechanisms.
# ---------------------------------------------------------------------------


class LockUserIn(BaseModel):
    permanent: bool = False
    minutes: int | None = Field(default=None, ge=1, le=525600)
    reason: str | None = Field(default=None, max_length=500)


@router.post("/users/{user_id}/lock", dependencies=[Depends(guard)])
def lock_user(user_id: int, payload: LockUserIn, db: Session = Depends(get_db)):
    """Admin-initiated lock, independent of the automatic lockout in
    app.core.account_lockout (which is triggered by repeated failed
    logins). ``permanent=true`` deactivates the account outright
    (reuses ``User.active`` — see account_lockout.py's module
    docstring for why); otherwise it's a temporary lock for
    ``minutes`` (default: settings.default_admin_lock_minutes)."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    if payload.permanent:
        user.active = False
        detail = f"permanent: {payload.reason}" if payload.reason else "permanent"
    else:
        minutes = payload.minutes or settings.default_admin_lock_minutes
        user.locked_until = datetime.utcnow() + timedelta(minutes=minutes)
        detail = f"temporary {minutes}min: {payload.reason}" if payload.reason else f"temporary {minutes}min"

    record_security_event(db, SecurityEvent.ACCOUNT_LOCKED, entity_type="user", entity_id=str(user_id), detail=detail)
    db.commit()
    return {"id": user_id, "active": user.active, "locked_until": user.locked_until}


@router.post("/users/{user_id}/unlock", dependencies=[Depends(guard)])
def unlock_user(user_id: int, db: Session = Depends(get_db)):
    """Reverses both a temporary lock (locked_until) and a permanent
    one (active=False) — the caller doesn't need to know which kind is
    in effect. Resets failed_login_count so the account isn't
    immediately re-locked by attempts made while it was locked out;
    lock_count (the escalation counter for future lock durations) is
    deliberately left as-is — see app.core.account_lockout."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    user.active = True
    user.locked_until = None
    user.failed_login_count = 0
    record_security_event(db, SecurityEvent.ACCOUNT_UNLOCKED, entity_type="user", entity_id=str(user_id))
    db.commit()
    return {"id": user_id, "active": user.active, "locked_until": user.locked_until}


@router.get("/security/locked-accounts", dependencies=[Depends(guard)])
def locked_accounts(db: Session = Depends(get_db)):
    """Accounts currently locked — either temporarily (locked_until in
    the future) or permanently (active=False). Does not include
    accounts with an *expired* temporary lock (locked_until in the
    past but not yet cleared) — those self-clear on next login attempt
    (see account_lockout.clear_lock_if_expired) and aren't actually
    blocking anyone, so listing them here would be misleading."""
    now = datetime.utcnow()
    permanent = db.scalars(select(User).where(User.active == False)).all()  # noqa: E712
    temporary = db.scalars(select(User).where(User.locked_until.is_not(None), User.locked_until > now)).all()
    return {
        "permanent": [{"id": u.id, "email": u.email, "full_name": u.full_name} for u in permanent],
        "temporary": [
            {
                "id": u.id,
                "email": u.email,
                "full_name": u.full_name,
                "locked_until": u.locked_until,
                "lock_count": u.lock_count,
            }
            for u in temporary
        ],
    }


@router.get("/security/failed-logins", dependencies=[Depends(guard)])
def failed_logins(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Recent failed-login and locked-account-login-attempt events —
    a filtered view over the same audit_logs table GET /admin/audit-logs
    already exposes, scoped to what a security review actually wants
    to see first."""
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.action.in_(["login_failed", "login_blocked_locked_account"]))
        .order_by(AuditLog.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": r.id,
            "action": r.action,
            "entity_id": r.entity_id,
            "ip_address": r.ip_address,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/users/{user_id}/sessions", dependencies=[Depends(guard)])
def user_sessions(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return [
        {
            "id": s.id,
            "device_id": s.device_id,
            "device_label": s.device_label,
            "ip_address": s.ip_address,
            "user_agent": s.user_agent,
            "created_at": s.created_at,
            "last_seen_at": s.last_seen_at,
        }
        for s in list_active_sessions(db, user)
    ]


@router.post("/sessions/{session_id}/revoke", dependencies=[Depends(guard)])
def admin_revoke_session(session_id: int, db: Session = Depends(get_db)):
    session_row = revoke_session_by_id_admin(db, session_id)
    if not session_row:
        raise HTTPException(404, "Session not found")
    record_security_event(
        db,
        SecurityEvent.SESSION_REVOKED,
        entity_type="user_session",
        entity_id=str(session_id),
        detail=f"admin-revoked, user_id={session_row.user_id}",
    )
    db.commit()
    return {"revoked": True, "user_id": session_row.user_id}


@router.get("/recruiters/pending", dependencies=[Depends(guard)])
def pending_recruiters(db: Session = Depends(get_db)):
    return [
        {
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "email_verified": u.email_verified,
            "status": u.recruiter_status,
        }
        for u in db.scalars(select(User).where(User.recruiter_status == "pending")).all()
    ]


@router.post("/recruiters/{user_id}/approve", dependencies=[Depends(guard)])
def approve_recruiter(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user or user.recruiter_status != "pending":
        raise HTTPException(404, "Pending recruiter not found")
    if not user.email_verified:
        raise HTTPException(400, "Recruiter must verify email first")
    user.role = "recruiter"
    user.recruiter_status = "approved"
    log_audit(db, action="approve_recruiter", entity_type="user", entity_id=str(user_id))
    db.commit()
    return {"approved": True, "id": user_id}


@router.post("/recruiters/{user_id}/reject", dependencies=[Depends(guard)])
def reject_recruiter(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user or user.recruiter_status != "pending":
        raise HTTPException(404, "Pending recruiter not found")
    user.recruiter_status = "rejected"
    log_audit(db, action="reject_recruiter", entity_type="user", entity_id=str(user_id))
    db.commit()
    return {"rejected": True, "id": user_id}


# --- V14 government recruitment lifecycle -----------------------------------
class RecruitmentUpdateIn(BaseModel):
    update_type: str
    title: str
    event_date: date | None = None
    source_url: str | None = None
    official: bool = True
    _validate_urls = http_url_validator("source_url")


_ALLOWED_UPDATE_TYPES = RECRUITMENT_UPDATE_TYPES


@router.post("/jobs/{job_id}/updates", dependencies=[Depends(guard)], status_code=201)
def create_recruitment_update(job_id: int, payload: RecruitmentUpdateIn, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.job_type.lower() != "government":
        raise HTTPException(409, "Lifecycle hub is for government recruitments")
    if payload.update_type not in _ALLOWED_UPDATE_TYPES:
        raise HTTPException(400, f"update_type must be one of {sorted(_ALLOWED_UPDATE_TYPES)}")
    row = RecruitmentUpdate(job_id=job_id, **payload.model_dump())
    db.add(row)
    log_audit(
        db, action="create_recruitment_update", entity_type="job", entity_id=str(job_id), detail=payload.update_type
    )
    db.commit()
    db.refresh(row)
    return row


@router.delete("/updates/{update_id}", dependencies=[Depends(guard)], status_code=204)
def delete_recruitment_update(update_id: int, db: Session = Depends(get_db)):
    row = db.get(RecruitmentUpdate, update_id)
    if not row:
        raise HTTPException(404, "Update not found")
    log_audit(db, action="delete_recruitment_update", entity_type="recruitment_update", entity_id=str(update_id))
    db.delete(row)
    db.commit()


@router.get("/audit-logs", dependencies=[Depends(guard)])
def list_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    action: str | None = Query(default=None, description="Exact match on action, e.g. 'publish_job'"),
    entity_type: str | None = Query(default=None, description="Exact match on entity_type, e.g. 'job'"),
    db: Session = Depends(get_db),
):
    """V16 — read access to the audit trail. Audit rows were already
    being written for every admin/auth action (see the log_audit call
    sites throughout this file and app/api/auth.py); this is the first
    endpoint that lets anyone actually read them back rather than only
    querying the database directly.

    Rows written before this version have actor_type/actor_id as
    NULL — that's expected, not a bug: those columns didn't exist yet
    (see migrations/v16_backend_hardening.sql), so there's nothing to
    backfill them from.
    """
    query = select(AuditLog).order_by(AuditLog.id.desc())
    if action:
        query = query.where(AuditLog.action == action)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    rows = db.scalars(query.limit(limit).offset(offset)).all()
    total = db.scalar(select(func.count()).select_from(AuditLog)) or 0
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": [
            {
                "id": r.id,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "detail": r.detail,
                "actor_type": r.actor_type,
                "actor_id": r.actor_id,
                "actor_label": r.actor_label,
                "request_id": r.request_id,
                "ip_address": r.ip_address,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    }


# --- V18.1 Company verification ----------------------------------------
@router.get("/companies/pending", dependencies=[Depends(guard)])
def pending_companies(db: Session = Depends(get_db)):
    from app.models.domain import Organization

    rows = db.scalars(select(Organization).where(Organization.verification_status == "pending")).all()
    return [{"id": o.id, "name": o.name, "slug": o.slug, "owner_user_id": o.owner_user_id} for o in rows]


@router.post("/companies/{org_id}/verify", dependencies=[Depends(guard)])
def verify_company(org_id: int, db: Session = Depends(get_db)):
    from app.models.domain import Organization

    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Company not found")
    org.verification_status = "verified"
    org.verified = True
    log_audit(db, action="verify_company", entity_type="organization", entity_id=str(org_id))
    db.commit()
    sync_company(db, org_id)  # V21.1 Phase 3
    return {"verified": True, "id": org_id}


@router.post("/companies/{org_id}/reject", dependencies=[Depends(guard)])
def reject_company(org_id: int, db: Session = Depends(get_db)):
    from app.models.domain import Organization

    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Company not found")
    org.verification_status = "rejected"
    org.verified = False
    log_audit(db, action="reject_company", entity_type="organization", entity_id=str(org_id))
    db.commit()
    sync_company(db, org_id)  # V21.1 Phase 3
    return {"rejected": True, "id": org_id}
