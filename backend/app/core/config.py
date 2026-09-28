"""Application configuration.

Settings are loaded from environment variables (or a local ``.env`` file)
using pydantic-settings. Nothing sensitive ships with a real default —
the placeholders below are safe only for local development and must be
overridden before any public deployment (see README "Security").
"""

from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CareerOS API"
    environment: str = "development"
    log_level: str = "INFO"

    # V11 test convenience — when true, registration auto-verifies email
    # instead of requiring the real OTP flow, so the existing test suite
    # doesn't need to intercept outbound email to exercise register->login.
    # Explicit and opt-in (set only by the test suite's own environment,
    # never inferred from DATABASE_URL) so a production deployment can
    # never end up here by an unlucky coincidence of naming its database.
    auto_verify_email_in_tests: bool = False

    database_url: str = "sqlite:///./careeros.db"

    # Comma-separated list of allowed browser origins, e.g.
    # "http://localhost:3000,https://app.careeros.example"
    frontend_origin: str = "http://localhost:3000"

    admin_api_key: str = "change-this-admin-key"
    jwt_secret: str = "change-this-jwt-secret-before-production"
    # V17.1 — access tokens are now short-lived; long-lived sessions are
    # carried by refresh tokens instead (see app/core/sessions.py), not
    # by a long-lived access token as before. access_token_days is kept
    # (unused by new code) only so an old JWT issued pre-V17.1 with a
    # matching claim shape still decodes during a rolling deploy.
    access_token_days: int = 7
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    refresh_token_remember_me_days: int = 90
    password_history_limit: int = 5
    password_min_length: int = 12

    # Email verification. Configure SMTP in production. In local development,
    # OTP is printed to the backend terminal so the flow can be tested without secrets.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_name: str = "CareerOS"
    smtp_use_tls: bool = True
    email_otp_minutes: int = 10
    # V23.2 — Email Notification & Template Engine.
    # "console" (default, dev-safe): renders + logs the email, never
    # opens a real SMTP connection. "smtp": actually sends via the
    # SMTPProvider (app/email/provider.py), which requires
    # smtp_host/smtp_from_email to be set — see Settings.is_production
    # validation note in app/email/provider.py for why production must
    # not silently fall back to console mode.
    email_mode: str = "console"
    email_max_retry_attempts: int = 4
    email_retry_backoff_seconds: int = 60
    email_queue_interval_minutes: int = 2

    # V23.3 — Smart Job Alerts scan interval. Short, like the email
    # queue's — this is also what makes INSTANT alerts feel instant.
    job_alerts_interval_minutes: int = 5

    # V23.4 — Communication Center. The reminder scan is frequent
    # enough that a 24-hours-before/1-hour-before interview reminder
    # or a due-today deadline reminder fires close to its target
    # window rather than up to an hour late; the digest scan is
    # coarser since it only needs to catch "a new UTC day has started
    # for this user" once, and DAILY_CAREER_DIGEST's own per-user-
    # per-day dedupe_key (see app.communication.digest) makes an
    # extra tick a harmless no-op either way.
    communication_reminder_interval_minutes: int = 15
    communication_digest_interval_minutes: int = 60

    # Basic brute-force protection for /auth endpoints.
    auth_rate_limit_attempts: int = 10
    auth_rate_limit_window_seconds: int = 60

    # V16 — optional shared backend for app.core.rate_limit. Unset by
    # default: the limiter falls back to in-memory, which is genuinely
    # fine for a single instance (the default docker-compose.production.yml
    # topology) but doesn't share state across replicas. Set this only if
    # you're actually running more than one backend replica/worker.
    redis_url: str | None = None

    # V17.2 — stricter, distinct rate-limit budgets for a couple of
    # buckets that warranted a tighter limit than the general
    # auth_rate_limit_* default (used by login/register/refresh/etc.).
    admin_login_rate_limit_attempts: int = 5
    admin_login_rate_limit_window_seconds: int = 300
    profile_update_rate_limit_attempts: int = 20
    profile_update_rate_limit_window_seconds: int = 60

    # V17.2 — account lockout. Distinct from the per-IP rate limiter
    # above: this tracks failures *per account*, so an attacker
    # rotating IPs against one known email still gets stopped. See
    # app/core/account_lockout.py.
    account_lockout_threshold: int = 5
    account_lockout_base_minutes: int = 5
    account_lockout_max_minutes: int = 240
    # "Progressive login delay": once failures pass this count, each
    # subsequent attempt must wait an increasing number of seconds
    # since the last failure (see account_lockout.progressive_delay_seconds)
    # — before the account reaches the hard lockout threshold above.
    account_progressive_delay_after_attempts: int = 3
    account_progressive_delay_base_seconds: int = 2
    account_progressive_delay_max_seconds: int = 30
    # Default duration an admin's manual temporary lock lasts if they
    # don't specify one explicitly (POST /admin/users/{id}/lock).
    default_admin_lock_minutes: int = 60

    # V17.2 — OTP hardening beyond what V16/V17.1 already had (hashed
    # storage, expiry, single-use). See app/core/otp_security.py.
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60

    # V17.2 — session timeouts, enforced in app/core/sessions.py on
    # every refresh (access tokens are short-lived, so a refresh call
    # is the natural, frequent checkpoint). Idle timeout resets on
    # activity (UserSession.last_seen_at); absolute timeout does not
    # — it's a hard cap from session creation regardless of activity.
    session_idle_timeout_minutes: int = 10080  # 7 days of no refresh calls
    session_absolute_timeout_days: int = 90

    # Upload limits protect worker memory and document parsers.
    resume_max_upload_mb: int = 8
    notification_pdf_max_upload_mb: int = 10
    # V22.3 — Application Documents. Files are stored on disk under
    # this directory, named only by a server-generated UUID (never the
    # user-supplied original filename — see app.applications.documents),
    # and this directory is never mounted as static/public.
    application_document_max_upload_mb: int = 10
    application_document_storage_dir: str = "var/uploads/application_documents"

    # V10 — connection pool sizing. Defaults are conservative for a
    # single small instance; a real production deployment should size
    # pool_size * (number of API replicas) to stay under the database's
    # own max_connections, with headroom for admin tools/migrations.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800

    # V2 automated collection. Off by default — an operator must review
    # app/ingestion/sources.py, confirm each source's live page structure
    # is still accurate, and set ingestion_enabled=true (or flip individual
    # sources' enabled flag) before it runs unattended. Everything it
    # collects still lands in the review queue, never auto-published.
    #
    # (This was found flipped to True during a later review pass, with no
    # accompanying verification that any source's live markup had actually
    # been checked — restored to False, matching this comment and the
    # per-source `enabled` flags in app/ingestion/sources.py, which carry
    # the same requirement. See ROADMAP.md's bug-review notes.)
    ingestion_enabled: bool = False
    ingestion_interval_minutes: int = 360
    ingestion_user_agent: str = "CareerOSBot/1.0 (+https://github.com/careeros; contact: set-a-real-contact-email)"
    ingestion_request_timeout_seconds: int = 20

    # V25.7 — auto-fill vacancies/dates/qualification/fee/etc. by reading
    # each record's notification PDF/page (app/ingestion/services/enrichment.py).
    ingestion_enrich_details: bool = True
    # Optional LLM fallback for fields the regex extractor could not find.
    # Uses the project's existing AI provider config; off by default (costs tokens).
    ingestion_ai_enrichment: bool = False
    # Max new records enriched (=extra downloads) per source per run.
    ingestion_enrich_max_per_run: int = 40
    # Run DB-registered sources (source_registry rows with status=active)
    # automatically. Off by default, same as ingestion_enabled.
    ingestion_registry_enabled: bool = False
    ingestion_registry_interval_minutes: int = 60

    # V6 Career AI — optional natural-language layer on top of the
    # deterministic match/eligibility/skill-gap engines. Off by default;
    # falls back to a template-based summary when no key is set, so the
    # feature works out of the box without any paid API. The model name
    # is intentionally not hardcoded to one snapshot — set it to whatever
    # is current per Anthropic's docs when you enable this.
    career_ai_anthropic_api_key: str | None = None
    career_ai_model: str = "claude-sonnet-5"
    career_ai_timeout_seconds: int = 20

    # V20.1 — AI Infrastructure & LLM Framework. Provider-agnostic
    # foundation layer (app/ai/) that future AI features build on; this
    # is separate from V6's career_ai_* keys above, which remain
    # untouched and continue to power app/services/career_ai.py
    # directly. Every ai_* key here is optional — with no provider key
    # set, app/ai's services return clear "not configured" errors
    # rather than the process failing to start.
    ai_default_provider: str = "anthropic"
    ai_fallback_provider: str | None = None
    ai_request_timeout_seconds: float = 30.0
    ai_max_retries: int = 1
    ai_default_model: str = "claude-sonnet-5"
    ai_default_temperature: float = 0.7
    ai_default_max_tokens: int = 1024
    ai_max_context_tokens: int = 8000

    ai_anthropic_api_key: str | None = None
    ai_anthropic_model: str = "claude-sonnet-5"
    ai_openai_api_key: str | None = None
    ai_openai_model: str = "gpt-4o-mini"
    ai_openai_embedding_model: str = "text-embedding-3-small"
    ai_gemini_api_key: str | None = None
    ai_gemini_model: str = "gemini-3.6-flash"
    ai_watsonx_api_key: str | None = None
    ai_watsonx_project_id: str | None = None
    ai_watsonx_url: str = "https://us-south.ml.cloud.ibm.com"
    ai_watsonx_model: str = "ibm/granite-4-h-small"
    ai_watsonx_api_version: str = "2025-10-25"
    ai_openrouter_api_key: str | None = None
    ai_openrouter_model: str = "openrouter/auto"

    ai_moderation_enabled: bool = False

    # Conversation memory (app/ai/conversation_manager.py): once a
    # thread's message_count reaches the summary trigger, everything
    # older than the most recent `history_max_messages` turns is
    # compressed into AIConversation.summary.
    ai_conversation_history_max_messages: int = 20
    ai_conversation_summary_trigger: int = 30

    # V7 Application OS — in-app deadline/admit-card/result notifications.
    # Unlike ingestion, this only reads the local DB (no outbound network
    # calls), so it's safe to run by default rather than opt-in.
    deadline_reminder_days: int = 3
    notification_scan_interval_minutes: int = 60

    # V19.4 — Automation & Notification Engine. Same "reads the local
    # DB only" safety as the V7 scan above, so also safe to run by
    # default. Automation (subscription/lifecycle-event fan-out) runs
    # hourly; reminder sync (creating new ReminderRule rows for newly
    # relevant dates) runs daily since it only needs to catch newly-set
    # dates, not near-real-time; reminder firing reuses the hourly
    # automation interval so a reminder due today doesn't wait a full day.
    automation_scan_interval_minutes: int = 60
    reminder_sync_interval_minutes: int = 1440

    # V21.1 — Unified Search Infrastructure. The DatabaseSearchProvider's
    # index (search_index_documents) is a derived cache rebuilt
    # periodically rather than updated synchronously on every job/company/
    # skill write (see app/search/indexer.py's module docstring for why).
    # 10 minutes keeps newly-published content searchable soon without
    # reindexing so often it competes for DB time with real traffic.
    search_reindex_interval_minutes: int = 10

    # V10 — with more than one worker process or replica, every one of
    # them would otherwise run its own copy of the background scheduler
    # (app/scheduler.py), causing duplicate ingestion runs and a real
    # risk of duplicate notification rows (two workers can both pass the
    # "already notified?" check before either commits). Set this to
    # false on every worker/replica except one designated "scheduler"
    # instance. Defaults to true because the common case (a single
    # worker) needs no configuration at all.
    scheduler_enabled: bool = True

    # ------------------------------------------------------------------
    # V25.6 — Enterprise Security & Compliance
    # ------------------------------------------------------------------
    # Access tokens carry a session id (``sid``). When true (default), every
    # authenticated request also confirms that session has not been revoked, so
    # logout / "log out this device" / password reset take effect immediately rather
    # than when the 15-minute access token expires. Costs one primary-key lookup per
    # authenticated request; set false only to restore the pre-V25.6 behaviour.
    access_token_session_check: bool = True

    # The shared X-Admin-Key is a break-glass credential with no per-person identity.
    # Leave true for backward compatibility; set false in production once named
    # admin/super_admin accounts exist so every admin action is attributable.
    admin_key_auth_enabled: bool = True

    # /metrics exposes route names and request counts. In production it requires
    # ``Authorization: Bearer <METRICS_TOKEN>``; with no token configured it is
    # disabled (403) in production and open in development.
    metrics_token: str | None = None

    # Career Agent: how long a PENDING_CONFIRMATION action can still be confirmed.
    career_agent_action_ttl_minutes: int = 1440

    # Forgot-password: minimum gap between reset codes for one account.
    password_reset_cooldown_seconds: int = 60

    # Retention (see docs/DATA_RETENTION_AND_DELETION.md). Purging is OPT-IN: nothing is
    # deleted automatically unless RETENTION_PURGE_ENABLED=true and the purge script /
    # job is run. 0 means "keep indefinitely". Audit and security events are never
    # purged by the purge job.
    retention_purge_enabled: bool = False
    retention_auth_artifacts_days: int = 30      # consumed/expired OTP rows, revoked/expired refresh tokens
    retention_notifications_days: int = 365      # read/archived in-app notifications
    retention_email_messages_days: int = 365     # rendered outbound email records
    retention_ai_usage_logs_days: int = 365      # per-call AI usage/cost logs (no prompt text)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @cached_property
    def cors_origins(self) -> list[str]:
        """Parse ``frontend_origin`` into a clean list of origins."""
        return [origin.strip() for origin in self.frontend_origin.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


settings = Settings()
