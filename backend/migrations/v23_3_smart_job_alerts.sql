-- V23.3: Smart Job Alerts & Personalized Job Notifications.
--
-- Additive only. Three new tables (job_alerts, job_alert_runs,
-- job_alert_deliveries). No historical migration is modified, no
-- existing table is altered. See docs/V23_3_SMART_JOB_ALERTS.md.
--
-- NOTE: `job_alerts` is intentionally NOT the existing `alerts` table
-- (V7/V19.4 simple saved-search alerts, alert_type='job') — that table
-- keeps working exactly as before. See JobAlert's docstring in
-- app/models/domain.py for why these are deliberately two concepts.

CREATE TABLE IF NOT EXISTS job_alerts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(160) NOT NULL,

    keywords VARCHAR(300),
    job_title VARCHAR(220),
    skills TEXT,
    location VARCHAR(160),
    remote_preference VARCHAR(20),
    employment_type VARCHAR(40),
    experience_level VARCHAR(120),
    salary_min FLOAT,
    salary_max FLOAT,
    job_category VARCHAR(100),
    govt_private_preference VARCHAR(20),
    company VARCHAR(220),
    source VARCHAR(60),

    frequency VARCHAR(20) NOT NULL DEFAULT 'INSTANT',
    min_relevance_score INTEGER,
    use_profile_personalization BOOLEAN NOT NULL DEFAULT FALSE,

    enabled BOOLEAN NOT NULL DEFAULT TRUE,

    last_run_at TIMESTAMP,
    last_run_status VARCHAR(20),
    last_match_count INTEGER NOT NULL DEFAULT 0,

    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_job_alerts_user_id ON job_alerts (user_id);
CREATE INDEX IF NOT EXISTS ix_job_alerts_enabled ON job_alerts (enabled);
CREATE INDEX IF NOT EXISTS ix_job_alerts_frequency ON job_alerts (frequency);
CREATE INDEX IF NOT EXISTS ix_job_alerts_created_at ON job_alerts (created_at);
-- The scheduler's core query: "due, enabled alerts of frequency X" —
-- see app.job_alerts.execution.due_alerts.
CREATE INDEX IF NOT EXISTS ix_job_alerts_enabled_frequency ON job_alerts (enabled, frequency);

CREATE TABLE IF NOT EXISTS job_alert_runs (
    id SERIAL PRIMARY KEY,
    job_alert_id INTEGER NOT NULL REFERENCES job_alerts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    started_at TIMESTAMP NOT NULL DEFAULT now(),
    completed_at TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
    candidates_scanned INTEGER NOT NULL DEFAULT 0,
    jobs_matched INTEGER NOT NULL DEFAULT 0,
    notifications_created INTEGER NOT NULL DEFAULT 0,
    emails_queued INTEGER NOT NULL DEFAULT 0,
    error_summary VARCHAR(500)
);
CREATE INDEX IF NOT EXISTS ix_job_alert_runs_job_alert_id ON job_alert_runs (job_alert_id);
CREATE INDEX IF NOT EXISTS ix_job_alert_runs_user_id ON job_alert_runs (user_id);
CREATE INDEX IF NOT EXISTS ix_job_alert_runs_started_at ON job_alert_runs (started_at);

CREATE TABLE IF NOT EXISTS job_alert_deliveries (
    id SERIAL PRIMARY KEY,
    job_alert_id INTEGER NOT NULL REFERENCES job_alerts(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel VARCHAR(10) NOT NULL,
    relevance_score INTEGER,
    delivered_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_job_alert_delivery_alert_job_channel UNIQUE (job_alert_id, job_id, channel)
);
CREATE INDEX IF NOT EXISTS ix_job_alert_deliveries_job_alert_id ON job_alert_deliveries (job_alert_id);
CREATE INDEX IF NOT EXISTS ix_job_alert_deliveries_job_id ON job_alert_deliveries (job_id);
CREATE INDEX IF NOT EXISTS ix_job_alert_deliveries_user_id ON job_alert_deliveries (user_id);
CREATE INDEX IF NOT EXISTS ix_job_alert_deliveries_delivered_at ON job_alert_deliveries (delivered_at);
