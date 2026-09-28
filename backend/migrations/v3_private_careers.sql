-- V3: private careers, internships, apprenticeships.
-- Non-destructive — safe to run against an existing CareerOS database.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS employment_type VARCHAR(40);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS work_mode VARCHAR(20);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS industry VARCHAR(120);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS experience_required VARCHAR(120);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS stipend VARCHAR(220);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS duration VARCHAR(120);
CREATE INDEX IF NOT EXISTS ix_jobs_employment_type ON jobs(employment_type);

CREATE TABLE IF NOT EXISTS partners (
    id SERIAL PRIMARY KEY,
    name VARCHAR(220) UNIQUE NOT NULL,
    contact_email VARCHAR(320) NOT NULL,
    api_key_hash VARCHAR(500) NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
