-- V25.1: Multi-Tenant Architecture & Organization Management.
--
-- Additive only — no historical table is dropped, renamed, or has a
-- column removed. `organizations` (V1/V18.1) gains two new nullable/
-- defaulted columns; three brand-new tables are created. As with every
-- prior migration in this project, Base.metadata.create_all() (the
-- SQLite dev/test path — see app/db/session.py) creates all of this
-- from the current ORM models on a fresh database automatically. This
-- file is for applying the same change to an existing PostgreSQL
-- deployment (see scripts/run_migrations.py).
--
-- After this file is applied, run
-- `python -m scripts.migrate_v25_1_backfill_organizations` once to
-- backfill OrganizationMember rows for every organization that
-- predates V25.1 (see that script's docstring) — this SQL file only
-- creates the schema, it does not populate it.

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
CREATE INDEX IF NOT EXISTS ix_organizations_created_by ON organizations (created_by);
CREATE INDEX IF NOT EXISTS ix_organizations_is_active ON organizations (is_active);

CREATE TABLE IF NOT EXISTS organization_members (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL DEFAULT 'RECRUITER',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    invited_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    joined_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_org_member_org_user UNIQUE (organization_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_org_members_org_status ON organization_members (organization_id, status);
CREATE INDEX IF NOT EXISTS ix_org_members_user ON organization_members (user_id);

CREATE TABLE IF NOT EXISTS organization_invitations (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email VARCHAR(320) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'RECRUITER',
    invited_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    accepted_at TIMESTAMP,
    accepted_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_org_invitations_org_email ON organization_invitations (organization_id, email);
CREATE INDEX IF NOT EXISTS ix_org_invitations_expires ON organization_invitations (expires_at);
CREATE INDEX IF NOT EXISTS ix_org_invitations_token_hash ON organization_invitations (token_hash);

-- No new organization_audit_logs table (spec section 19) — organization
-- events are recorded on the existing, already actor/request-attributed
-- `audit_logs` table (entity_type='organization', entity_id=<org id>)
-- via app.core.audit.log_audit, exactly like every other subsystem's
-- audit events. See app/api/organizations.py's module docstring.
