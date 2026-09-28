-- V19.1: Government Recruitment Core. Additive only — no existing
-- table is dropped, renamed, or has a column removed. Safe to run
-- against an existing CareerOS database.
--
-- NOTE ON NAMING: `government_organizations` is a NEW table, distinct
-- from the pre-existing `organizations` table (V18.1 Company Module,
-- private-sector recruiter companies). `jobs.organization` remains a
-- free-text column and is NOT backfilled or altered by this
-- migration — organization_id below is purely optional.

CREATE TABLE IF NOT EXISTS government_organizations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(220) NOT NULL,
    short_name VARCHAR(60),
    department VARCHAR(220),
    ministry VARCHAR(220),
    govt_level VARCHAR(30),
    official_website VARCHAR(1000),
    official_career_url VARCHAR(1000),
    official_result_url VARCHAR(1000),
    official_admit_card_url VARCHAR(1000),
    contact_phone VARCHAR(60),
    contact_email VARCHAR(320),
    logo_url VARCHAR(1000),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_government_organizations_name ON government_organizations(name);
CREATE INDEX IF NOT EXISTS ix_government_organizations_short_name ON government_organizations(short_name);
CREATE INDEX IF NOT EXISTS ix_government_organizations_govt_level ON government_organizations(govt_level);
CREATE INDEX IF NOT EXISTS ix_government_organizations_status ON government_organizations(status);

CREATE TABLE IF NOT EXISTS source_registry (
    id SERIAL PRIMARY KEY,
    source_name VARCHAR(220) NOT NULL UNIQUE,
    official_url VARCHAR(1000),
    collector_type VARCHAR(30) NOT NULL DEFAULT 'official_html',
    schedule VARCHAR(60),
    status VARCHAR(20) NOT NULL DEFAULT 'disabled',
    last_run_at TIMESTAMP,
    last_success_at TIMESTAMP,
    error_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_source_registry_source_name ON source_registry(source_name);
CREATE INDEX IF NOT EXISTS ix_source_registry_status ON source_registry(status);

-- jobs: link to government_organizations (nullable — existing rows,
-- and every future Private/Internship/Apprenticeship row, stay
-- organization_id=NULL and keep using jobs.organization as-is) plus
-- two new government-lifecycle fields alongside the existing V7
-- admit_card_url/result_url etc.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS organization_id INTEGER REFERENCES government_organizations(id) ON DELETE SET NULL;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ad_number VARCHAR(120);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS answer_key_url VARCHAR(1000);

CREATE INDEX IF NOT EXISTS ix_jobs_organization_id ON jobs(organization_id);
CREATE INDEX IF NOT EXISTS ix_jobs_ad_number ON jobs(ad_number);

-- recruitment_updates.update_type is a plain VARCHAR (see
-- app.core.constants.RECRUITMENT_UPDATE_TYPES) — no ALTER needed to
-- accept the new V19.1 lifecycle stages (notification,
-- application_open, application_closed, correction_window,
-- city_intimation, objection_window, final_answer_key, score_card,
-- medical, final_selection, completed, cancelled). Validation for
-- these lives in app.api.admin's POST /admin/jobs/{id}/updates only.
