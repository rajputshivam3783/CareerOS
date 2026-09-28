-- V0 — Foundational `jobs` table bootstrap.
--
-- BUG FIX (V21.5 stabilization audit): no migration file in this
-- directory ever created the `jobs` table — v1_baseline_schema.sql
-- and v1_safe_upgrade.sql both ALTER it, and v1_safe_upgrade.sql's
-- own comment says it's "a non-destructive compatibility upgrade for
-- an EXISTING CareerOS PostgreSQL database". That was true for every
-- environment migrated forward from before this migrations/ directory
-- existed, but it means scripts/run_migrations.py has never been able
-- to actually bootstrap a genuinely fresh, empty Postgres database —
-- confirmed by actually running it against one: it fails immediately
-- on the very first ALTER TABLE jobs statement it hits, since jobs
-- doesn't exist yet.
--
-- This file adds exactly the columns that were part of the ORIGINAL,
-- pre-migration-history jobs table (i.e., every Job column in
-- app/models/domain.py that no *other* migration file adds via
-- ALTER TABLE jobs ADD COLUMN IF NOT EXISTS — verified by grepping
-- every migrations/*.sql file for that pattern). Every column added
-- later by an existing migration (status, skills, owner_user_id,
-- organization_id, cloned_from_job_id, employment_type, work_mode,
-- industry, experience_required, stipend, duration, admit_card_*,
-- result_*, ad_number, answer_key_url, responsibilities, requirements,
-- benefits, screening_questions, closed_at, archived_at) is
-- deliberately NOT included here — those migrations already add them
-- correctly, in the correct order relative to the tables their
-- foreign keys reference (organization_id references
-- government_organizations, which must exist first — created by
-- v19_1; owner_user_id and cloned_from_job_id likewise reference
-- users/jobs itself, both already guaranteed to exist by the time
-- those later migrations run). Adding them here too would be
-- harmless (IF NOT EXISTS everywhere) but would duplicate, not
-- replace, that existing history.
--
-- Never edit this file after it's been applied to any environment —
-- add a new migration instead (see scripts/run_migrations.py).

CREATE TABLE IF NOT EXISTS jobs (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(180) UNIQUE NOT NULL,
    title VARCHAR(220) NOT NULL,
    organization VARCHAR(220) NOT NULL,
    department VARCHAR(220),
    job_type VARCHAR(40) NOT NULL DEFAULT 'Government',
    govt_level VARCHAR(30),
    category VARCHAR(100),
    location VARCHAR(160) NOT NULL DEFAULT 'India',
    vacancies INTEGER,
    qualification TEXT NOT NULL DEFAULT 'See official notification',
    age_limit VARCHAR(220),
    age_relaxation TEXT,
    application_fee TEXT,
    salary VARCHAR(220),
    pay_level VARCHAR(120),
    start_date DATE,
    deadline DATE,
    exam_date DATE,
    selection_process TEXT,
    description TEXT NOT NULL DEFAULT 'See official notification',
    notification_url VARCHAR(1000),
    official_url VARCHAR(1000),
    apply_url VARCHAR(1000),
    source_name VARCHAR(220),
    source_reference VARCHAR(220),
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Matches app/models/domain.py's Job.title/organization (index=True).
-- slug's UNIQUE constraint above already creates its own index; deadline's
-- index is created separately by v1_safe_upgrade.sql (ix_jobs_deadline).
CREATE INDEX IF NOT EXISTS ix_jobs_title ON jobs(title);
CREATE INDEX IF NOT EXISTS ix_jobs_organization ON jobs(organization);
