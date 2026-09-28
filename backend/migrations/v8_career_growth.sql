-- V8: Career Growth — resumes + curated exam-prep resources.
-- Non-destructive — safe to run against an existing CareerOS database.

CREATE TABLE IF NOT EXISTS resumes (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    original_filename VARCHAR(320) NOT NULL,
    extracted_text TEXT NOT NULL,
    skills_detected TEXT,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exam_prep_resources (
    id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    organization VARCHAR(220) NOT NULL,
    exam_name VARCHAR(220) NOT NULL,
    resource_type VARCHAR(30) NOT NULL,
    title VARCHAR(220) NOT NULL,
    url VARCHAR(1000) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_exam_prep_job_id ON exam_prep_resources(job_id);
CREATE INDEX IF NOT EXISTS ix_exam_prep_organization ON exam_prep_resources(organization);
