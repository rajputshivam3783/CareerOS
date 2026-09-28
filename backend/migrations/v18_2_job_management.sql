-- V18.2: Recruiter ATS — professional job wizard fields, draft/clone/
-- archive lifecycle, and a Kanban pipeline stage for applicants.
-- Non-destructive — safe to run against an existing CareerOS database.
-- Does not touch Authentication, Security, Government Hub, AI, Search,
-- Notifications, Analytics, or the `jobs.status` values already relied
-- on by ingestion/admin review (review/published/rejected).

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS responsibilities TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS requirements TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS skills TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS benefits TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS screening_questions TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS cloned_from_job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS ix_jobs_cloned_from_job_id ON jobs(cloned_from_job_id);

-- Kanban pipeline stage — a richer, recruiter-facing view of where a
-- candidate sits (Applied/Shortlisted/Screening/Interview/Technical
-- Round/HR Round/Offer/Accepted/Rejected/Withdrawn) than the simpler
-- `status` column other parts of the app (candidate-facing views,
-- notifications) already read. Kept as a separate column so nothing
-- that depends on the existing `status` vocabulary breaks.
ALTER TABLE applicants ADD COLUMN IF NOT EXISTS pipeline_stage VARCHAR(30);
CREATE INDEX IF NOT EXISTS ix_applicants_pipeline_stage ON applicants(pipeline_stage);

-- Backfill pipeline_stage for existing rows from their current status.
UPDATE applicants SET pipeline_stage = CASE status
    WHEN 'submitted' THEN 'applied'
    WHEN 'shortlisted' THEN 'shortlisted'
    WHEN 'interview' THEN 'interview'
    WHEN 'rejected' THEN 'rejected'
    WHEN 'hired' THEN 'accepted'
    ELSE 'applied'
END
WHERE pipeline_stage IS NULL;
