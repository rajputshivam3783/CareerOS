-- V2: automated collection run history.
-- Non-destructive — safe to run against an existing CareerOS database.
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id SERIAL PRIMARY KEY,
    source_name VARCHAR(220) NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    discovered INTEGER DEFAULT 0,
    created INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    status VARCHAR(30) DEFAULT 'running',
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS ix_ingestion_runs_source_name ON ingestion_runs(source_name);
CREATE INDEX IF NOT EXISTS ix_ingestion_runs_status ON ingestion_runs(status);
