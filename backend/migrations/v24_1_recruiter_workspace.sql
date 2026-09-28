-- V24.1: Recruiter Workspace & Hiring Dashboard.
--
-- Additive only — no historical migration is modified, and no table is
-- duplicated. This version's professional recruiter dashboard, job
-- management, application overview, company and recruiter profile
-- screens are all built on the existing V9/V16/V18.x recruiter/company/
-- applicant schema (jobs.owner_user_id, organizations, applicants,
-- offer_letters, ...). The only schema change genuinely required is a
-- single nullable column so a job's "Published date" (spec section 5)
-- can be shown as a real, distinct fact from `created_at` instead of
-- being inferred.
--
-- Base.metadata.create_all() (SQLite dev path) adds this column from
-- scratch on a fresh database automatically — the ALTER TABLE below is,
-- as with prior versions' migrations, for an existing PostgreSQL
-- deployment.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS published_at TIMESTAMP;

-- Recruiter dashboard/job-management queries filter and sort by
-- owner_user_id + status very frequently (spec sections 3, 5, 6); a
-- composite index keeps that a single index scan instead of a
-- sequential scan as a recruiter's job count grows (spec section 23).
CREATE INDEX IF NOT EXISTS ix_jobs_owner_status ON jobs (owner_user_id, status);
