-- V25.6 — Enterprise Security & Compliance.
--
-- This release changes NO existing table or column and drops NOTHING.
--
-- The only DDL is an idempotent CREATE for `failed_job_records` (introduced in V25.5 as a
-- SQLAlchemy model). V25.5 shipped without a SQL migration, so production databases only
-- received the table through `Base.metadata.create_all` at application start-up; this file
-- makes the schema reproducible from the migration set alone (audit finding F-19). It is a
-- no-op on any database where the table already exists.

CREATE TABLE IF NOT EXISTS failed_job_records (
    id SERIAL PRIMARY KEY,
    job_name VARCHAR(120) NOT NULL,
    idempotency_key VARCHAR(200) NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'pending_retry',
    failure_reason TEXT NOT NULL DEFAULT '',
    retry_count INTEGER NOT NULL DEFAULT 0,
    first_failed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_attempt_at TIMESTAMP NOT NULL DEFAULT NOW(),
    next_retry_at TIMESTAMP,
    resolved_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_failed_job_records_job_name ON failed_job_records (job_name);
CREATE INDEX IF NOT EXISTS ix_failed_job_records_status ON failed_job_records (status);
CREATE INDEX IF NOT EXISTS ix_failed_job_records_job_status ON failed_job_records (job_name, status);
CREATE INDEX IF NOT EXISTS ix_failed_job_records_idempotency ON failed_job_records (job_name, idempotency_key);
