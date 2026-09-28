-- V18.1: Company module — extends the pre-existing `organizations`
-- table (name/website/verified only, since V1) into a full ATS
-- company profile, and adds branch offices. Non-destructive — safe to
-- run against an existing CareerOS database. `jobs.organization`
-- stays a free-text column; nothing here changes it.

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS slug VARCHAR(220);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS logo_url VARCHAR(1000);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS banner_url VARCHAR(1000);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS industry VARCHAR(120);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS company_size VARCHAR(40);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS founded_year INTEGER;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS location VARCHAR(220);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS linkedin_url VARCHAR(500);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS twitter_url VARCHAR(500);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS facebook_url VARCHAR(500);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS instagram_url VARCHAR(500);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS verification_status VARCHAR(20) DEFAULT 'unverified';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- Backfill verification_status from the pre-existing `verified` bool
-- so rows created before this migration aren't stuck at the default.
UPDATE organizations SET verification_status = 'verified' WHERE verified = TRUE AND verification_status = 'unverified';

CREATE UNIQUE INDEX IF NOT EXISTS ix_organizations_slug ON organizations(slug);
CREATE INDEX IF NOT EXISTS ix_organizations_owner_user_id ON organizations(owner_user_id);
CREATE INDEX IF NOT EXISTS ix_organizations_verification_status ON organizations(verification_status);

CREATE TABLE IF NOT EXISTS company_branches (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    branch_name VARCHAR(220) NOT NULL,
    location VARCHAR(220),
    address TEXT,
    is_headquarters BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_company_branches_organization_id ON company_branches(organization_id);
