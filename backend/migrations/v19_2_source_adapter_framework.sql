-- V19.2: Official Source Adapter Framework. Additive only — no
-- existing table is dropped, renamed, or has a column removed. Safe
-- to run against an existing CareerOS database (including one that
-- has never run V19.1's migration against source_registry rows yet).

ALTER TABLE source_registry ADD COLUMN IF NOT EXISTS last_failure_at TIMESTAMP;
ALTER TABLE source_registry ADD COLUMN IF NOT EXISTS organization VARCHAR(220);
ALTER TABLE source_registry ADD COLUMN IF NOT EXISTS govt_level VARCHAR(30);
ALTER TABLE source_registry ADD COLUMN IF NOT EXISTS category VARCHAR(120);
ALTER TABLE source_registry ADD COLUMN IF NOT EXISTS config TEXT;
ALTER TABLE source_registry ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 100;
ALTER TABLE source_registry ADD COLUMN IF NOT EXISTS last_latency_ms INTEGER;
ALTER TABLE source_registry ADD COLUMN IF NOT EXISTS availability_pct DOUBLE PRECISION;
ALTER TABLE source_registry ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE source_registry ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0;
ALTER TABLE source_registry ADD COLUMN IF NOT EXISTS circuit_state VARCHAR(20) NOT NULL DEFAULT 'closed';
ALTER TABLE source_registry ADD COLUMN IF NOT EXISTS circuit_opened_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS ix_source_registry_priority ON source_registry(priority);
CREATE INDEX IF NOT EXISTS ix_source_registry_circuit_state ON source_registry(circuit_state);

CREATE TABLE IF NOT EXISTS ingestion_run_logs (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    source_name VARCHAR(220) NOT NULL,
    level VARCHAR(10) NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_ingestion_run_logs_run_id ON ingestion_run_logs(run_id);
CREATE INDEX IF NOT EXISTS ix_ingestion_run_logs_source_name ON ingestion_run_logs(source_name);
CREATE INDEX IF NOT EXISTS ix_ingestion_run_logs_created_at ON ingestion_run_logs(created_at);

CREATE TABLE IF NOT EXISTS ingestion_dead_letters (
    id SERIAL PRIMARY KEY,
    source_name VARCHAR(220) NOT NULL,
    run_id INTEGER REFERENCES ingestion_runs(id) ON DELETE SET NULL,
    payload TEXT NOT NULL,
    error TEXT NOT NULL,
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_ingestion_dead_letters_source_name ON ingestion_dead_letters(source_name);
CREATE INDEX IF NOT EXISTS ix_ingestion_dead_letters_created_at ON ingestion_dead_letters(created_at);

-- recruitment_updates (V14/V16, unchanged table) already has every
-- column app.ingestion.services.change_detection needs — no ALTER
-- required. update_type is a plain VARCHAR validated against
-- app.core.constants.RECRUITMENT_UPDATE_TYPES, which already includes
-- result/admit_card/answer_key/cancelled/notification etc.
