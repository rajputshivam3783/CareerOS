-- V24.3: Candidate Pipeline & Hiring Workflow.
--
-- Additive + one data migration — no historical migration is modified,
-- and no table (users/recruiters/companies/jobs/applications/candidate
-- profiles/interviews/notifications) is duplicated. Builds entirely on
-- the existing V9/V16/V18.2 `applicants`/`applicant_notes`/`interviews`/
-- `offer_letters` tables (spec section 26).
--
-- Base.metadata.create_all() (SQLite dev path) creates the new table
-- and column from scratch on a fresh database automatically — the
-- statements below are, as with prior versions' migrations, for an
-- existing PostgreSQL deployment.

-- 1. Recruiter-side, immutable pipeline-stage history (spec section 7).
--    Deliberately separate from `application_status_history`, which
--    tracks the candidate-owned `applications.status` — see
--    RecruiterPipelineHistory's docstring.
CREATE TABLE IF NOT EXISTS recruiter_pipeline_history (
    id SERIAL PRIMARY KEY,
    applicant_id INTEGER NOT NULL REFERENCES applicants(id) ON DELETE CASCADE,
    old_stage VARCHAR(30),
    new_stage VARCHAR(30) NOT NULL,
    changed_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    changed_at TIMESTAMP NOT NULL DEFAULT now(),
    direction VARCHAR(20),
    reason TEXT
);

CREATE INDEX IF NOT EXISTS ix_recruiter_pipeline_history_applicant_id_changed_at
    ON recruiter_pipeline_history (applicant_id, changed_at);
CREATE INDEX IF NOT EXISTS ix_recruiter_pipeline_history_new_stage
    ON recruiter_pipeline_history (new_stage);

-- 2. hired_at (spec section 14) — set once by the application layer
--    the first time pipeline_stage becomes 'hired'; this migration
--    only adds the column.
ALTER TABLE applicants ADD COLUMN IF NOT EXISTS hired_at TIMESTAMP;

-- 3. Rename the V18.2 pipeline_stage vocabulary to the V24.3 canonical
--    hiring-workflow names (see app.core.constants.LEGACY_PIPELINE_STAGE_MAP
--    and PIPELINE_STAGES's docstring for why). Existing NULL values
--    (never explicitly set) are left NULL — the application layer
--    already treats NULL as the first stage ("new").
UPDATE applicants SET pipeline_stage = 'new'         WHERE pipeline_stage = 'applied';
UPDATE applicants SET pipeline_stage = 'reviewing'    WHERE pipeline_stage = 'screening';
UPDATE applicants SET pipeline_stage = 'assessment'   WHERE pipeline_stage IN ('technical_round', 'hr_round');
UPDATE applicants SET pipeline_stage = 'hired'        WHERE pipeline_stage = 'accepted';
-- 'shortlisted', 'interview', 'offer', 'rejected', 'withdrawn' are
-- already spelled the same way in both vocabularies — no rewrite
-- needed for those rows.

ALTER TABLE applicants ALTER COLUMN pipeline_stage SET DEFAULT 'new';

-- Backfill hired_at for any applicant this migration just renamed (or
-- that already had 'hired'/'accepted') so the column isn't silently
-- empty for candidates hired before V24.3 shipped. Best-effort only:
-- there's no historical stage-change timestamp to draw on before this
-- version, so `updated_at` (the last time the row changed at all) is
-- used as a documented approximation — see docs/V24_3_CANDIDATE_PIPELINE.md,
-- "Known limitations".
UPDATE applicants SET hired_at = updated_at WHERE pipeline_stage = 'hired' AND hired_at IS NULL;

-- 4. One-time backfill: give every existing applicant an initial
--    pipeline-history row so "complete candidate hiring history" (spec
--    section 7) doesn't start empty for applicants that predate this
--    version. `old_stage` is NULL (no prior stage is known) and
--    `changed_by_user_id` is NULL (no actor is known for a backfilled
--    row); `direction` is 'initial'.
INSERT INTO recruiter_pipeline_history (applicant_id, old_stage, new_stage, changed_by_user_id, changed_at, direction, reason)
SELECT a.id, NULL, COALESCE(a.pipeline_stage, 'new'), NULL, a.created_at, 'initial', 'Backfilled by the V24.3 migration'
FROM applicants a
WHERE NOT EXISTS (SELECT 1 FROM recruiter_pipeline_history h WHERE h.applicant_id = a.id);
