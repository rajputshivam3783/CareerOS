-- V25.2: Advanced Admin & Platform Governance.
--
-- Additive only. No table is dropped or renamed, no column is removed
-- or retyped, and every new column is nullable or carries a default,
-- so every row written by V1-V25.1 stays valid with no backfill.
--
-- As with every prior migration in this project, Base.metadata.create_all()
-- (the SQLite dev/test path — see app/db/session.py) creates all of this
-- from the current ORM models on a fresh database automatically. This
-- file applies the same change to an existing PostgreSQL deployment
-- (see scripts/run_migrations.py).
--
-- Deliberately NOT created here:
--   * a `security_events` table — security events reuse the existing
--     `audit_logs` table through app.core.security_events (V17.2), so
--     an investigator queries one place, not two (spec section 28's
--     "avoid duplicate audit systems").
--   * per-resource admin history tables — user/organization/job admin
--     history is a filtered read of `platform_audit_logs` below
--     (spec section 12).
--   * any ingestion or background-job table — sections 17/18 are served
--     entirely by the already-durable ingestion_runs / ingestion_run_logs /
--     source_registry / automation_logs / email_messages rows.

-- ---------------------------------------------------------------------
-- 1. Existing tables gain lifecycle / moderation columns.
-- ---------------------------------------------------------------------

-- Platform account lifecycle. `active` remains the flag every
-- authentication path checks; this column makes the lifecycle
-- explicit and queryable. Defaulting every existing row to 'ACTIVE' is
-- correct for the overwhelming majority, and the API never trusts this
-- column blindly for pre-V25.2 rows — app.core.platform_lifecycle.
-- derive_account_status() derives the label from `active` +
-- `suspended_at`, so an account deactivated before this column existed
-- is still reported honestly rather than as ACTIVE.
ALTER TABLE users ADD COLUMN IF NOT EXISTS account_status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE';
CREATE INDEX IF NOT EXISTS ix_users_account_status ON users (account_status);

-- Organization platform lifecycle. Same relationship to the
-- pre-existing `is_active` flag (V25.1) as above.
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMP;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS suspension_reason VARCHAR(500);
CREATE INDEX IF NOT EXISTS ix_organizations_status ON organizations (status);

-- Job moderation annotations on the EXISTING review workflow. No new
-- status column: "suspended" is a new *value* of jobs.status, which is
-- already a plain VARCHAR — the same pattern V14/V16 used to add role
-- and update_type values without a migration. That is what makes every
-- existing `WHERE status = 'published'` query exclude suspended jobs
-- automatically.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS moderation_reason VARCHAR(40);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS moderation_note TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS moderated_at TIMESTAMP;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS moderated_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS pre_moderation_status VARCHAR(30);
CREATE INDEX IF NOT EXISTS ix_jobs_moderation_reason ON jobs (moderation_reason);
-- The moderation queue's hot path: "everything in state X, newest
-- first". Without this, the queue degrades to a sequential scan as the
-- jobs table grows (spec section 33).
CREATE INDEX IF NOT EXISTS ix_jobs_status_created ON jobs (status, created_at DESC);

-- ---------------------------------------------------------------------
-- 2. platform_audit_logs — the append-only governance trail.
--
-- APPEND-ONLY is enforced at the application layer: app.core.
-- platform_audit.record_platform_action is the only writer anywhere in
-- the codebase, and no UPDATE or DELETE statement against this table
-- exists in any route, service or script. A deployment that wants the
-- guarantee enforced by the database as well should grant the
-- application's database role INSERT and SELECT only on this table --
-- see docs/V25_2_ADMIN_PLATFORM_GOVERNANCE.md, which documents that
-- hardening step and the data-retention exception it leaves open.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS platform_audit_logs (
    id SERIAL PRIMARY KEY,
    action VARCHAR(60) NOT NULL,
    target_type VARCHAR(40) NOT NULL,
    target_id VARCHAR(120),
    organization_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_type VARCHAR(20) NOT NULL DEFAULT 'user',
    actor_label VARCHAR(160),
    reason VARCHAR(60),
    note TEXT,
    metadata_json TEXT,
    result VARCHAR(20) NOT NULL DEFAULT 'success',
    request_id VARCHAR(64),
    ip_address VARCHAR(64),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
-- One index per filter the /admin/audit investigation UI exposes, so
-- none of them degrades to a table scan.
CREATE INDEX IF NOT EXISTS ix_platform_audit_action ON platform_audit_logs (action);
CREATE INDEX IF NOT EXISTS ix_platform_audit_target ON platform_audit_logs (target_type, target_id);
CREATE INDEX IF NOT EXISTS ix_platform_audit_actor ON platform_audit_logs (actor_user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_platform_audit_action_created ON platform_audit_logs (action, created_at);
CREATE INDEX IF NOT EXISTS ix_platform_audit_org ON platform_audit_logs (organization_id);
CREATE INDEX IF NOT EXISTS ix_platform_audit_created ON platform_audit_logs (created_at);
CREATE INDEX IF NOT EXISTS ix_platform_audit_request ON platform_audit_logs (request_id);
CREATE INDEX IF NOT EXISTS ix_platform_audit_result ON platform_audit_logs (result);

-- ---------------------------------------------------------------------
-- 3. platform_settings — typed overrides only.
--
-- NOT a generic JSON blob (spec section 19 forbids one): the catalog of
-- which keys exist, their types, defaults and bounds lives in code, in
-- app.core.platform_settings.SETTING_DEFINITIONS. This table stores the
-- overrides an administrator has actually made, each tagged with its
-- declared type, which is re-validated on every read — so a row
-- hand-edited to a nonsense value degrades to the code-side default
-- rather than reaching a caller.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS platform_settings (
    id SERIAL PRIMARY KEY,
    key VARCHAR(80) NOT NULL UNIQUE,
    value_json TEXT NOT NULL,
    value_type VARCHAR(20) NOT NULL,
    updated_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_platform_settings_key ON platform_settings (key);

-- ---------------------------------------------------------------------
-- 4. platform_announcements — intent + delivery state.
--
-- Not a notification system: delivery goes through the existing V23.1
-- in-app notification service and V23.2 email queue (spec section 21).
-- A row is created in DRAFT and delivers nothing; sending is a
-- separate, separately-audited request.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS platform_announcements (
    id SERIAL PRIMARY KEY,
    title VARCHAR(220) NOT NULL,
    message TEXT NOT NULL,
    audience VARCHAR(30) NOT NULL DEFAULT 'ALL',
    channel VARCHAR(10) NOT NULL DEFAULT 'IN_APP',
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    scheduled_for TIMESTAMP,
    sent_at TIMESTAMP,
    recipient_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_platform_announcements_status ON platform_announcements (status);
CREATE INDEX IF NOT EXISTS ix_platform_announcements_audience ON platform_announcements (audience);

-- ---------------------------------------------------------------------
-- 5. Supporting index for the security-events screen, which filters the
--    existing audit_logs table by action + recency.
-- ---------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS ix_audit_logs_action_created ON audit_logs (action, created_at);
