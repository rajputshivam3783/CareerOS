-- V24.2: Advanced Candidate Discovery & Search.
--
-- Additive only — no historical migration is modified, and no table
-- (users/candidates/profiles/resumes/jobs/applications) is duplicated.
-- Candidate discovery is built entirely on existing tables (users,
-- profiles, resumes, applicants, career_preferences, user_sessions);
-- the only schema change genuinely required is a single opt-in
-- visibility flag, since no candidate-discoverability preference
-- existed anywhere in the system before this version (spec section
-- 17 only asks for one if none already exists).
--
-- Base.metadata.create_all() (SQLite dev path) adds this column from
-- scratch on a fresh database automatically — the ALTER TABLE below
-- is, as with prior versions' migrations, for an existing PostgreSQL
-- deployment.

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS candidate_searchable BOOLEAN NOT NULL DEFAULT false;

-- Every recruiter candidate-discovery query filters on this flag to
-- find the opted-in pool (spec sections 2, 21: never scan the whole
-- candidate base) — index it so that's an index scan, not a
-- sequential scan, as the candidate base grows.
CREATE INDEX IF NOT EXISTS ix_profiles_candidate_searchable ON profiles (candidate_searchable);
