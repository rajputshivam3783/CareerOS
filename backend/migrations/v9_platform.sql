-- V9: Platform — recruiter accounts + applicant pipeline.
-- Non-destructive — safe to run against an existing CareerOS database.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_jobs_owner_user_id ON jobs(owner_user_id);

CREATE TABLE IF NOT EXISTS applicants (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    cover_note TEXT,
    resume_snapshot TEXT,
    status VARCHAR(30) DEFAULT 'submitted',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_applicant_job_user UNIQUE (job_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_applicants_job_id ON applicants(job_id);
CREATE INDEX IF NOT EXISTS ix_applicants_user_id ON applicants(user_id);
CREATE INDEX IF NOT EXISTS ix_applicants_status ON applicants(status);
