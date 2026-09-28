-- V22.1: Application Tracking Infrastructure.
-- Extends the existing `applications` table (V7 Application OS) —
-- does NOT create a parallel/duplicate application table. Every
-- statement is additive/backward-compatible: ADD COLUMN (nullable, or
-- with a safe default), one-time data backfill, and new indexes. No
-- existing migration file is edited. See
-- docs/V22_1_APPLICATION_TRACKING.md.

-- --- Richer fields (APPLICATION DATA MODEL) ---
ALTER TABLE applications ADD COLUMN IF NOT EXISTS job_title VARCHAR(220);
-- job_title and role hold the same value going forward (see the
-- Application model's own docstring for why role couldn't just be
-- renamed) — backfill so every pre-V22.1 row has both populated.
UPDATE applications SET job_title = role WHERE job_title IS NULL;

ALTER TABLE applications ADD COLUMN IF NOT EXISTS job_url VARCHAR(1000);
ALTER TABLE applications ADD COLUMN IF NOT EXISTS location VARCHAR(160);
ALTER TABLE applications ADD COLUMN IF NOT EXISTS employment_type VARCHAR(60);
ALTER TABLE applications ADD COLUMN IF NOT EXISTS source VARCHAR(60);
ALTER TABLE applications ADD COLUMN IF NOT EXISTS salary VARCHAR(220);
-- Application deadline — distinct from the pre-existing `next_deadline`
-- (the next upcoming *action*, e.g. an interview date).
ALTER TABLE applications ADD COLUMN IF NOT EXISTS deadline DATE;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS recruiter_name VARCHAR(220);
ALTER TABLE applications ADD COLUMN IF NOT EXISTS recruiter_email VARCHAR(255);
ALTER TABLE applications ADD COLUMN IF NOT EXISTS external_reference VARCHAR(120);

ALTER TABLE applications ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMP;
UPDATE applications SET status_updated_at = created_at WHERE status_updated_at IS NULL;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;
UPDATE applications SET updated_at = created_at WHERE updated_at IS NULL;

-- --- Canonical status vocabulary ---
-- SAVED, PLANNING_TO_APPLY, APPLIED, ASSESSMENT, INTERVIEW, OFFER,
-- ACCEPTED, REJECTED, WITHDRAWN, GHOSTED (see app.applications.status
-- for the single source of truth this mirrors). One-time backfill of
-- V7's informal lowercase values into this vocabulary; anything
-- already uppercase/unrecognized is preserved via UPPER() rather than
-- silently dropped.
UPDATE applications SET status = CASE lower(status)
    WHEN 'planned' THEN 'PLANNING_TO_APPLY'
    WHEN 'applied' THEN 'APPLIED'
    WHEN 'interview' THEN 'INTERVIEW'
    WHEN 'offer' THEN 'OFFER'
    WHEN 'rejected' THEN 'REJECTED'
    WHEN 'accepted' THEN 'ACCEPTED'
    WHEN 'withdrawn' THEN 'WITHDRAWN'
    WHEN 'saved' THEN 'SAVED'
    WHEN 'assessment' THEN 'ASSESSMENT'
    WHEN 'ghosted' THEN 'GHOSTED'
    ELSE upper(status)
END;

-- --- Indexes (DATABASE PERFORMANCE) ---
CREATE INDEX IF NOT EXISTS ix_applications_user_status ON applications (user_id, status);
CREATE INDEX IF NOT EXISTS ix_applications_user_created_at ON applications (user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_applications_user_deadline ON applications (user_id, deadline);
CREATE INDEX IF NOT EXISTS ix_applications_user_applied_on ON applications (user_id, applied_on);
-- applications.job_id already indexed since V7 — not re-created here.

-- --- Immutable status history (APPLICATION STATUS HISTORY) ---
CREATE TABLE IF NOT EXISTS application_status_history (
    id SERIAL PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    old_status VARCHAR(50),
    new_status VARCHAR(50) NOT NULL,
    changed_at TIMESTAMP NOT NULL DEFAULT now(),
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_application_status_history_application_id ON application_status_history (application_id);
CREATE INDEX IF NOT EXISTS ix_application_status_history_changed_at ON application_status_history (changed_at);

-- Backfill one "created" history row for every pre-existing
-- application so the journey view is never empty for applications
-- that predate V22.1 — each becomes a single synthetic entry from
-- NULL (unknown prior state) to its current (now-canonical) status,
-- timestamped at the application's own creation time.
INSERT INTO application_status_history (application_id, old_status, new_status, changed_at)
SELECT a.id, NULL, a.status, a.created_at
FROM applications a
WHERE NOT EXISTS (
    SELECT 1 FROM application_status_history h WHERE h.application_id = a.id
);
