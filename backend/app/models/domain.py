"""Core SQLAlchemy models spanning V1 (Job) through V9 (AuditLog)."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # V24.1 — recruiter dashboard/job-management queries filter and
        # sort by owner_user_id + status constantly; see
        # migrations/v24_1_recruiter_workspace.sql.
        Index("ix_jobs_owner_status", "owner_user_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(220), index=True)
    organization: Mapped[str] = mapped_column(String(220), index=True)
    department: Mapped[str | None] = mapped_column(String(220), nullable=True)
    # V19.1 — Government Recruitment Core. `organization_id` optionally
    # links a Government-type Job to a structured Organization row (see
    # Organization below); left nullable and additive so every existing
    # Job (government, private, internship — all created before this
    # column existed) stays valid with organization_id=NULL and keeps
    # using the free-text `organization` string exactly as before.
    # `ad_number`/`answer_key_url` extend the existing V7 exam-lifecycle
    # fields (admit_card_url, result_url, ...) rather than replacing them.
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("government_organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ad_number: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    answer_key_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    job_type: Mapped[str] = mapped_column(String(40), index=True, default="Government")
    govt_level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    work_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    experience_required: Mapped[str | None] = mapped_column(String(120), nullable=True)
    stipend: Mapped[str | None] = mapped_column(String(220), nullable=True)
    duration: Mapped[str | None] = mapped_column(String(120), nullable=True)
    location: Mapped[str] = mapped_column(String(160), default="India")
    vacancies: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qualification: Mapped[str] = mapped_column(Text, default="See official notification")
    age_limit: Mapped[str | None] = mapped_column(String(220), nullable=True)
    age_relaxation: Mapped[str | None] = mapped_column(Text, nullable=True)
    application_fee: Mapped[str | None] = mapped_column(Text, nullable=True)
    salary: Mapped[str | None] = mapped_column(String(220), nullable=True)
    pay_level: Mapped[str | None] = mapped_column(String(120), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    exam_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # V7 — exam lifecycle updates. The same posting gets edited over time
    # (via PATCH /admin/jobs/{id}) as these become available; they aren't
    # supplied at initial ingestion.
    admit_card_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    admit_card_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    result_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    result_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    selection_process: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="See official notification")
    notification_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    official_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    apply_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(220), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(220), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="review", index=True)
    # V9 — set when a recruiter posts this job directly (as opposed to
    # government ingestion, admin manual entry, or a V3 partner
    # submission, all of which leave this NULL).
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # V18.2 — professional job creation wizard (recruiter ATS). All
    # optional/free-text so nothing that writes a Job without them
    # (government ingestion, admin manual entry) needs to change.
    responsibilities: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    skills: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated
    benefits: Mapped[str | None] = mapped_column(Text, nullable=True)
    screening_questions: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded list[str]
    cloned_from_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # V24.1 — Recruiter Workspace. Nullable/additive, set once by
    # app.api.admin.publish() the first time a job's `status` becomes
    # "published" (never touched again after that, even if the job is
    # later closed/reopened) so the recruiter workspace can show a real
    # "Published date" distinct from `created_at` (when the recruiter
    # first saved the listing) — see docs/V24_1_RECRUITER_WORKSPACE.md.
    # Every job published before this column existed keeps
    # published_at=NULL; the API treats that as "unknown", never as a
    # fabricated date.
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # V25.2 — platform job moderation. These annotate the EXISTING
    # review workflow (`status` in review/published/rejected, plus the
    # new terminal-but-reversible "suspended") rather than introducing
    # a second publication system: app.services.job_moderation is the
    # only writer, and app.api.admin's original publish/reject routes
    # now delegate to it so both entry points stay consistent.
    #
    # `moderation_reason` is a structured code from
    # app.services.job_moderation.MODERATION_REASONS and IS shown to
    # the owning recruiter. `moderation_note` is the admin's free-text
    # internal note and is NEVER returned on a recruiter- or
    # candidate-facing endpoint (spec section 9).
    # `pre_moderation_status` records what the job's status was before
    # a suspension so "restore" is an exact, reversible undo rather
    # than a guess at where the listing belonged.
    moderation_reason: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    moderation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    moderated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    pre_moderation_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GovernmentOrganization(Base):
    """V19.1 — Government Recruitment Core. A structured government
    body (ministry/department/board/commission/PSU/university) that
    issues recruitments.

    NOTE ON NAMING: there is already an unrelated `Organization` model
    (V18.1 Company Module, below) mapped to table `organizations`,
    used for private-sector recruiter companies (owner_user_id,
    verification_status, slug, ...). This is deliberately a distinct
    class and table (`government_organizations`) — it does not touch,
    extend, or share rows with that table. Additive either way:
    existing Government Jobs keep working via their free-text
    `organization` string (Job.organization) whether or not they're
    ever linked to a row here via Job.organization_id.
    """

    __tablename__ = "government_organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(220), index=True)
    short_name: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(220), nullable=True)
    ministry: Mapped[str | None] = mapped_column(String(220), nullable=True)
    # Central / State / PSU / University / Board / Commission —
    # see app.core.constants.GOVERNMENT_LEVELS. Plain VARCHAR, same
    # pattern as Job.govt_level, for the same reason (no migration to
    # add a new level later).
    govt_level: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    official_website: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    official_career_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    official_result_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    official_admit_card_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # active / inactive — see app.core.constants.ORGANIZATION_STATUSES.
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SourceRegistry(Base):
    """V19.1 — Government Recruitment Core. One row per ingestion
    source (distinct from IngestionRun, the V2 per-run log): a
    standing catalog entry every future adapter registers itself
    into, carrying its schedule/status and a rolling summary
    (last_run_at/last_success_at/error_count) of IngestionRun rows
    for that source_name. Purely additive bookkeeping — nothing in
    the existing V2 ingestion pipeline (app.ingestion.ingest) has to
    change or read this table for ingestion to keep working exactly
    as it does today.
    """

    __tablename__ = "source_registry"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_name: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    official_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # official_html / rss / xml / json_api / pdf_metadata / sitemap /
    # selenium / playwright — see app.core.constants.SOURCE_COLLECTOR_TYPES.
    collector_type: Mapped[str] = mapped_column(String(30), default="official_html")
    # Free text describing the run cadence (e.g. "daily", "hourly",
    # "manual") — intentionally not a cron column yet; V19.1 only
    # built the registry, not a scheduler for it. V19.2's
    # app.ingestion.scheduler interprets this string ("hourly" /
    # "daily" / "manual") against last_run_at to decide what's due.
    schedule: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # active / paused / disabled
    status: Mapped[str] = mapped_column(String(20), default="disabled", index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # --- V19.2 — Official Source Adapter Framework. All additive/nullable
    # with safe defaults so every existing V19.1 SourceRegistry row (and
    # every row created via the unchanged V19.1 POST /government/sources
    # payload, which doesn't set any of these) keeps working unchanged. ---

    # Free-text organization/govt_level/category so a ConfiguredSourceAdapter
    # (app.ingestion.adapters.configured) can build a JobRecord's
    # classification fields without a code change per organization.
    organization: Mapped[str | None] = mapped_column(String(220), nullable=True)
    govt_level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Collector-specific parameters as a JSON-encoded string (CSS
    # selectors for html_list, a JSON-path for json_api, an item xpath
    # for xml, etc.) — see app.ingestion.adapters.configured for the
    # shape expected per collector_type. Kept as TEXT (not a JSON
    # column type) so this migrates identically on SQLite and Postgres.
    config: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Scheduler — priority queue ordering (lower runs first) and the
    # in-process/future-distributed-worker lock fields.
    priority: Mapped[int] = mapped_column(Integer, default=100)

    # Health tracking (V19.2 SOURCE HEALTH requirement): latency of
    # the most recent run, a rolling success-rate percentage over
    # recent runs, and how many retry attempts the most recent run
    # needed before it succeeded or gave up.
    last_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    availability_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Circuit breaker state (V19.2 ERROR HANDLING requirement):
    # closed -> normal; open -> skipped by the scheduler until the
    # cool-down elapses; half_open -> next run is a trial run.
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    circuit_state: Mapped[str] = mapped_column(String(20), default="closed")
    circuit_opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IngestionRunLog(Base):
    """V19.2 — structured, per-event log lines attached to one
    IngestionRun. IngestionRun itself (V2, unchanged) already stores a
    single rolled-up ``error_message``; this table is additive and
    exists purely so the admin "View logs" screen can show a
    timestamped sequence of what happened during a run (fetch started,
    N records discovered, retry attempt 2/3, circuit breaker opened,
    ...) instead of only the final outcome."""

    __tablename__ = "ingestion_run_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="CASCADE"), index=True)
    source_name: Mapped[str] = mapped_column(String(220), index=True)
    level: Mapped[str] = mapped_column(String(10), default="info")  # info / warning / error
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class IngestionDeadLetter(Base):
    """V19.2 — Dead Letter Queue abstraction. A record-level failure
    (a JobRecord that passed fetch() but failed to normalize/save,
    e.g. a data-shape problem specific to one posting rather than the
    whole source being down) lands here instead of silently vanishing,
    so an operator can inspect and, if fixable, resubmit it by hand.
    Adapter-level failures (the whole fetch() call raising) are still
    captured on IngestionRun.error_message as before — this table is
    for the narrower, per-record case."""

    __tablename__ = "ingestion_dead_letters"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_name: Mapped[str] = mapped_column(String(220), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id", ondelete="SET NULL"), nullable=True)
    payload: Mapped[str] = mapped_column(Text)  # JSON-encoded raw record
    error: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    full_name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(30), default="candidate")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    recruiter_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # V17.1 Auth Core — nullable so existing rows (created before these
    # columns existed) remain valid as-is. `phone` backs the duplicate
    # phone validation required at registration; the company_* fields
    # are populated for recruiter registrations only.
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True, index=True)
    company_name: Mapped[str | None] = mapped_column(String(220), nullable=True)
    company_website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # V17.2 — account lockout. Nullable/zero-defaulted so existing rows
    # are valid as-is. Permanent lock deliberately reuses the existing
    # `active` flag (see app/core/account_lockout.py's module docstring
    # for why) rather than adding a redundant lock_reason column.
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    last_failed_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Number of times this account has been temporarily locked, ever.
    # Not reset by unlock — used to escalate lock duration for repeat
    # offenders (see account_lockout.lock_duration_minutes).
    lock_count: Mapped[int] = mapped_column(Integer, default=0)

    # V17.3 — administrative suspension, distinct from the V17.2 lockout
    # mechanism above (which is *security*-driven: failed-login-triggered,
    # self-clearing after `locked_until` passes) and from a permanent
    # deactivation (`active=False` with no suspension fields set). A
    # suspension is an *administrative* hold with a recorded reason,
    # reversible via unsuspend. Like the V17.2 permanent lock, this
    # reuses `active=False` to actually block authentication (see
    # app/core/rbac.py's V17.3 section and SECURITY_ARCHITECTURE.md for
    # why reusing `active` — every auth code path already treats an
    # inactive user as fully unable to authenticate) — these two columns
    # exist only so "suspended" is distinguishable from "deactivated" in
    # the admin UI/audit trail, not to add a second auth gate.
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    suspension_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # V25.2 — Advanced Admin & Platform Governance. An explicit,
    # queryable PLATFORM account lifecycle state (ACTIVE | SUSPENDED |
    # DEACTIVATED) for the admin user-management screens, which
    # previously had to infer "is this account suspended or merely
    # deactivated?" from the combination of `active` + `suspended_at`.
    #
    # This does NOT become a second authentication gate: `active` is
    # still the one flag every auth code path checks (see
    # app.core.security.current_user), and app.core.platform_lifecycle
    # keeps the two in lockstep on every transition. The column exists
    # so the lifecycle is explicit in queries, filters and audit
    # records rather than reconstructed, and so DEACTIVATED (an
    # administrative end-state) is distinguishable from SUSPENDED (a
    # reversible hold) without guessing.
    #
    # Deliberately distinct from `OrganizationMember.status`: this is
    # the user's standing on the PLATFORM; that is their standing
    # inside one organization. Neither implies the other.
    account_status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)


class EmailVerification(Base):
    __tablename__ = "email_verifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    purpose: Mapped[str] = mapped_column(String(30), default="verify_email")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # V17.2 — wrong-code guesses against this row. A code is invalidated
    # (treated as consumed) once this reaches settings.otp_max_attempts,
    # independent of the per-IP verify-email rate limit, which an
    # attacker distributing guesses across IPs wouldn't trip.
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class UserSession(Base):
    """V17.1 — one row per logged-in device/browser.

    A session is the parent of a refresh-token rotation chain (see
    ``RefreshToken.session_id``). Revoking a session revokes every
    refresh token that belongs to it, which is what "logout this
    device" / "logout all sessions" actually do.
    """
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(String(120), index=True)
    device_label: Mapped[str | None] = mapped_column(String(220), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    remember_me: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RefreshToken(Base):
    """V17.1 — hashed (never plaintext) refresh tokens, rotated on use.

    ``token_hash`` is sha256 of the token actually handed to the
    client; only the hash is ever stored, matching how EmailVerification
    already treats OTP codes. ``replaced_by_id`` links a used token to
    the token that replaced it, so a stolen/replayed refresh token can
    be detected (reuse of an already-rotated token revokes the whole
    session) without needing a separate detection table.
    """
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("user_sessions.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    replaced_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PasswordHistory(Base):
    """V17.1 — previous password hashes, so reset/change can reject
    immediate reuse of a recent password. Never used for anything but
    that comparison; rows older than the configured history limit are
    pruned when a new one is written."""
    __tablename__ = "password_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)



class RecruitmentUpdate(Base):
    """Lifecycle event attached to a government recruitment/admission."""
    __tablename__ = "recruitment_updates"
    __table_args__ = (
        UniqueConstraint("job_id", "update_type", "source_url", name="uq_recruitment_update_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    update_type: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(300))
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    official: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default="published", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    highest_qualification: Mapped[str | None] = mapped_column(String(220), nullable=True)
    graduation_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skills: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_roles: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_locations: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    # V5 — reservation category, entered voluntarily by the candidate to get
    # an *indicative* age-relaxation estimate. Always a self-reported,
    # optional field the candidate controls, same as every other profile
    # attribute here — never inferred or required.
    reservation_category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_pwd: Mapped[bool] = mapped_column(Boolean, default=False)
    # V24.2 — Candidate Discovery. Opt-in only, default False (privacy-
    # preserving default per spec section 17): when True, this
    # candidate is discoverable by any approved recruiter via
    # GET /recruiter/candidates, independent of whether they've applied
    # to that recruiter's jobs. False (the default, and every existing
    # row's value after this migration) means the candidate is visible
    # to recruiters only through the existing, narrower channel that
    # already existed before V24.2 — having applied to one of that
    # recruiter's jobs (Applicant). This is a new *visibility* switch
    # only; it does not change who can apply to jobs or anything else
    # about the candidate experience.
    candidate_searchable: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class SavedJob(Base):
    __tablename__ = "saved_jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_saved_user_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Application(Base):
    """V7 Application OS — private, candidate-owned application
    tracker. Deliberately distinct from ``Applicant`` (the
    recruiter-visible pipeline row created by
    ``POST /jobs/{job_id}/apply`` — see that endpoint's own docstring
    in app/api/platform.py): this table is never visible to anyone but
    its owner, and covers *any* role a candidate is pursuing, on or off
    CareerOS.

    V22.1 (Application Tracking Infrastructure) extends this in place
    with the fuller production schema — richer fields, a canonical
    10-state status vocabulary, and an immutable
    ``ApplicationStatusHistory`` — rather than introducing a second
    application table. See ``app/applications/`` and
    ``docs/V22_1_APPLICATION_TRACKING.md``.

    Field-naming note: ``role`` (V7) and ``job_title`` (V22.1) hold the
    same value — kept in sync by ``app.applications.service`` on every
    write. ``role`` could not be dropped or renamed outright:
    ``app.recommendations.candidate_features`` already reads it
    directly (``applied_company_role_pairs``) and multiple other
    modules across the codebase select it. ``job_title`` is the
    canonical name going forward (matches this version's spec); new
    code should prefer it. Likewise ``applied_on`` (V7, a bare date) is
    what the spec calls ``applied_at`` — no second column was added for
    the same fact; the API layer exposes it as ``applied_at`` in
    responses (see app/api/applications.py) while the DB/ORM column
    keeps its original name for backward compatibility. ``deadline``
    (V22.1, the application's own deadline) is distinct from
    ``next_deadline`` (V7, the next upcoming *action* — an interview,
    a follow-up — which may be a completely different date).
    """

    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_user_status", "user_id", "status"),
        Index("ix_applications_user_created_at", "user_id", "created_at"),
        Index("ix_applications_user_deadline", "user_id", "deadline"),
        Index("ix_applications_user_applied_on", "user_id", "applied_on"),
        # V23.4 — supports app.communication.reminders' global deadline
        # scan (spec section 27: "avoid scanning every application" —
        # this keeps that scan an index lookup on non-null deadlines
        # rather than a full table scan across every user).
        Index("ix_applications_deadline_not_null", "deadline"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    company: Mapped[str] = mapped_column(String(220))
    role: Mapped[str] = mapped_column(String(220))
    job_title: Mapped[str | None] = mapped_column(String(220), nullable=True)
    job_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source: Mapped[str | None] = mapped_column(String(60), nullable=True)
    salary: Mapped[str | None] = mapped_column(String(220), nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    recruiter_name: Mapped[str | None] = mapped_column(String(220), nullable=True)
    recruiter_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="SAVED", index=True)
    applied_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApplicationStatusHistory(Base):
    """V22.1 — one immutable row per status change on an Application,
    so the full journey (SAVED -> ... -> ACCEPTED/REJECTED/WITHDRAWN)
    can always be reconstructed. Never updated or deleted by the
    service layer once written (cascade-deleted only if the parent
    Application itself is deleted). ``metadata_json`` is small,
    optional, structured context (e.g. ``{"note": "recruiter called"}``)
    — never a substitute for ``Application.notes``."""

    __tablename__ = "application_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    old_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    new_status: Mapped[str] = mapped_column(String(50))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApplicationNote(Base):
    """V22.3 — a private, free-text note a candidate keeps against one
    of their own applications (recruiter conversation, interview prep,
    salary discussion, company research, ...). Never visible to anyone
    but the owning candidate — ownership is always checked through the
    parent Application (see app.applications.notes)."""

    __tablename__ = "application_notes"
    __table_args__ = (Index("ix_application_notes_application_id_created_at", "application_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApplicationInterview(Base):
    """V22.3 — an application-specific interview round. ``result``
    starts at SCHEDULED and is updated by the candidate as the round
    resolves (COMPLETED/PASSED/FAILED/CANCELLED/RESCHEDULED); this is
    informational only and is never used to drive Application.status
    automatically — the candidate still updates the application's own
    status explicitly via app.applications.service."""

    __tablename__ = "application_interviews"
    __table_args__ = (
        Index("ix_application_interviews_application_id_scheduled_at", "application_id", "scheduled_at"),
        # V23.4 — supports app.communication.reminders' global upcoming-
        # interview scan (spec section 27).
        Index("ix_application_interviews_result_scheduled_at", "result", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    interview_type: Mapped[str] = mapped_column(String(30))
    round_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interviewer_name: Mapped[str | None] = mapped_column(String(220), nullable=True)
    interviewer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meeting_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    location: Mapped[str | None] = mapped_column(String(220), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(String(20), default="SCHEDULED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApplicationTask(Base):
    """V22.3 — an application-specific follow-up/task ("Send recruiter
    follow-up", "Prepare for technical interview", ...). Deliberately
    scoped to one application (unlike a general to-do list) so it
    surfaces right alongside the rest of that application's workspace
    and its own timeline."""

    __tablename__ = "application_tasks"
    __table_args__ = (
        Index("ix_application_tasks_application_id_due_at", "application_id", "due_at"),
        # V23.4 — supports app.communication.reminders' global task-due
        # scan (spec section 27).
        Index("ix_application_tasks_completed_due_at", "completed", "due_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApplicationDocument(Base):
    """V22.3 — metadata for a file attached to an application (resume,
    cover letter, offer letter, ...). The raw bytes live on disk under
    a private, non-web-served directory named only by ``stored_filename``
    (a server-generated UUID — never derived from the user-supplied
    ``original_filename``, which is display-only and never used to
    build a filesystem path — see app.applications.documents and
    app/core/uploads.py). List/detail responses only ever expose this
    metadata row, never the storage path itself."""

    __tablename__ = "application_documents"
    __table_args__ = (Index("ix_application_documents_application_id_uploaded_at", "application_id", "uploaded_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(30))
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True)
    file_size: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ApplicationEvent(Base):
    """V22.3 — the unified application activity/timeline log. Only
    covers events NOT already reconstructable from
    ``ApplicationStatusHistory`` (status changes are read from there
    directly, never duplicated here — see app.applications.timeline):
    notes, interviews, tasks, and document uploads each write one row
    here when created (and, for tasks/interviews, on a couple of
    specific follow-up transitions), giving every application a single
    chronological activity feed."""

    __tablename__ = "application_events"
    __table_args__ = (Index("ix_application_events_application_id_occurred_at", "application_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class RecruiterAIInsight(Base):
    """V24.4 — cache of one generated recruiter-analytics AI output
    (pipeline summary / candidate comparison / job insights), same
    content-hash design as ``ApplicationAIInsight`` (V22.4) —
    ``context_key`` hashes exactly the deterministic facts that went
    into the prompt, so a pipeline move, new application, or job edit
    naturally produces a different key and this cache can never serve
    stale intelligence; there is no separate invalidation step to
    forget (see app.recruiter_analytics.cache).

    Generalized over ``scope_type``/``scope_id`` rather than a single
    foreign key, since the three V24.4 AI features are scoped
    differently: ``scope_type="pipeline"`` keys on the recruiter's own
    user id (a cross-job summary), ``scope_type="job"`` and
    ``scope_type="comparison"`` key on a job id (job-insights and
    candidate-comparison are both job-specific). Authorization is
    still enforced the normal way at the API layer before this cache
    is ever touched (``_owned_job_or_404``/``require_recruiter``) —
    this table has no ownership column of its own because a cache hit
    is only ever looked up after that check already passed for this
    request's own recruiter, and ``scope_id`` for a job is validated
    against that job's own recruiter every time, same as any other
    job-scoped read. Stores only the generated output, never the
    prompt — same privacy posture as ApplicationAIInsight.

    V25.3 reuses this same table, unmodified, for its own three AI
    insight features rather than creating a second cache
    (``app.intelligence.ai``): ``scope_type="career_intelligence"``
    keys on the candidate's own user id, ``scope_type="org_intelligence"``
    keys on the organization id (authorized by V25.1 membership before
    lookup, same pattern as the job-scoped case above), and
    ``scope_type="market_intelligence"`` uses a fixed ``scope_id=0``
    since platform market activity has no owning entity to key on.
    ``scope_type`` is ``String(20)`` — kept short deliberately
    (``org_intelligence``, not the more obvious
    ``organization_intelligence``, which is 25 characters and would
    fail the column length on PostgreSQL) so a future caller does not
    silently repeat the mistake.
    """

    __tablename__ = "recruiter_ai_insights"
    __table_args__ = (
        UniqueConstraint("scope_type", "scope_id", "kind", "context_key", name="uq_recruiter_ai_insight"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(20), index=True)  # pipeline | job | comparison
    scope_id: Mapped[int] = mapped_column(index=True)  # recruiter user id (pipeline) or job id (job/comparison)
    kind: Mapped[str] = mapped_column(String(40), index=True)  # pipeline_summary | job_insights | candidate_comparison
    context_key: Mapped[str] = mapped_column(String(64), index=True)
    content_json: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ApplicationAIInsight(Base):
    """V22.4 — cache of one generated AI Application Intelligence
    output (narrative analysis / follow-up draft / interview prep) for
    one application, keyed by a content-hash ``context_key`` of exactly
    the inputs that would change the output — mirrors
    ``ResumeAISuggestion``'s cache design (app.resume_ai.cache), applied
    per-application instead of per-user (see
    app.applications.ai.cache). A status change, new interview, new/
    completed task, or changed deadline naturally produces a different
    context_key, so this cache can never silently serve stale
    intelligence — there is no separate invalidation step to forget.
    Stores only the generated *output* (as JSON text) — never the
    prompt sent to the model, matching AI_RESUME_PRIVACY.md's
    "don't persist raw prompts containing personal data unnecessarily",
    and observability.py already logs only token/cost/latency
    metadata, never prompt/response text."""

    __tablename__ = "application_ai_insights"
    __table_args__ = (UniqueConstraint("application_id", "kind", "context_key", name="uq_application_ai_insight"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)  # narrative / follow_up / interview_prep
    context_key: Mapped[str] = mapped_column(String(64), index=True)
    content_json: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Organization(Base):
    """V18.1 — extended into the ATS "Company" profile a recruiter
    manages (logo/banner/description/etc.) on top of the bare
    name+website+verified row this table already had since V1. Note
    that ``jobs.organization`` remains a free-text string column (used
    by government ingestion, search, etc. — untouched here); a Company
    profile is an optional, richer record a recruiter can attach their
    own postings to via ``owner_user_id``, not a foreign key those
    other subsystems are required to point at.
    """

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(220), unique=True)
    website: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)

    slug: Mapped[str | None] = mapped_column(String(220), unique=True, nullable=True, index=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    logo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    banner_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    company_size: Mapped[str | None] = mapped_column(String(40), nullable=True)
    founded_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location: Mapped[str | None] = mapped_column(String(220), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    twitter_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    facebook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    instagram_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Richer than the pre-existing `verified` bool (kept for backward
    # compatibility and updated alongside this) — distinguishes "never
    # submitted", "awaiting review" and "rejected", not just yes/no.
    verification_status: Mapped[str] = mapped_column(String(20), default="unverified", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # V25.1 — Multi-Tenant Architecture. Nullable/additive so every
    # `organizations` row created before this migration (V1 through
    # V24) stays valid as-is. `created_by` is deliberately distinct
    # from the pre-existing `owner_user_id`: it's a historical record
    # of who created the row and is never used for authorization —
    # ownership for access-control purposes is decided by the
    # `OrganizationMember` row with role=OWNER (see that class's
    # docstring), matching spec section 4's requirement that ownership
    # be represented through the membership system, not this column.
    # `is_active` is the soft-deletion flag for spec section 2 —
    # deactivating an organization must never cascade-delete unrelated
    # candidate accounts, so this is a flag, not a DELETE.
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # V25.2 — platform-level organization lifecycle (ACTIVE |
    # SUSPENDED | DEACTIVATED), set only by a platform administrator.
    # `is_active` (V25.1) remains the flag every existing membership/
    # tenancy check already reads, and is kept in lockstep with this
    # column by app.core.platform_lifecycle — so no V25.1 code
    # path has to learn about `status` for suspension to take effect.
    # Suspension NEVER deletes organization data (spec section 7): it
    # is a reversible state change plus a recorded reason.
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    suspension_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class OrganizationMember(Base):
    """V25.1 — Multi-Tenant Architecture & Organization Management.

    The formal membership/RBAC record for the `Organization` table
    above (which already existed as of V18.1 as a recruiter's
    "Company" profile). This is a NEW table, additive alongside the
    pre-existing `CompanyTeamMember` (V18.4) rather than a replacement
    of it — rewriting/removing that table would break every existing
    V18.4-V24 code path that reads it directly (app.api.company's
    roster endpoints). Instead:

    - `app.core.team_access.team_owner_ids` (the single chokepoint
      every recruiter-facing job/candidate/analytics/AI query already
      filters through) now prefers this table when an organization has
      been backfilled/created here, falling back to the legacy
      `CompanyTeamMember`-only resolution otherwise — see that
      function's docstring for exactly how.
    - `app.api.company`'s existing owner-only "instant add" team
      endpoints (`POST/DELETE /recruiter/company/team/...`) keep
      working completely unchanged, and now also mirror each write
      into this table (see `app.core.organizations.sync_legacy_membership`)
      so the two stay consistent going forward without a recruiter
      having to redo anything through the new API.
    - `scripts/migrate_v25_1_backfill_organizations.py` is a one-time,
      idempotent backfill that creates the matching OrganizationMember
      row for every pre-existing `Organization.owner_user_id` (as
      OWNER/ACTIVE) and `CompanyTeamMember` row (as RECRUITER/ACTIVE),
      so no existing recruiter or team loses access when this ships.

    One row per (organization_id, user_id) EVER — re-inviting someone
    who was REMOVED updates their existing row's status rather than
    inserting a second one. This is what the plain UniqueConstraint
    below uses to satisfy "no duplicate active membership" (spec
    section 3) portably across SQLite (tests/dev) and PostgreSQL
    (prod), instead of a partial/filtered unique index whose syntax
    differs between the two.
    """

    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member_org_user"),
        Index("ix_org_members_org_status", "organization_id", "status"),
        Index("ix_org_members_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # OWNER | ADMIN | RECRUITER today; a plain string column (no DB
    # enum), matching this codebase's existing convention for
    # extensible role values (see app.core.rbac's V17.3 notes on
    # User.role) so a future role doesn't need a migration.
    role: Mapped[str] = mapped_column(String(20), default="RECRUITER", index=True)
    # PENDING | ACTIVE | SUSPENDED | REMOVED.
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    invited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OrganizationInvitation(Base):
    """V25.1 — a pending invitation for someone to join an
    Organization, resolved to an ``OrganizationMember`` row only on
    explicit acceptance (spec section 16: matching email is never
    sufficient by itself).

    ``token_hash`` stores a SHA-256 hash of the actual invitation
    token, never the token itself — the same "never store the secret
    itself" pattern as ``User.password_hash`` — so a database
    compromise alone can't be used to accept invitations. The raw
    token exists only in the acceptance URL emailed to the invitee and
    is never logged (see app.api.organizations)."""

    __tablename__ = "organization_invitations"
    __table_args__ = (
        Index("ix_org_invitations_org_email", "organization_id", "email"),
        Index("ix_org_invitations_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(20), default="RECRUITER")
    invited_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # PENDING | ACCEPTED | REVOKED | EXPIRED
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class CompanyBranch(Base):
    """V18.1 — a company's office locations, shown on its profile."""

    __tablename__ = "company_branches"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    branch_name: Mapped[str] = mapped_column(String(220))
    location: Mapped[str | None] = mapped_column(String(220), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_headquarters: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CompanyTeamMember(Base):
    """V18.4 — Team management: which users can act as recruiters on
    behalf of a company profile, and with what role. Deliberately a
    separate table from `Organization.owner_user_id` rather than
    replacing it: the owner row is still authoritative (and always has
    a corresponding role="owner" member here, created alongside the
    company itself — see app.api.company.upsert_my_company), while
    this table lets the owner additionally list other *existing*
    recruiter accounts as team members. Adding someone here does not
    create an account or change `User.role` — deliberately reuses
    existing recruiter accounts/auth rather than touching
    registration, so this stays additive to Authentication, not a
    change to it. As of V18.6, this table also drives shared job
    access — see `app.core.team_access.team_owner_ids`, used by
    `app.api.recruiter` so any teammate can manage any other
    teammate's jobs/applicants/interviews/offers, not just the roster
    display. Company profile settings and email templates remain
    owner-only.
    """

    __tablename__ = "company_team_members"
    __table_args__ = (UniqueConstraint("company_id", "user_id", name="uq_team_company_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")  # owner | member
    added_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EmailTemplate(Base):
    """V18.5 — a recruiter's editable copy of one of the five ATS email
    templates (application received / interview invitation / interview
    reminder / offer / rejection) for their company. Storage + rendering
    only, matching V18 scope: this does not send anything and does not
    touch app.api.recruiter's notification/email code paths. Rows are
    created lazily from EMAIL_TEMPLATE_DEFAULTS the first time a
    recruiter fetches or edits a given type — see
    app.api.email_templates._get_or_seed — so a company that has never
    opened the editor still round-trips through EMAIL_TEMPLATE_DEFAULTS
    rather than having empty rows.
    """

    __tablename__ = "email_templates"
    __table_args__ = (UniqueConstraint("company_id", "template_type", name="uq_email_template_company_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    template_type: Mapped[str] = mapped_column(String(40), index=True)
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    alert_type: Mapped[str] = mapped_column(String(50))
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # V7 — when the saved-search matcher last scanned for jobs published
    # after this point, so each new match is notified exactly once.
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Notification(Base):
    """V7 — in-app notifications for deadline/admit-card/result
    milestones. Deliberately in-app only (no email/SMS sending): this
    project has no verified outbound mail/SMS provider configured, and
    a fake "we texted you" that doesn't actually send anything would be
    worse than an honest in-app inbox. See services/notifications.py
    for the scan that creates these and the note on adding a real
    delivery channel later.

    V23.1 — extended (additive columns only, via a new migration —
    see v23_1_notification_infrastructure.sql) into a general-purpose
    notification record for the new event-driven system in
    app.notifications.*, alongside the V7/V19.4 job-alert usage above,
    which is unchanged and keeps working exactly as before (every new
    column below is nullable or has a safe default, so no existing row
    or code path needs to change). ``notification_type`` (V7) is kept
    as the specific type string (e.g. "deadline", "application_status_
    changed"); ``category`` (V23.1) is the broader grouping spec'd for
    the notification center/preferences UI. ``dedupe_key`` is how
    app.notifications.service enforces the "one notification per real
    event, even under retries" requirement — see that module."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True)
    notification_type: Mapped[str] = mapped_column(String(30), index=True)  # deadline / admit_card / result / application_status_changed / ...
    title: Mapped[str] = mapped_column(String(220))
    message: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # V19.4 — Notification Center gains an Archive tab alongside
    # Unread/Read. Nullable-safe default (False) so every pre-existing
    # row keeps behaving as "not archived" with no backfill needed.
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # V23.1 — see the class docstring above for the V7/V19.4 vs V23.1
    # column split. All nullable or safely defaulted; no backfill needed.
    category: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)  # JOB/APPLICATION/INTERVIEW/DEADLINE/RECRUITER/AI/SYSTEM
    priority: Mapped[str] = mapped_column(String(10), default="NORMAL", index=True)  # LOW/NORMAL/HIGH/URGENT
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    action_url: Mapped[str | None] = mapped_column(String(300), nullable=True)  # always a validated internal path — see app.notifications.service._validate_action_url
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Idempotency key (e.g. "application_status_changed:<status_history_id>")
    # — see app.notifications.service.create_notification. NULL for every
    # pre-V23.1 notification (V7/V19.4 rows), which is fine: multiple NULLs
    # are always allowed under a SQL UNIQUE constraint, so old rows never
    # collide with each other or with new ones.
    dedupe_key: Mapped[str | None] = mapped_column(String(150), nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe_key"),)


class Partner(Base):
    """V3 — an employer or authorized job-aggregator allowed to submit
    private/internship/apprenticeship postings directly via API,
    instead of being scraped. Each partner gets its own hashed key so
    access can be revoked individually without affecting others."""

    __tablename__ = "partners"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(220), unique=True)
    contact_email: Mapped[str] = mapped_column(String(320))
    api_key_hash: Mapped[str] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    recruiter_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IngestionRun(Base):
    """V2 automated collection — one row per adapter run, so the admin
    UI/API can show what ran, when, and how many records it produced
    without having to parse logs."""

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_name: Mapped[str] = mapped_column(String(220), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    discovered: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Applicant(Base):
    """V9 — a candidate formally applying to a CareerOS-hosted job
    posting. Deliberately separate from `Application` (the candidate's
    personal, private tracker of roles they're pursuing anywhere,
    which may include private notes never meant for an employer): this
    table is the other side of that boundary — only created when a
    candidate chooses to apply through the platform, and only its
    resume snapshot/cover note/status are ever visible to the
    recruiter who owns the job."""

    __tablename__ = "applicants"
    __table_args__ = (UniqueConstraint("job_id", "user_id", name="uq_applicant_job_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    cover_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A copy of the resume text *as of the moment of applying* — later
    # edits to the candidate's stored Resume shouldn't retroactively
    # change what a recruiter already saw for this application.
    resume_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="submitted", index=True)
    # V18.2 — recruiter-facing Kanban pipeline stage. Deliberately a
    # separate column from `status`: `status` is the simpler
    # candidate-facing vocabulary other parts of the app (notifications,
    # candidate views) already read, and stays untouched here. This
    # holds the richer hiring-workflow stage set — see PIPELINE_STAGES
    # in app.core.constants (renamed to its current
    # new/reviewing/shortlisted/assessment/interview/offer/hired/
    # rejected/withdrawn vocabulary in V24.3; see that constant's
    # docstring for the V18.2 rename mapping) — shown on the recruiter
    # Kanban board and never used to overwrite `Application.status`,
    # the candidate-owned equivalent on a different table.
    pipeline_stage: Mapped[str | None] = mapped_column(String(30), default="new", index=True)
    # V16 — required by the recruiter API whenever status is set to
    # "rejected" (see app.api.recruiter.update_applicant_status). Never
    # shown to other candidates; visible to the candidate themselves so
    # rejection isn't a black box, and to the owning recruiter.
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # V24.3 — set once, the first time `pipeline_stage` becomes "hired"
    # (see app.recruiter_pipeline.service.change_stage). Never reset by
    # a later correction move away from "hired" — that keeps "this
    # candidate was hired on <date>" answerable even if the recruiter
    # later has to walk the stage back for a data-entry fix.
    hired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApplicantNote(Base):
    """V16 — private, timestamped recruiter notes on an applicant.
    Never visible to the candidate or to other recruiters — only the
    owning recruiter/admin (enforced the same way applicant access
    already is, via the underlying job's owner_user_id)."""

    __tablename__ = "applicant_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("applicants.id", ondelete="CASCADE"), index=True)
    author_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Interview(Base):
    """V16 — one scheduled interview round for an applicant. An
    applicant can have several (phone screen, technical, final), so
    this is its own table rather than fields bolted onto Applicant."""

    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("applicants.id", ondelete="CASCADE"), index=True)
    round_name: Mapped[str] = mapped_column(String(120), default="Interview")
    mode: Mapped[str] = mapped_column(String(20), default="video")  # video | phone | onsite
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    location_or_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)  # scheduled | completed | cancelled | rescheduled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RecruiterPipelineHistory(Base):
    """V24.3 — one immutable row per recruiter-side hiring-stage change
    on an `Applicant`. Deliberately separate from
    `ApplicationStatusHistory` (which tracks the *candidate*-owned
    `Application.status` — a completely different table, see that
    class's docstring and docs/V24_3_CANDIDATE_PIPELINE.md, "Status
    separation"): this table is recruiter/company-side data about the
    `Applicant.pipeline_stage` column, and is never read by any
    candidate-facing endpoint. Never updated or deleted by the service
    layer once written (cascade-deleted only if the parent Applicant
    itself is deleted)."""

    __tablename__ = "recruiter_pipeline_history"
    __table_args__ = (
        Index("ix_recruiter_pipeline_history_applicant_id_changed_at", "applicant_id", "changed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("applicants.id", ondelete="CASCADE"), index=True)
    old_stage: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_stage: Mapped[str] = mapped_column(String(30), index=True)
    changed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    # "reactivation" | "forward" | "backward" | "terminal" | "initial" —
    # see app.recruiter_pipeline.service._direction. Purely descriptive
    # (never used for authorization); makes conversion/"skipped a
    # stage" reporting possible without re-deriving it from
    # PIPELINE_FORWARD_STAGES on every read.
    direction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class OfferLetter(Base):
    """V16 — an offer extended to an applicant. ``letter_text`` is
    generated deterministically from the structured fields on this row
    (see app.services.offer_letters) — never AI-generated, since a
    wrong salary/date in a real offer letter is a serious problem, the
    same reasoning V8 already applies to exam-prep content."""

    __tablename__ = "offer_letters"

    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("applicants.id", ondelete="CASCADE"), index=True, unique=True)
    position_title: Mapped[str] = mapped_column(String(220))
    salary: Mapped[str | None] = mapped_column(String(120), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    letter_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)  # draft | sent | accepted | declined | withdrawn
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Resume(Base):
    """V8 — one stored resume per candidate. Uploading a new file
    replaces the previous extracted text/skills rather than keeping a
    history; this is a working document for matching, not an archive."""

    __tablename__ = "resumes"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(320))
    extracted_text: Mapped[str] = mapped_column(Text)
    skills_detected: Mapped[str | None] = mapped_column(Text, nullable=True)
    # V20.2 — AI Resume Intelligence. Nullable/additive: only the raw
    # file bytes (in memory during the POST /resume request, never
    # persisted) can answer "does this layout use tables/columns", so
    # it's captured once at upload time or not at all — NULL for every
    # resume uploaded before this column existed, or if detection
    # wasn't possible for the format (see app.resume_ai.extraction.
    # detect_tables_or_columns). Read by app.resume_ai.ats_analysis;
    # does not change this table's existing meaning or any other column.
    has_tables_or_columns: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExamPrepResource(Base):
    """V8 — admin-curated exam-prep links (syllabus, previous-year
    papers, mock tests, cutoffs). Deliberately curated rather than
    generated: fabricating syllabus/paper content for a real
    high-stakes government exam risks being confidently wrong in a way
    that could hurt a candidate's preparation, so this project only
    ever links to admin-verified sources."""

    __tablename__ = "exam_prep_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True)
    organization: Mapped[str] = mapped_column(String(220), index=True)
    exam_name: Mapped[str] = mapped_column(String(220))
    resource_type: Mapped[str] = mapped_column(String(30))  # syllabus / previous_papers / mock_test / cutoff / study_material
    title: Mapped[str] = mapped_column(String(220))
    url: Mapped[str] = mapped_column(String(1000))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # V16 — who/what performed the action, and which request it happened
    # in. Added nullable so old rows (written before this migration)
    # stay valid; new rows are always populated by app.core.audit.log_audit.
    # actor_type is one of "user" (a logged-in User, id in actor_id) or
    # "admin_key" (the shared X-Admin-Key bootstrap credential, which has
    # no user row of its own).
    actor_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    actor_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RolePermissionOverride(Base):
    """V17.3 — a runtime grant/revoke of one permission for one role,
    layered on top of the static defaults in app.core.rbac's
    DOT_ROLE_PERMISSIONS. This is what makes permissions genuinely
    "configurable" (an admin action, via POST /admin/rbac/roles/{role}/grant
    or /revoke) rather than requiring a code change + deploy for every
    adjustment. See app.core.rbac.effective_permissions_for_role for how
    this is merged with the static catalog: `granted=True` adds a
    permission the role doesn't have by default; `granted=False`
    removes one it does.
    """
    __tablename__ = "role_permission_overrides"
    __table_args__ = (UniqueConstraint("role", "permission", name="uq_role_permission"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(30), index=True)
    permission: Mapped[str] = mapped_column(String(80), index=True)
    granted: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# V19.4 — Government Automation & Notification Engine.
#
# Layered on top of the existing V7 Notification/Alert tables (above)
# rather than replacing them: `Notification` is still the one row that
# means "this user has an in-app notification", `scan_and_notify` still
# runs unmodified on its own schedule. What's new here is everything
# upstream of that — who to notify and why (Subscription), what to say
# (NotificationTemplate), whether it also went out by email
# (NotificationDeliveryLog), how a user wants to be reached
# (UserNotificationPreference), and scheduled nudges tied to a specific
# date rather than a lifecycle event (ReminderRule). See
# app/services/notification_channels.py, notification_templates.py,
# automation.py and reminder_engine.py for the logic that reads/writes
# these tables.
# ---------------------------------------------------------------------------


class Subscription(Base):
    """A standing "notify me about X" registration. `subscription_type`
    is one of the categories in the V19.4 spec (recruitment /
    organization / exam / category / qualification / state / central /
    psu / bank / railway / police / teaching / medical / engineering /
    defence). For the single-recruitment case, `job_id` identifies it
    directly; every other type is matched against the relevant Job
    column (organization/category/qualification/location) via `value`
    — see app.services.automation._matches_subscription. Deliberately
    free-text `value` rather than a foreign key into a controlled-
    vocabulary table: Job.organization/category/qualification are
    themselves free text (see Job's own docstring further up), so a
    subscription needs to match the same loosely-structured data the
    ingestion adapters actually produce."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "subscription_type", "value", "job_id", name="uq_subscription"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subscription_type: Mapped[str] = mapped_column(String(30), index=True)
    value: Mapped[str | None] = mapped_column(String(220), nullable=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserNotificationPreference(Base):
    """One row per user (created lazily on first read/write — see
    app.api.notification_engine.get_preferences). Every flag defaults
    to the always-on, instant-delivery behavior V7 already had, so a
    user who never visits the preferences page keeps getting notified
    exactly as before this version existed."""

    __tablename__ = "user_notification_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Comma-separated free-text lists (same pattern as Profile.skills
    # above) — empty/null means "no extra filter beyond subscriptions".
    category_preferences: Mapped[str | None] = mapped_column(Text, nullable=True)
    organization_preferences: Mapped[str | None] = mapped_column(Text, nullable=True)
    quiet_hours_start: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-23, local-naive hour
    quiet_hours_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # instant / daily_digest / weekly_summary
    digest_mode: Mapped[str] = mapped_column(String(20), default="instant")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # V23.1 — per-category in-app toggle for the new event-driven
    # notification system (app.notifications.*). Distinct from
    # category_preferences above (which is free-text government-job
    # subscription filtering, V19.4) — these are simple on/off switches
    # for the 7 categories in Notification.category. All default True,
    # preserving "notified exactly as before this column existed" for
    # every user who never visits the preferences page, same rationale
    # as every other flag on this model. Full per-channel (email, etc.)
    # preference handling is explicitly out of scope for V23.1 — see
    # docs/V23_1_NOTIFICATION_INFRASTRUCTURE.md.
    notify_job: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_application: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_interview: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_deadline: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_recruiter: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_ai: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_system: Mapped[bool] = mapped_column(Boolean, default=True)
    # V23.2 — per-category EMAIL toggle, distinct from the per-category
    # in-app toggle above. Gated behind `email_enabled` (the existing
    # V19.4 global switch) in app.email.preferences.should_send_email —
    # both must be true for a given category's email to go out. These
    # NEVER gate email verification / password reset / other security-
    # critical transactional email (see app.email.service.
    # send_transactional_email, which never checks preferences at all)
    # — spec: "must not be disabled through ordinary notification
    # preferences." All default True for the same "unchanged behavior
    # for anyone who's never visited the preferences page" reason as
    # every other flag on this model.
    email_job: Mapped[bool] = mapped_column(Boolean, default=True)
    email_application: Mapped[bool] = mapped_column(Boolean, default=True)
    email_interview: Mapped[bool] = mapped_column(Boolean, default=True)
    email_deadline: Mapped[bool] = mapped_column(Boolean, default=True)
    email_recruiter: Mapped[bool] = mapped_column(Boolean, default=True)
    email_ai: Mapped[bool] = mapped_column(Boolean, default=True)
    email_system: Mapped[bool] = mapped_column(Boolean, default=True)

    # V23.4 — Communication Center. `timezone` is an IANA name (e.g.
    # "Asia/Kolkata"); nullable-by-default-value rather than nullable
    # column so every existing row (created before this column
    # existed) reads as "UTC" — the documented default spec section 16
    # asks for ("If no timezone exists: use a clearly documented
    # default") — with no backfill migration required. Used only to
    # evaluate quiet_hours_start/quiet_hours_end (already existed —
    # V19.4 — but were never actually consulted before this version;
    # see app.communication.reminders) in the user's local time; every
    # timestamp stored anywhere in this codebase remains UTC (see
    # docs/V23_4_COMMUNICATION_CENTER.md "Timezone handling").
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    # Daily communication digest email — spec section 12/13: opt-IN
    # (default False), unlike every per-event email_* flag above
    # (which preserve pre-existing always-on behavior). A digest is a
    # brand-new kind of email nobody has ever received before this
    # version, so there is no "unchanged default" to preserve; the
    # safer default for a new bundled-content email is off until the
    # candidate explicitly asks for it.
    digest_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class SystemEmailTemplate(Base):
    """V23.2 — system-wide transactional/notification email templates
    (WELCOME_EMAIL, EMAIL_VERIFICATION, PASSWORD_RESET,
    APPLICATION_STATUS_CHANGED, INTERVIEW_SCHEDULED,
    SYSTEM_NOTIFICATION, ...). Named ``SystemEmailTemplate``/table
    ``system_email_templates`` specifically to avoid colliding with
    the pre-existing ``EmailTemplate``/``email_templates`` table
    (V18.5) — that one is a *recruiter's own, per-company* editable
    copy of ATS notification wording (application received/interview
    invitation/offer/rejection/reminder), a genuinely different concept
    from these system-wide, non-company-scoped templates. Both use the
    same simple ``{{variable}}`` placeholder syntax for consistency,
    but are deliberately two tables — collapsing them would conflate
    "a recruiter's company voice" with "CareerOS's own system emails."

    ``variables_json`` lists the variable names this template expects
    (used to validate a render call has everything it needs — see
    app.email.templates.render) — it is metadata about the template,
    never actual recipient data."""

    __tablename__ = "system_email_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_key: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    subject: Mapped[str] = mapped_column(String(300))
    html_body: Mapped[str] = mapped_column(Text)
    text_body: Mapped[str] = mapped_column(Text)
    variables_json: Mapped[str] = mapped_column(Text, default="[]")
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailMessage(Base):
    """V23.2 — one queued/sent/failed email. This is the durable
    record the retry system and admin overview both read; actual
    delivery attempts are logged one-per-row in
    ``EmailDeliveryAttempt`` below rather than only keeping a single
    "last error" (kept here too, denormalized, for a cheap list view).

    SECURITY: ``variables_json`` must never contain a secret (an OTP
    code, a reset token, a password). For security-critical
    transactional email, app.email.service.send_transactional_email
    renders the real secret in memory only and persists a redacted
    variables_json here (e.g. the user's name, not the code) — see
    that function's own docstring. Every other, non-secret-bearing
    template stores its real variables here for legitimate retry."""

    __tablename__ = "email_messages"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_email_messages_user_dedupe_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    template_key: Mapped[str] = mapped_column(String(50), index=True)
    recipient: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(300))
    variables_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailDeliveryAttempt(Base):
    """V23.2 — one row per actual send attempt against an
    ``EmailMessage``, independent of that row's own denormalized
    attempts/last_error summary — gives a full attempt-by-attempt
    audit trail (spec: "delivery status" / admin observability)."""

    __tablename__ = "email_delivery_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_message_id: Mapped[int] = mapped_column(ForeignKey("email_messages.id", ondelete="CASCADE"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))  # SENT / FAILED
    provider: Mapped[str] = mapped_column(String(20))  # console / smtp
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ReminderRule(Base):
    """A scheduled nudge tied to a specific date on a specific job
    (application deadline / exam date / result-expected / document
    verification / medical / joining), or a fully custom one-off. Auto-
    created by app.services.reminder_engine for every interested user
    at the offsets configured in their preferences (default: 3 and 1
    days before) whenever a Job gains a relevant date; a user can also
    create additional custom ones directly via the API."""

    __tablename__ = "reminder_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    reminder_type: Mapped[str] = mapped_column(String(30), index=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    offset_days: Mapped[int] = mapped_column(Integer, default=0)  # 0 for a custom exact-date reminder
    fire_date: Mapped[date] = mapped_column(Date, index=True)  # target_date - offset_days, precomputed for the scan
    auto_created: Mapped[bool] = mapped_column(Boolean, default=True)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NotificationReminder(Base):
    """V23.4 — Communication Center reminder engine's own durable
    delivery record. Deliberately a NEW table rather than reusing
    ``ReminderRule`` above: that table is V19.4's, purpose-built for
    one narrow case (a single date on a Government ``Job``/
    ``RecruitmentUpdate``, offset-based `fire_date`, fires through
    `app.services.reminder_engine` only) — see its own docstring. This
    version's reminders cover a structurally different set of sources
    (an ``ApplicationInterview``, an ``Application`` deadline, or an
    ``ApplicationTask`` due date) with a different identity shape
    (``source_type``/``source_id``/``reminder_type``/``scheduled_for``
    rather than a job_id + offset_days), and are fired through the
    V23.1/V23.2 notification/email systems via
    ``app.communication.reminders`` — see that module and
    docs/V23_4_COMMUNICATION_CENTER.md for why these two reminder
    systems live side by side rather than merging.

    IDEMPOTENCY (spec sections 6/15 — "a retry or worker restart must
    not produce duplicate reminders"): the UNIQUE constraint below on
    (source_type, source_id, reminder_type, scheduled_for) is the
    single source of truth a concurrent/retried worker cannot race
    past — a row is inserted with status=PENDING *before* any
    notification/email is created for it, and only ever updated
    (never re-inserted) afterward. See app.communication.reminders.
    """

    __tablename__ = "notification_reminders"
    __table_args__ = (
        UniqueConstraint(
            "source_type", "source_id", "reminder_type", "scheduled_for",
            name="uq_notification_reminders_identity",
        ),
        Index("ix_notification_reminders_user_status", "user_id", "status"),
        Index("ix_notification_reminders_scheduled_for", "scheduled_for"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # INTERVIEW / DEADLINE / TASK
    source_type: Mapped[str] = mapped_column(String(20), index=True)
    # the id of the ApplicationInterview / Application / ApplicationTask row
    source_id: Mapped[int] = mapped_column(Integer, index=True)
    # e.g. "24_HOURS_BEFORE", "1_HOUR_BEFORE", "7_DAYS_BEFORE",
    # "3_DAYS_BEFORE", "1_DAY_BEFORE", "DUE_TODAY", "OVERDUE"
    reminder_type: Mapped[str] = mapped_column(String(30), index=True)
    # the UTC instant this reminder logically fires at (see module
    # docstring / docs — computed once from the source's own date and
    # never recomputed, so it remains a stable identity component even
    # if the underlying interview/deadline is later edited: a changed
    # date is treated as a NEW reminder, not a mutation of this one)
    # NOTE: no `index=True` here — the explicit, named
    # `Index("ix_notification_reminders_scheduled_for", ...)` in
    # __table_args__ above already covers this column. Both existing
    # at once is what caused V23.5's confirmed startup bug (see
    # docs/V23_BUG_REPORT.md): SQLAlchemy's autogenerated column-level
    # index and the explicit one collided on the exact same name,
    # so `Base.metadata.create_all()` tried to `CREATE INDEX
    # ix_notification_reminders_scheduled_for` twice against the same
    # table and the second attempt crashed app startup on any fresh
    # database (SQLite: `index ... already exists`; the equivalent
    # Postgres migration was never affected, since
    # migrations/v23_4_communication_center.sql only ever declared it
    # once — this was purely a SQLAlchemy-metadata self-collision).
    scheduled_for: Mapped[datetime] = mapped_column(DateTime)

    # PENDING / DELAYED (quiet hours) / SENT / SKIPPED / FAILED
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    priority: Mapped[str] = mapped_column(String(10), default="NORMAL")

    notification_id: Mapped[int | None] = mapped_column(
        ForeignKey("notifications.id", ondelete="SET NULL"), nullable=True
    )
    email_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("email_messages.id", ondelete="SET NULL"), nullable=True
    )

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class NotificationTemplate(Base):
    """A reusable, admin-editable message template. `key` is the
    lookup used by app.services.automation (e.g. "admit_card_released"),
    `channel` is "in_app" or "email" — the same event has one template
    per channel since an email needs a subject and fuller phrasing
    where an in-app card doesn't. Body/subject may contain
    ``{placeholder}`` tokens resolved by
    app.services.notification_templates.render against the triggering
    Job/RecruitmentUpdate. Seeded with sensible defaults at import time
    (see notification_templates.DEFAULT_TEMPLATES) so the engine works
    out of the box even before an admin customizes anything."""

    __tablename__ = "notification_templates"
    __table_args__ = (UniqueConstraint("key", "channel", name="uq_notification_template"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)  # email only
    body: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class NotificationDeliveryLog(Base):
    """One row per (notification, channel) delivery attempt. The V7
    `Notification` row itself remains the source of truth for "does
    this user have an in-app notification"; this table exists purely
    to answer "did the email actually go out, and if not why" for the
    admin queue/retry/stats tooling, without overloading Notification
    with delivery bookkeeping it never needed for its original in-app-
    only scope."""

    __tablename__ = "notification_delivery_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int | None] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(20), index=True)  # in_app / email / push / sms / whatsapp
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending/sent/failed/skipped/not_implemented
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    # V25.5 — indexed: the new GET /admin/observability endpoint
    # (app.api.admin_observability) filters this table by a
    # created_at >= since window on every call; before this it was
    # the one unindexed column on an otherwise fully-indexed table.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AutomationCursor(Base):
    """A tiny per-trigger high-water mark ("last id already processed")
    so app.services.automation.run_automation_scan never re-notifies
    for the same Job/RecruitmentUpdate/AuditLog row twice. One row per
    trigger name, upserted after each scan — same idea as
    Alert.last_checked_at above, generalized to an id-based cursor
    (rather than a timestamp) so it isn't sensitive to two rows sharing
    a created_at value at a scan boundary."""

    __tablename__ = "automation_cursors"

    trigger: Mapped[str] = mapped_column(String(60), primary_key=True)
    last_id: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AutomationLog(Base):
    """One row per automation trigger run (recruitment_published,
    result_released, admit_card_released, deadline_changed,
    status_changed, subscription_match), for the admin "Automation
    Logs" view. Deliberately separate from AuditLog (V9) — AuditLog
    records *who* did *what* administrative action; this records what
    the *automation engine* itself did on its own schedule, which has
    a different shape (a trigger name + how many notifications it fanned out to)."""

    __tablename__ = "automation_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(60), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    notifications_created: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# V20.1 — AI Infrastructure & LLM Framework. Additive only: the provider
# abstraction, prompt registry, and conversation memory in app/ai/ are new
# consumers of these tables; nothing above this line changes. See
# AI_ARCHITECTURE.md.
# ---------------------------------------------------------------------------


class AIConversation(Base):
    """One AI conversation thread. ``session_key`` lets an anonymous or
    not-yet-authenticated caller (e.g. a pre-login chat widget) resume
    a thread without a user_id; ``user_id`` is set once a real user
    owns it. A future feature (Career Copilot, etc.) is expected to
    create one of these per chat session rather than inventing its own
    history table."""

    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    session_key: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Purpose tag (e.g. "resume_ai", "interview_ai") set by the calling
    # feature — this layer doesn't interpret it, only stores/filters by it.
    context_type: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AIMessage(Base):
    """One turn within an AIConversation. Token counts are the real
    provider-reported figures when available (assistant turns),
    otherwise a TokenCounter estimate (user turns, which providers
    never bill/report individually)."""

    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # system / user / assistant
    content: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class AIPromptTemplate(Base):
    """A versioned, admin-editable prompt template. ``key`` is the
    lookup used by app.ai.prompt_service.render(key, variables);
    multiple rows may share a key at different ``version`` numbers —
    only the highest-numbered ``active`` row for a key is used, so a
    bad edit can be deactivated without deleting history."""

    __tablename__ = "ai_prompt_templates"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_ai_prompt_template_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    template: Mapped[str] = mapped_column(Text)
    # JSON-encoded list of required variable names, validated by
    # prompt_service.render before substitution.
    variables: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AIUsageLog(Base):
    """One row per AI provider call (completion, embedding, or
    moderation), successful or not. This is the source of truth for
    the admin Usage/Observability panels — token counts, cost
    estimates, latency, and per-provider success rate are all derived
    by aggregating this table rather than kept as separately-updated
    running counters, so historical numbers stay accurate even if the
    process restarts (in-memory counters in app.ai.observability do
    not survive a restart; this table does)."""

    __tablename__ = "ai_usage_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    service: Mapped[str] = mapped_column(String(40), index=True)  # completion / embedding / moderation
    operation: Mapped[str | None] = mapped_column(String(60), nullable=True)  # calling feature/purpose label
    provider: Mapped[str] = mapped_column(String(30), index=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    used_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_estimate_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    success: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ---------------------------------------------------------------------------
# V20.2 — AI Resume Intelligence. Additive only, built on the V20.1 AI
# Gateway and the V8 Resume module (both unchanged above this line). See
# AI_RESUME_ARCHITECTURE.md. Only *derived, structured* results are stored
# here — never a raw LLM prompt/response — per AI_RESUME_PRIVACY.md.
# ---------------------------------------------------------------------------


class ResumeAnalysis(Base):
    """Latest deterministic analysis (normalized profile + every
    component score + ATS analysis) for a candidate's stored Resume.
    One row per user, replaced on recompute — same "working document,
    not an archive" posture as Resume itself. JSON columns hold
    structured, derived data only (scores, extracted section text
    already visible to the candidate in their own resume) — never a
    prompt or raw model response."""

    __tablename__ = "resume_analyses"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    profile_json: Mapped[str] = mapped_column(Text)
    scores_json: Mapped[str] = mapped_column(Text)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ResumeJobMatch(Base):
    """Cached explainable match result between one user's resume and
    one job — recomputing this is cheap (no LLM call, pure
    deterministic scoring; see app.resume_ai.job_match) but the cache
    still avoids redundant work on repeat views of the same
    resume/job pair within a session, and lets a recruiter's applicant
    view and a candidate's own job-match view share one row when
    they're looking at the same resume text and job."""

    __tablename__ = "resume_job_matches"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_resume_job_match"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    overall_score: Mapped[int] = mapped_column(Integer)
    skills_score: Mapped[int] = mapped_column(Integer)
    experience_score: Mapped[int] = mapped_column(Integer)
    education_score: Mapped[int] = mapped_column(Integer)
    keywords_score: Mapped[int] = mapped_column(Integer)
    result_json: Mapped[str] = mapped_column(Text)  # full JobMatchResult + SkillGapResult, serialized
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ResumeAISuggestion(Base):
    """Cache of one generative resume-AI output (bullet rewrite,
    summary, project suggestion, job-advice narration) keyed by a
    content hash of its inputs — see app.resume_ai.cache. Stores the
    generated *output* text only, never the prompt sent to the model,
    so this table never accumulates the raw personal-data prompts
    AI_RESUME_PRIVACY.md says to avoid persisting unnecessarily."""

    __tablename__ = "resume_ai_suggestions"
    __table_args__ = (UniqueConstraint("user_id", "kind", "context_key", name="uq_resume_ai_suggestion"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)  # bullet_improve / summary / project_improve / job_advice
    context_key: Mapped[str] = mapped_column(String(64), index=True)
    content: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ---------------------------------------------------------------------------
# V20.3 — AI Career Copilot. Additive only, built on the V20.1 AI Gateway
# (conversations/messages already exist there — AIConversation/AIMessage/
# AIPromptTemplate/AIUsageLog are reused as-is, not duplicated) and V20.2
# Resume Intelligence (both unchanged above this line). See
# CAREER_COPILOT_ARCHITECTURE.md. Only two new tables: career preferences
# the candidate sets explicitly, and action-plan items so completion status
# survives across requests — everything else the Copilot uses (context,
# recommendations, roadmap) is composed on demand from existing tables,
# not re-stored, per CAREER_CONTEXT_ENGINE.md's "don't duplicate" stance.
# ---------------------------------------------------------------------------


class CareerPreference(Base):
    """Candidate-defined career profile — distinct from `Profile` (V1,
    unchanged): `Profile` holds what the candidate *is* (location,
    qualification, skills); this holds what they *want* (target role,
    industry, work mode, target companies, salary expectation, learning
    goals). One row per user, all fields optional/self-reported —
    never inferred by the Copilot without the candidate stating them."""

    __tablename__ = "career_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    target_role: Mapped[str | None] = mapped_column(String(160), nullable=True)
    preferred_industry: Mapped[str | None] = mapped_column(String(160), nullable=True)
    preferred_location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    preferred_work_mode: Mapped[str | None] = mapped_column(String(30), nullable=True)  # remote / hybrid / onsite
    experience_level: Mapped[str | None] = mapped_column(String(40), nullable=True)  # entry / mid / senior / lead
    target_companies: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated
    salary_expectation: Mapped[str | None] = mapped_column(String(120), nullable=True)  # free text — never validated/verified
    preferred_skills: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated
    learning_goals: Mapped[str | None] = mapped_column(Text, nullable=True)
    career_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CareerActionItem(Base):
    """One task in the Copilot's generated action plan
    (Today/This Week/This Month/Next 3 Months — see
    app.career_copilot.action_plan). Persisted (rather than
    recomputed fresh every request) specifically so a candidate's
    "done"/"dismissed" mark on an item survives the next time the plan
    is regenerated — regeneration upserts by `dedupe_key`, a stable
    hash of (user, bucket, title, related_job_id), and never resets an
    existing item's status."""

    __tablename__ = "career_action_items"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_career_action_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(64), index=True)
    bucket: Mapped[str] = mapped_column(String(20))  # today / this_week / this_month / next_3_months
    title: Mapped[str] = mapped_column(String(300))
    reason: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10))  # high / medium / low
    source: Mapped[str] = mapped_column(String(30))  # deadline / skill_gap / application / career_goal / recommendation
    related_job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending / done / dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    regenerated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# V20.4 — AI Interview & Mock Interview System. Additive only, built on
# the V20.1 AI Gateway (app.ai.completion_service — never a provider
# directly), V20.2 Resume Intelligence (app.resume_ai — profile
# extraction, job-match, skill-gap, all reused not duplicated), and
# V20.3 Career Copilot (system_prompt.wrap_untrusted for prompt-
# injection defense; the Copilot itself is what explains a report, not
# a second engine — see app.interview_ai.copilot_bridge). See
# AI_INTERVIEW_ARCHITECTURE.md.
#
# Named `MockInterview*` (not `Interview*`) specifically to avoid any
# confusion with the pre-existing V16 `Interview` table above, which is
# a *recruiter-scheduled* real interview round for an ATS applicant —
# an entirely different concept this version does not touch.
#
# As with ResumeAISuggestion (V20.2), only *derived, structured*
# results are stored — an evaluation's scores/feedback text, never the
# raw prompt sent to the model — per AI_INTERVIEW_PRIVACY.md.
# ---------------------------------------------------------------------------


class MockInterviewSession(Base):
    """One configured mock interview, from setup through final report.
    `status` is only ever changed via app.interview_ai.state_machine's
    validated transition table (see STOP/DO-NOT-TOUCH note in that
    module) — never set directly by API code — so a session's status
    history is always a legal path through
    draft -> ready -> in_progress -> (paused <-> in_progress) -> completed/cancelled."""

    __tablename__ = "mock_interview_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Optional — a job-specific interview references a real, published
    # Job; every other mode leaves this NULL and free-text target_role
    # instead (never a fabricated job).
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    interview_type: Mapped[str] = mapped_column(String(30), index=True)
    # technical / hr / behavioral / resume_based / job_specific / coding
    # / data_science / system_design / mixed / custom
    target_role: Mapped[str | None] = mapped_column(String(160), nullable=True)
    experience_level: Mapped[str | None] = mapped_column(String(40), nullable=True)  # entry / mid / senior / lead
    difficulty: Mapped[str] = mapped_column(String(20), default="medium")  # easy / medium / hard / adaptive
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    planned_question_count: Mapped[int] = mapped_column(Integer, default=8)
    focus_skills: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated
    programming_language: Mapped[str | None] = mapped_column(String(40), nullable=True)  # coding interviews only
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    current_question_index: Mapped[int] = mapped_column(Integer, default=0)
    current_difficulty: Mapped[str] = mapped_column(String(20), default="medium")  # adapts as the session progresses
    consecutive_strong_answers: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_weak_answers: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_paused_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MockInterviewQuestion(Base):
    """One question asked within a session, in the order asked.
    `parent_question_id` links a follow-up back to the question it
    followed up on (see app.interview_ai.followup_engine) — NULL for a
    top-level question. `source` records what grounded this question
    (never invented out of nothing for resume_based/job_specific modes
    — see app.interview_ai.question_engine)."""

    __tablename__ = "mock_interview_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("mock_interview_sessions.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)  # 0-based order within the session
    category: Mapped[str] = mapped_column(String(60), index=True)  # e.g. "dsa", "system_design", "leadership"
    difficulty: Mapped[str] = mapped_column(String(20))
    question_text: Mapped[str] = mapped_column(Text)
    parent_question_id: Mapped[int | None] = mapped_column(ForeignKey("mock_interview_questions.id", ondelete="SET NULL"), nullable=True)
    # resume_project / job_requirement / job_skill / question_bank / ai_generated
    source: Mapped[str] = mapped_column(String(30), default="question_bank")
    source_detail: Mapped[str | None] = mapped_column(String(300), nullable=True)  # e.g. which resume project/job skill grounded it
    asked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MockInterviewAnswer(Base):
    """The candidate's answer to one question. One row per question —
    a re-submission overwrites `answer_text` and re-triggers
    evaluation rather than accumulating duplicates."""

    __tablename__ = "mock_interview_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("mock_interview_questions.id", ondelete="CASCADE"), unique=True, index=True)
    answer_text: Mapped[str] = mapped_column(Text)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MockInterviewEvaluation(Base):
    """The scored evaluation of one answer. Every *_score is 0-100 and
    every score has a matching *_explanation — "Do NOT generate
    arbitrary scores" from the spec is enforced structurally here: the
    column pair exists so an evaluation without an explanation cannot
    be stored. JSON columns hold plain lists of short strings, never a
    raw prompt/response — same posture as ResumeAISuggestion."""

    __tablename__ = "mock_interview_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int] = mapped_column(ForeignKey("mock_interview_answers.id", ondelete="CASCADE"), unique=True, index=True)
    overall_score: Mapped[int] = mapped_column(Integer)
    correctness_score: Mapped[int] = mapped_column(Integer)
    technical_depth_score: Mapped[int] = mapped_column(Integer)
    relevance_score: Mapped[int] = mapped_column(Integer)
    clarity_score: Mapped[int] = mapped_column(Integer)
    communication_score: Mapped[int] = mapped_column(Integer)
    structure_score: Mapped[int] = mapped_column(Integer)
    confidence_score: Mapped[int] = mapped_column(Integer)
    completeness_score: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str] = mapped_column(Text)  # why the overall score is what it is
    strengths_json: Mapped[str] = mapped_column(Text, default="[]")
    weaknesses_json: Mapped[str] = mapped_column(Text, default="[]")
    missing_json: Mapped[str] = mapped_column(Text, default="[]")
    improvement_tips_json: Mapped[str] = mapped_column(Text, default="[]")
    stronger_example: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_followup: Mapped[bool] = mapped_column(Boolean, default=False)
    difficulty_adjustment: Mapped[str] = mapped_column(String(20), default="same")  # increase / decrease / same
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)  # True if AI failed and a fallback evaluation was used
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MockInterviewReport(Base):
    """The final report for a completed session. Numeric scores here
    are a deterministic aggregation of every MockInterviewEvaluation in
    the session (see app.interview_ai.report_engine.aggregate_scores)
    — never a fresh AI judgment independent of the per-answer scores
    already shown to the candidate, so the report can never disagree
    with the per-question breakdown it's summarizing. Only the
    narrative text fields (`summary`, `communication_feedback`) are
    AI-generated, and only from the aggregated numbers/lists — see
    REPORT_ENGINE's grounding rule in INTERVIEW_SCORING.md."""

    __tablename__ = "mock_interview_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("mock_interview_sessions.id", ondelete="CASCADE"), unique=True, index=True)
    overall_score: Mapped[int] = mapped_column(Integer)
    technical_score: Mapped[int] = mapped_column(Integer)
    communication_score: Mapped[int] = mapped_column(Integer)
    problem_solving_score: Mapped[int] = mapped_column(Integer)
    role_fit_score: Mapped[int] = mapped_column(Integer)
    confidence_score: Mapped[int] = mapped_column(Integer)
    strengths_json: Mapped[str] = mapped_column(Text, default="[]")
    weaknesses_json: Mapped[str] = mapped_column(Text, default="[]")
    technical_gaps_json: Mapped[str] = mapped_column(Text, default="[]")  # cross-referenced with V20.2 skill gap when job_id is set
    communication_feedback: Mapped[str] = mapped_column(Text)
    recommended_topics_json: Mapped[str] = mapped_column(Text, default="[]")
    summary: Mapped[str] = mapped_column(Text)
    next_steps_json: Mapped[str] = mapped_column(Text, default="[]")
    questions_answered: Mapped[int] = mapped_column(Integer, default=0)
    questions_skipped: Mapped[int] = mapped_column(Integer, default=0)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MockInterviewCodingSubmission(Base):
    """A candidate's code submission for one coding-interview question.
    `sandbox_status` is honest about execution: this version ships no
    real sandboxed execution environment, so every submission is
    "unavailable" — the code is still reviewed (as untrusted text, by
    the same evaluation engine every other answer uses), just never
    executed. See app.interview_ai.sandbox and
    CODING_INTERVIEW_SECURITY.md."""

    __tablename__ = "mock_interview_coding_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("mock_interview_questions.id", ondelete="CASCADE"), unique=True, index=True)
    language: Mapped[str] = mapped_column(String(40))
    code_text: Mapped[str] = mapped_column(Text)
    sandbox_status: Mapped[str] = mapped_column(String(20), default="unavailable")  # unavailable / executed / error
    sandbox_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
# V20.5 — AI Learning & Skill Intelligence (Phase 1: Skill Intelligence
# core). Additive only. Builds a single canonical Skill model for the
# whole platform — app.resume_ai.skill_gap (V20.2) and
# MockInterviewReport.technical_gaps_json (V20.4) keep working exactly
# as before; app.skill_intelligence.gap composes them with this table
# rather than replacing either. See SKILL_INTELLIGENCE.md / SKILL_GRAPH.md.
# ---------------------------------------------------------------------------


class Skill(Base):
    """One canonical skill. ``canonical_name`` is the lowercase key every
    alias and every relationship resolves to — never create a second
    Skill row for a concept that already has one; add an alias instead
    (see SkillAlias). Seeded from a curated catalog
    (app.skill_intelligence.catalog) that deliberately overlaps with
    app.services.career.SKILLS rather than forking it."""

    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("canonical_name", name="uq_skill_canonical_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(120), index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(20), index=True)  # technical / soft
    subcategory: Mapped[str] = mapped_column(String(40), index=True)
    difficulty: Mapped[str] = mapped_column(String(20), default="beginner")  # beginner/intermediate/advanced/expert
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_admin_added: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SkillAlias(Base):
    """An alternate spelling/name that normalizes to one canonical
    Skill (e.g. ``js`` -> ``javascript``). Lookups are case-insensitive
    on ``alias``; see app.skill_intelligence.normalization.resolve()."""

    __tablename__ = "skill_aliases"
    __table_args__ = (UniqueConstraint("alias", name="uq_skill_alias"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    alias: Mapped[str] = mapped_column(String(120), index=True)


class SkillRelationship(Base):
    """A directed edge in the skill graph. ``relationship_type`` is one
    of: prerequisite, related, advanced_version, alternative,
    complementary. Read as "from_skill -> relationship_type -> to_skill",
    e.g. (python, prerequisite, pandas) means Python is a prerequisite
    for Pandas. See SKILL_GRAPH.md for the full seeded graph."""

    __tablename__ = "skill_relationships"
    __table_args__ = (
        UniqueConstraint("from_skill_id", "to_skill_id", "relationship_type", name="uq_skill_relationship"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    from_skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    to_skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    relationship_type: Mapped[str] = mapped_column(String(20), index=True)


# ---------------------------------------------------------------------------
# V20.5 (Phase 2) — Learning Paths & Resources. Additive only. Every
# LearningPlanModule optionally links a Skill (above) and/or a
# LearningResource; a plan is built by app.skill_intelligence.learning_path
# from the Phase-1 gap/graph engines, then persisted here so
# pause/resume/reorder/progress survive across requests. See
# LEARNING_ENGINE.md / RESOURCE_MANAGEMENT.md.
# ---------------------------------------------------------------------------


class LearningResource(Base):
    """One admin-curated learning resource. ``is_verified`` gates
    whether candidates ever see it — see AI_SAFETY.md's "never
    fabricate resource URLs" rule: every row here was entered by an
    admin, never generated. ``status`` lets an admin stage a resource
    (draft) before it's candidate-visible (published) or retire one
    (archived) without deleting history that existing plans reference."""

    __tablename__ = "learning_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(30), index=True)
    # course/book/documentation/article/video/tutorial/practice_platform/project/certification
    difficulty: Mapped[str] = mapped_column(String(20), default="beginner")
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str] = mapped_column(String(40), default="English")
    is_free: Mapped[bool] = mapped_column(Boolean, default=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)  # draft/published/archived
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # V20.5 (Phase 4) — structured project-brief fields, populated by an
    # admin only when resource_type == "project" (per the spec's
    # PROJECT RECOMMENDATIONS section: Objective/Skills/Difficulty/
    # Requirements/Expected Output/Evaluation Criteria). "Skills" and
    # "Difficulty" already exist above (skill_id, difficulty); these
    # four cover the rest. All nullable and unused for non-project
    # resource types — never auto-filled or inferred.
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluation_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LearningPlan(Base):
    """One candidate's learning plan toward a goal. ``target_skill_id``
    is optional — a plan can target a single skill or, when generated
    from a job/interview gap, cover several (see
    LearningPlanModule.skill_id on each module). ``status`` is set only
    via app.skill_intelligence.plans' validated transitions
    (draft -> active -> paused/completed/cancelled), mirroring
    MockInterviewSession's status-machine convention."""

    __tablename__ = "learning_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    target_skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"), nullable=True)
    target_job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    # active / paused / completed / cancelled
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    weekly_goal_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    # V20.5 (Phase 4) — learning streak, updated by
    # app.skill_intelligence.plans whenever a module is started/logged/
    # completed. Tracks consecutive *calendar days* with activity, not
    # sessions — matches the spec's PROGRESS TRACKING "Streak" field.
    current_streak_days: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak_days: Mapped[int] = mapped_column(Integer, default=0)
    last_activity_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LearningPlanModule(Base):
    """One step of a LearningPlan, in candidate-controlled
    ``order_index`` order (reorderable — see PUT
    /learning-plans/{id}/modules/reorder). Links the Skill it teaches
    and, when one was available at generation time, a verified
    LearningResource — never a fabricated one (module can exist with
    resource_id NULL, meaning "no verified resource yet", rather than
    inventing a URL)."""

    __tablename__ = "learning_plan_modules"
    __table_args__ = (UniqueConstraint("plan_id", "order_index", name="uq_learning_plan_module_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("learning_plans.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    resource_id: Mapped[int | None] = mapped_column(ForeignKey("learning_resources.id", ondelete="SET NULL"), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="not_started", index=True)
    # not_started / in_progress / completed / skipped
    time_spent_minutes: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# V20.5 (Phase 3) — Assessments, Practice, and Career Readiness.
# Additive only. Assessment content (questions/options/explanations) is
# admin-authored, same posture as LearningResource — never AI-generated
# at request time, so nothing here can fabricate a question or a
# "correct" answer that wasn't deliberately written by an admin.
# Readiness scores are computed on demand (app.skill_intelligence.readiness)
# from data that already exists elsewhere, not persisted — every score
# is always freshly explainable from current state.
# ---------------------------------------------------------------------------


class SkillAssessment(Base):
    """One admin-authored assessment for a skill. Made up of
    AssessmentQuestion rows; a candidate's attempt is an
    AssessmentAttempt."""

    __tablename__ = "skill_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(220))
    assessment_type: Mapped[str] = mapped_column(String(20), default="mcq")
    # mcq / coding / scenario / technical / behavioral
    difficulty: Mapped[str] = mapped_column(String(20), default="beginner")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)  # draft/published/archived
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AssessmentQuestion(Base):
    """One admin-authored MCQ question. ``options_json`` is a JSON
    list of option strings; ``correct_option`` is the 0-based index
    into that list. ``topic`` tags the question with a sub-topic of
    the skill (e.g. "closures" under javascript) so a low score on
    that topic can drive a targeted practice recommendation
    (app.skill_intelligence.practice) without re-deriving it from raw
    answers each time."""

    __tablename__ = "assessment_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("skill_assessments.id", ondelete="CASCADE"), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    options_json: Mapped[str] = mapped_column(Text)  # JSON list[str]
    correct_option: Mapped[int] = mapped_column(Integer)
    topic: Mapped[str] = mapped_column(String(80))
    difficulty: Mapped[str] = mapped_column(String(20), default="beginner")
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class AssessmentAttempt(Base):
    """One candidate's attempt at a SkillAssessment. Scored by
    app.skill_intelligence.assessments.submit — never self-reported by
    the client."""

    __tablename__ = "assessment_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("skill_assessments.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="in_progress", index=True)  # in_progress/completed
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    score_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    weak_topics_json: Mapped[str] = mapped_column(Text, default="[]")  # JSON list[str]
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AssessmentAnswer(Base):
    """One answer within an AssessmentAttempt."""

    __tablename__ = "assessment_answers"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id", name="uq_assessment_answer"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("assessment_attempts.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("assessment_questions.id", ondelete="CASCADE"), index=True)
    selected_option: Mapped[int] = mapped_column(Integer)
    is_correct: Mapped[bool] = mapped_column(Boolean)


class PracticeRecommendation(Base):
    """A generated (not fabricated — derived from real weak-topic and
    skill-gap data, see app.skill_intelligence.practice) recommendation
    to act on. ``status`` lets a candidate dismiss one without it being
    regenerated identically next time."""

    __tablename__ = "practice_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    recommendation_type: Mapped[str] = mapped_column(String(30))
    # practice_questions / coding_problems / projects / mock_interviews / revision
    reason: Mapped[str] = mapped_column(Text)
    priority_score: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending/dismissed/completed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# V21.3 — AI Job Recommendation Engine. Additive only. Builds entirely on
# existing tables/engines: Profile, CareerPreference, Resume/ResumeAnalysis
# (V20.2), Skill/SkillAlias (V20.5), SavedJob/Application (V1/V6),
# search_index_documents (V21.1) for candidate retrieval. Only four new
# tables, none of which duplicates Jobs/Users/Skills/Applications/Bookmarks:
#
# - RecommendationPreference: recommendation-specific settings not already
#   covered by Profile (candidate *is*) or CareerPreference (candidate
#   *wants*) — e.g. which opportunity types to include, employment-type
#   filter. One row per user, all optional.
# - RecommendationFeedback: latest feedback state per (user, job) —
#   interested/not_interested/dismiss/not_relevant. Save/Apply are NOT
#   duplicated here; they read/write the existing SavedJob/Application
#   tables directly (see app.recommendations.feedback).
# - RecommendationSnapshot: one cached "Jobs For You" result set per user,
#   replaced on recompute (same posture as ResumeAnalysis) — keyed by an
#   input_signature so a snapshot is only reused while nothing that would
#   change it (resume, skills, career goal, preferences, saved/applied
#   jobs, or the underlying job pool) has changed. See
#   RECOMMENDATION_ARCHITECTURE.md.
# - RecommendationEvent: privacy-safe aggregate analytics log (impression/
#   open/save/apply/dismiss/not_relevant) for CTR/conversion reporting
#   only — never a second copy of application data.
# ---------------------------------------------------------------------------


class RecommendationPreference(Base):
    """V21.3 — candidate-controlled recommendation settings. Distinct
    from CareerPreference (V20.3, unchanged): that table is read as an
    input signal here, not extended, since its fields (target_role,
    preferred_industry, ...) already mean exactly what the spec's
    PERSONALIZATION section asks for. This table only adds the couple
    of knobs that don't already exist anywhere: which opportunity
    types to surface at all, and an explicit employment-type filter."""

    __tablename__ = "recommendation_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    include_government: Mapped[bool] = mapped_column(Boolean, default=True)
    include_private: Mapped[bool] = mapped_column(Boolean, default=True)
    include_internships: Mapped[bool] = mapped_column(Boolean, default=True)
    include_apprenticeships: Mapped[bool] = mapped_column(Boolean, default=True)
    preferred_employment_types: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated
    diversity_level: Mapped[str] = mapped_column(String(20), default="balanced")  # low/balanced/high
    # V21.4 — USER CONTROLS: "Personalized Recommendations ON/OFF". When
    # False, the ranking pipeline skips app.recommendations.signals
    # entirely (no learned-behavior component), while explicit,
    # candidate-stated preferences (skills, career goal, location, the
    # fields above) keep working exactly as before — this only turns
    # off the *learned* behavioral layer. See PERSONALIZATION_ARCHITECTURE.md.
    personalization_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RecommendationFeedback(Base):
    """V21.3 — the candidate's latest stated feedback on one job's
    recommendation. One row per (user, job); a repeat feedback action
    updates this row rather than appending, since only the current
    state ("do not show me this again", "not relevant") matters for
    future ranking — the analytics *history* of feedback events is
    captured separately in RecommendationEvent, which is append-only.
    """

    __tablename__ = "recommendation_feedback"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_recommendation_feedback_user_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    feedback_type: Mapped[str] = mapped_column(String(20), index=True)
    # interested / not_interested / dismiss / not_relevant
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RecommendationSnapshot(Base):
    """V21.3 — cached "Jobs For You" result for one candidate. Same
    "working document, not an archive" posture as ResumeAnalysis
    (V20.2): one row per user, overwritten on recompute. Recompute is
    triggered when ``input_signature`` (a hash of the candidate/job
    signals that could change the result — see
    app.recommendations.cache) no longer matches what's on file, or
    when the snapshot has passed ``expires_at``, or on an explicit
    POST /job-recommendations/refresh."""

    __tablename__ = "recommendation_snapshots"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    input_signature: Mapped[str] = mapped_column(String(64), index=True)
    results_json: Mapped[str] = mapped_column(Text)  # serialized list[RankedRecommendation]
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class RecommendationEvent(Base):
    """V21.3 — privacy-safe aggregate analytics event (ANALYTICS
    requirement). Records only what's needed for impression/open/CTR/
    conversion reporting: which user saw or acted on which recommended
    job, when, and how. Never stores resume text, scores, or any other
    personal-data payload — see RECOMMENDATION_PRIVACY.md. This is an
    events log for aggregate reporting only; it is never read as the
    source of truth for "is this job saved/applied" (SavedJob/
    Application remain that source of truth).

    V21.4 additions (all additive, all nullable — no existing row or
    query changes behavior):
    - ``job_id`` is now nullable: "search" and "filter_usage" events
      (BEHAVIORAL SIGNALS) aren't about one specific job. Search text
      itself is never duplicated here — it's already captured by
      V21.2's ``RecentSearch``; this just logs that a search happened.
    - ``filters_json``: short structured metadata only — which filter
      dimension changed (filter_usage), or a feed request's result
      count/latency (the synthetic ``feed_view`` event type, used only
      for ADMIN no-result-rate/latency metrics). Never free text a
      candidate typed, never a resume/profile fragment.
    - ``experiment_variant``: which A/B TESTING FOUNDATION variant (if
      any) was active for this event. NULL for every event while no
      experiment is active (the default) — see
      app.recommendations.experiments and RANKING_EXPERIMENTS.md.
    """

    __tablename__ = "recommendation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(20), index=True)
    # impression / open / save / apply / dismiss / not_relevant /
    # interested / not_interested / share / filter_usage / feed_view
    filters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    experiment_variant: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ---------------------------------------------------------------------------
# V21.4 — Advanced Personalization & Intelligent Ranking. Additive only.
# See PERSONALIZATION_ARCHITECTURE.md / BEHAVIOR_SIGNALS.md /
# RANKING_ENGINE_V21_4.md / RANKING_EXPERIMENTS.md for how each of
# these is used. Deliberately NOT added: a second job/recommendation
# database, a second events table (RecommendationEvent above is
# extended, not duplicated), or a second candidate-preferences table
# (RecommendationPreference above is extended for the ON/OFF toggle).
# ---------------------------------------------------------------------------


class BehaviorSignalAggregate(Base):
    """V21.4 — one time-decayed, incrementally-updated behavioral
    signal for one candidate. Composite primary key
    ``(user_id, signal_type, signal_key)`` — e.g.
    ``("skill", "python")``, ``("company", "Acme Corp")``,
    ``("location", "Noida")``, ``("job_type", "Government")``,
    ``("role_keyword", "backend")``.

    ``score`` is a running exponentially time-decayed weighted sum
    (see app.recommendations.events._decay_factor /
    BEHAVIOR_SIGNALS.md), updated in place on every new event rather
    than being recomputed from raw event history — this is what lets
    TIME DECAY and PERFORMANCE both hold without keeping unlimited
    per-event history for ranking purposes (raw events, kept
    separately in ``RecommendationEvent`` for analytics, follow their
    own retention policy — see DATA_RETENTION notes in
    BEHAVIOR_SIGNALS.md). A negative ``score`` means net-negative
    interactions with that signal (e.g. repeatedly dismissed
    Government roles); it is clamped to a bounded range
    (``app.recommendations.events.SCORE_CLAMP``) so one strong negative
    interaction can never zero out or permanently exclude an entire
    category — it only ever reduces that category's ranking boost,
    and decays back toward zero over time on its own even without
    further interaction.
    """

    __tablename__ = "behavior_signal_aggregates"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    signal_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    signal_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    last_event_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RankingConfiguration(Base):
    """V21.4 — RANKING CONFIGURATION, admin-tunable. One row per
    config key (e.g. ``"component_weights"``, ``"time_decay_half_life_days"``,
    ``"event_weights"``, ``"negative_feedback_penalty"``); ``value_json``
    holds that key's current value. A missing row for a key means "use
    the documented code-level default" (see RANKING_ENGINE_V21_4.md) —
    this table only ever *overrides* defaults, so it's fully functional
    empty. Never exposed to normal candidates — see admin_guard-gated
    endpoints in app/api/recommendations.py ("Do NOT expose dangerous
    internal configuration directly to normal users")."""

    __tablename__ = "ranking_configuration"

    config_key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class RankingExperiment(Base):
    """V21.4 — A/B TESTING FOUNDATION. Defines an experiment and its
    variant allocation; does NOT store per-user assignments, because
    assignment is a deterministic pure function of
    ``(user_id, experiment_key)`` — see
    app.recommendations.experiments.assign_variant — so it can never
    drift out of sync with this table and needs no extra storage or
    cleanup. ``status='draft'`` (the default) means the experiment has
    no effect on ranking at all; only an admin explicitly flipping
    ``status='active'`` turns it on ("Do NOT launch uncontrolled
    experiments. Do NOT randomly change ranking for users without
    configuration'). At most one experiment is treated as active at a
    time — see RANKING_EXPERIMENTS.md."""

    __tablename__ = "ranking_experiments"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_key: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft / active / stopped
    variants_json: Mapped[str] = mapped_column(Text)  # e.g. {"control": 50, "variant_b": 50}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class JobAlert(Base):
    """V23.3 — Smart Job Alerts: a candidate's saved alert
    configuration. Deliberately a NEW table/model rather than reusing
    ``Alert`` (V7/V19.4's simple ``alert_type='job'`` saved-search —
    see app.services.notifications._check_saved_search_alerts). That
    table intentionally stays exactly as-is (spec: "Do NOT remove or
    break V16-V23.2 functionality") — it's a single free-text query
    match with no frequency/threshold/dedup/digest concept. A JobAlert
    is a materially richer object (structured criteria across many
    fields, INSTANT/DAILY/WEEKLY frequency, an optional minimum
    relevance score, an optional "use my profile" personalization
    flag), so it gets its own table rather than overloading Alert's
    single `query` text column — see docs/V23_3_SMART_JOB_ALERTS.md.

    Every criteria field is nullable — "Do not require every field"
    (spec section 2). A field left NULL means "don't filter on this,"
    never "match nothing."
    """

    __tablename__ = "job_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    name: Mapped[str] = mapped_column(String(160))

    # --- Criteria (all optional — see class docstring) ---
    keywords: Mapped[str | None] = mapped_column(String(300), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(220), nullable=True)
    skills: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated, same convention as Job.skills
    location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    remote_preference: Mapped[str | None] = mapped_column(String(20), nullable=True)  # remote / hybrid / onsite / any
    employment_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    experience_level: Mapped[str | None] = mapped_column(String(120), nullable=True)
    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    job_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # government / private / any(NULL) — mirrors Job.job_type == "Government" check
    # used throughout this codebase (see app.recommendations.job_features.build).
    govt_private_preference: Mapped[str | None] = mapped_column(String(20), nullable=True)
    company: Mapped[str | None] = mapped_column(String(220), nullable=True)
    source: Mapped[str | None] = mapped_column(String(60), nullable=True)

    frequency: Mapped[str] = mapped_column(String(20), default="INSTANT", index=True)  # INSTANT / DAILY / WEEKLY
    min_relevance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100, user-facing normalized scale
    use_profile_personalization: Mapped[bool] = mapped_column(Boolean, default=False)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Execution bookkeeping (denormalized here for cheap list-view
    # reads — JobAlertRun below remains the durable per-run audit
    # trail; these three columns are just "the latest one," updated
    # in the same transaction as the JobAlertRun row they summarize).
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # SUCCESS / FAILED
    last_match_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_job_alerts_enabled_frequency", "enabled", "frequency"),
    )


class JobAlertRun(Base):
    """V23.3 — one execution of one JobAlert (manual or scheduled).
    The durable audit trail behind JobAlert's denormalized
    last_run_*/last_match_count columns — spec section 19 ("Alert
    History": last execution, matches, notifications, failures)."""

    __tablename__ = "job_alert_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_alert_id: Mapped[int] = mapped_column(ForeignKey("job_alerts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")  # RUNNING / SUCCESS / FAILED
    candidates_scanned: Mapped[int] = mapped_column(Integer, default=0)
    jobs_matched: Mapped[int] = mapped_column(Integer, default=0)
    notifications_created: Mapped[int] = mapped_column(Integer, default=0)
    emails_queued: Mapped[int] = mapped_column(Integer, default=0)
    # Never a raw stack trace (spec section 19) — a short, safe summary.
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)


class JobAlertDelivery(Base):
    """V23.3 — durable deduplication/delivery record. Spec section 8:
    "A candidate must NOT receive repeated alerts for the same job" —
    across multiple alert runs, retries, email+in-app processing, and
    worker restarts. This table (not a job_id uniqueness constraint —
    the same job legitimately matches multiple alerts, per spec) is
    the single source of truth checked before any notification/email
    is created for a (job_alert_id, job_id) pair, and the row is
    written in the SAME transaction as the delivery it records, under
    the UNIQUE constraint below, so a concurrent/retried worker loses
    the insert race rather than double-delivering — see
    app.job_alerts.execution.
    """

    __tablename__ = "job_alert_deliveries"
    __table_args__ = (
        UniqueConstraint("job_alert_id", "job_id", "channel", name="uq_job_alert_delivery_alert_job_channel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_alert_id: Mapped[int] = mapped_column(ForeignKey("job_alerts.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(10))  # IN_APP / EMAIL
    relevance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ---------------------------------------------------------------------------
# V25.2 — Advanced Admin & Platform Governance.
#
# Three new tables, and deliberately only three. Everything else this
# version needs already exists and is extended in place instead:
#
# - Security events (spec section 23) reuse the V17.2
#   `app.core.security_events` taxonomy, which writes to the existing
#   `audit_logs` table — no `security_events` table is created, because
#   a second security-event store would be exactly the "duplicate audit
#   system" spec section 28 warns against.
# - Per-resource admin history (spec section 12) is a filtered read of
#   `platform_audit_logs` below, not a per-resource history table.
# - Background-job and ingestion monitoring (sections 17/18) read the
#   already-durable `IngestionRun`/`IngestionRunLog`/`SourceRegistry`/
#   `AutomationLog` rows and the in-process `app.scheduler.job_health`
#   map; nothing new is recorded for them.
# ---------------------------------------------------------------------------


class PlatformAuditLog(Base):
    """The append-only record of every platform-administrator action.

    Why this is a separate table from the general-purpose `audit_logs`
    (V16) rather than more columns on it: the two have genuinely
    different shapes and different retention/immutability contracts.
    `audit_logs` is a high-volume, application-wide activity trail
    (every login, every job publish, every organization event) whose
    rows carry a single free-text `detail`. A platform-governance
    record has to answer a fixed set of investigative questions —
    which administrator, against which target, in which organization,
    for what structured reason, with what outcome — and has to be
    queryable on each of those independently for the
    /admin/audit investigation UI. Encoding organization_id, reason,
    result and metadata into `audit_logs.detail` as free text would
    make every one of those filters a substring scan.

    Both are still written for an admin action: `log_audit` keeps the
    platform-wide trail complete and unchanged for anything already
    reading it, and this table adds the structured governance record
    on top. See app.core.platform_audit.record_platform_action.

    APPEND-ONLY: the application layer never issues an UPDATE or
    DELETE against this table. There is no endpoint, admin or
    otherwise, that edits or removes a row — see
    docs/V25_2_ADMIN_PLATFORM_GOVERNANCE.md for the data-retention
    discussion.
    """

    __tablename__ = "platform_audit_logs"
    __table_args__ = (
        Index("ix_platform_audit_target", "target_type", "target_id"),
        Index("ix_platform_audit_actor", "actor_user_id", "created_at"),
        Index("ix_platform_audit_action_created", "action", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # One of app.core.platform_audit.PlatformAction — a plain string
    # column (no DB enum), matching this codebase's convention for
    # extensible value sets (see app.core.rbac's notes on User.role).
    action: Mapped[str] = mapped_column(String(60), index=True)
    # "user" | "organization" | "job" | "platform_setting" | "announcement" | ...
    target_type: Mapped[str] = mapped_column(String(40), index=True)
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Set when the action concerns, or happened inside, one
    # organization — so an investigator can pull every platform action
    # touching one tenant without joining through each target type.
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # NULL only for the shared X-Admin-Key break-glass credential,
    # which has no user row of its own (actor_type records which it
    # was). Never NULL for a JWT-authenticated administrator.
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(20), default="user")  # user | admin_key
    actor_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # Structured reason code where the action requires one (job
    # rejection/suspension, user/organization suspension).
    reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # The administrator's free-text note. Internal: never returned on
    # any non-platform-admin endpoint.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON-encoded, deliberately small: before/after state for the
    # changed fields only. Never a full record dump, and never
    # anything from the "must not be exposed" list in spec section 15
    # (no resume content, no private documents, no secrets).
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "success" | "failure" | "partial" — a bulk operation that
    # partially applied records "partial" with per-item counts in
    # metadata_json.
    result: Mapped[str] = mapped_column(String(20), default="success", index=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class PlatformSetting(Base):
    """One typed, validated platform configuration value.

    Deliberately NOT an untyped JSON blob (spec section 19): the
    authoritative list of what settings exist, what type each is, its
    default, and whether changing it is sensitive lives in code, in
    app.core.platform_settings.SETTING_DEFINITIONS. This table stores
    only the *overrides* an administrator has actually made. A key
    that isn't in the code-side registry is rejected at write time and
    ignored at read time, so a stray row can never introduce an
    unknown setting.

    `value_json` holds the value JSON-encoded (so a bool stays a bool
    and an int stays an int across SQLite and PostgreSQL alike)
    together with its declared type, which is re-validated on read.
    """

    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    value_json: Mapped[str] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(20))  # bool | int | str
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PlatformAnnouncement(Base):
    """An administrator-authored platform announcement.

    This is a *record of intent plus delivery state*, not a new
    notification system (spec section 21): actual delivery goes
    through the existing V23.1 `app.notifications.service` (in-app)
    and V23.2 `app.email.service` (email), so per-user preferences,
    deduplication and the retrying email queue all apply unchanged.

    An announcement is created in DRAFT and delivers nothing. Sending
    is a separate, explicit, audited action — so there is no single
    request that can both create and mass-mail an announcement by
    accident. Email delivery additionally requires the
    `announcement_email_enabled` platform setting to be on.
    """

    __tablename__ = "platform_announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(220))
    message: Mapped[str] = mapped_column(Text)
    # ALL | CANDIDATES | RECRUITERS | ORGANIZATION_ADMINS | PLATFORM_ADMINS
    audience: Mapped[str] = mapped_column(String(30), default="ALL", index=True)
    # IN_APP | EMAIL | BOTH
    channel: Mapped[str] = mapped_column(String(10), default="IN_APP")
    # DRAFT | SENDING | SENT | FAILED
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
# V25.3 — Data Intelligence, Career & Market Analytics.
#
# One new table, and only one. Everything else V25.3 reports is derived
# live from tables that already exist: skill frequency from `jobs.skills`,
# hiring metrics from `applicants` via the V24.4 service, platform counts
# from V25.2's analytics, and ingestion figures from `ingestion_runs`.
#
# Deliberately NOT created (spec sections 15, 16 and 30):
#
#   * No analytics aggregate or snapshot tables. Every V25.3 aggregate is
#     a GROUP BY or COUNT over indexed columns, bounded by a date window
#     and a page size. Copying the production data into a parallel
#     analytics schema would add a freshness problem, a refresh job and a
#     reconciliation burden to buy performance that measurement has not
#     yet shown to be needed.
#
#   * No materialized views, for the same reason, and because the
#     application supports both SQLite and PostgreSQL — a materialized
#     view would exist on one and not the other, giving the two backends
#     different freshness semantics for the same endpoint.
#
#   * No new analytics event table. CareerOS already records every event
#     section 16 lists that it records at all: `recommendation_events`
#     (impression/open/save/apply/dismiss/search/filter usage),
#     `application_events` (notes/interviews/tasks/documents),
#     `application_status_history`, `recruiter_pipeline_history` (stage
#     changes), `search_query_logs` / `recent_searches`, plus `saved_jobs`
#     and `applicants` themselves. Adding a general page-view or
#     job-view tracker would be new behavioural collection with a new
#     retention obligation, for a metric V24.4 already reports honestly
#     as unavailable. Section 16 says to add only events genuinely
#     needed; none were.
# ---------------------------------------------------------------------------


class DataQualityIssueState(Base):
    """An administrator's triage decision about one detected data-quality
    issue (V25.3, spec section 13).

    Data-quality issues themselves are NOT stored: they are recomputed
    from `app.intelligence.quality.rules` on every request, so the report
    can never drift out of date with the data it describes and a fixed
    row simply stops being flagged. What is stored is the human judgement
    a recomputation cannot reproduce — "we know about this one",
    "this is expected, leave it".

    This is the only writable surface in the data-quality feature. No
    endpoint there modifies an inspected job, candidate or application;
    section 13 requires that production data not be changed without an
    explicit safe workflow, and V25.3's answer is that there is no
    automatic modification at all.

    `entity_id` is intentionally a plain integer rather than a foreign
    key: a single row here may refer to a job, a user or an applicant
    depending on its rule, and several rules exist precisely to find rows
    whose references are already broken — a FK would make the orphan
    rules impossible to triage.
    """

    __tablename__ = "data_quality_issue_states"
    __table_args__ = (
        UniqueConstraint("rule_id", "entity_id", name="uq_data_quality_issue_state"),
        Index("ix_data_quality_issue_states_rule_state", "rule_id", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    # open / acknowledged / resolved / wont_fix
    state: Mapped[str] = mapped_column(String(20), default="open", index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
# V25.4 — Advanced AI Career Agent & Automation. Additive only.
#
# Reuses (never duplicates): app.ai.completion_service (the V20.1 AI
# Gateway) for the one generative call per turn; app.career_copilot's
# context_engine/system_prompt for grounding and prompt-injection
# defense; and the V21/V22/V23/V24/V25.3 services themselves
# (search, recommendations, applications, notifications, skill
# intelligence, resume/interview AI) as the agent's *tools* — see
# app/career_agent/tools.py.
#
# Four new tables, deliberately NOT a reuse of `ai_conversations` /
# `ai_messages` (V20.1, also used as-is by V20.3 Career Copilot):
# an agent turn needs to carry structured, inspectable metadata (which
# tool ran, which action it produced) that the generic AIMessage row
# has no column for, and a "pending confirmation" write action has no
# analogue in a plain chat log at all. Extending AIMessage with an
# agent-only metadata column and bolting an action table onto a
# generic chat schema would entangle two independently-evolving
# features for no shared benefit — the same reasoning V23.3's
# JobAlert docstring gives for staying a separate table from the
# older `alerts` table. See docs/V25_4_AI_CAREER_AGENT.md.
# ---------------------------------------------------------------------------


class CareerAgentConversation(Base):
    """One Career Agent chat thread. Always user-owned (unlike
    `AIConversation`, the agent has no anonymous/pre-login mode) —
    every query in app/career_agent scopes by `user_id` so one
    candidate's conversations are never visible to another (spec
    section 15/34)."""

    __tablename__ = "career_agent_conversations"
    __table_args__ = (Index("ix_career_agent_conversations_user_updated", "user_id", "updated_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # active / archived — archiving (not deleting) is what "start a new
    # conversation" without losing history does; DELETE removes the row.
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CareerAgentMessage(Base):
    """One turn in a CareerAgentConversation. `metadata_json` carries
    the agent-specific, inspectable trail a plain chat message doesn't
    need: which state the turn ended in, which tool (if any) was
    selected/executed, and the id of any CareerAgentAction it produced
    — this is what lets the frontend show "tool/action indicators"
    (spec section 29) without re-deriving them from prose."""

    __tablename__ = "career_agent_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("career_agent_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user / assistant / system
    content: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class CareerAgentAction(Base):
    """One tool invocation the agent proposed or ran — the audit trail
    behind the confirmation model (spec sections 4, 18, 26, 34).

    `status` is the state-machine value for this one action:
    PENDING_CONFIRMATION / CONFIRMED / EXECUTING / COMPLETED / REJECTED
    / FAILED. READ actions are written here already COMPLETED (so the
    log is a complete tool-call history, not just of writes); WRITE
    and HIGH_RISK actions are written PENDING_CONFIRMATION and only
    move to EXECUTING/COMPLETED after an explicit confirm call.

    `payload_json` is the validated, whitelisted tool parameters the
    agent proposed — never raw model output and never a query string —
    and is deliberately minimized (spec section 32): no secrets, no
    full resume/document text, just the small structured arguments a
    tool call needs (job ids, a task title, a due date, ...).
    """

    __tablename__ = "career_agent_actions"
    __table_args__ = (
        Index("ix_career_agent_actions_user_status", "user_id", "status"),
        Index("ix_career_agent_actions_conversation", "conversation_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("career_agent_conversations.id", ondelete="SET NULL"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(60), index=True)  # tool name, e.g. "schedule_follow_up"
    risk_level: Mapped[str] = mapped_column(String(20))  # READ / WRITE / HIGH_RISK
    status: Mapped[str] = mapped_column(String(30), default="PENDING_CONFIRMATION", index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CareerAgentPreference(Base):
    """Per-candidate Career Agent *behavior* settings — proactive
    notifications on/off, frequency, quiet hours, channels (spec
    section 21). Deliberately NOT where career goals/target role live
    (that's the existing `CareerPreference`, reused as-is) — this is
    configuration for the agent's own automation, not career data, so
    it stays out of the AI's grounding context entirely."""

    __tablename__ = "career_agent_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    proactive_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # instant / daily / weekly
    frequency: Mapped[str] = mapped_column(String(20), default="daily")
    quiet_hours_start: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-23, local-hour convention
    quiet_hours_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # comma-separated subset of {"in_app"} today — kept open-ended for a
    # future channel (email/SMS) without another migration.
    channels: Mapped[str] = mapped_column(String(120), default="in_app")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
