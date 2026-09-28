-- CareerOS V14 Government Recruitment Hub
CREATE TABLE IF NOT EXISTS recruitment_updates (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    update_type VARCHAR(40) NOT NULL,
    title VARCHAR(300) NOT NULL,
    event_date DATE NULL,
    source_url VARCHAR(1000) NULL,
    official BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(30) NOT NULL DEFAULT 'published',
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_recruitment_update_source UNIQUE(job_id, update_type, source_url)
);
CREATE INDEX IF NOT EXISTS ix_recruitment_updates_job_id ON recruitment_updates(job_id);
CREATE INDEX IF NOT EXISTS ix_recruitment_updates_update_type ON recruitment_updates(update_type);
CREATE INDEX IF NOT EXISTS ix_recruitment_updates_event_date ON recruitment_updates(event_date);
CREATE INDEX IF NOT EXISTS ix_recruitment_updates_status ON recruitment_updates(status);
