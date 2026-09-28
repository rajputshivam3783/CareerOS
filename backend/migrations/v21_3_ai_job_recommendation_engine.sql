-- V21.3: AI Job Recommendation Engine.
-- Non-destructive — safe to run against an existing CareerOS database.
-- Adds exactly four new tables (recommendation_preferences,
-- recommendation_feedback, recommendation_snapshots,
-- recommendation_events). Does not alter, rename, or drop jobs, users,
-- skills, applications, saved_jobs, search_index_documents, or any
-- other existing table. See RECOMMENDATION_ARCHITECTURE.md.

CREATE TABLE IF NOT EXISTS recommendation_preferences (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    include_government BOOLEAN NOT NULL DEFAULT TRUE,
    include_private BOOLEAN NOT NULL DEFAULT TRUE,
    include_internships BOOLEAN NOT NULL DEFAULT TRUE,
    include_apprenticeships BOOLEAN NOT NULL DEFAULT TRUE,
    preferred_employment_types TEXT,
    diversity_level VARCHAR(20) NOT NULL DEFAULT 'balanced',
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recommendation_feedback (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    feedback_type VARCHAR(20) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_recommendation_feedback_user_job UNIQUE (user_id, job_id)
);
CREATE INDEX IF NOT EXISTS ix_recommendation_feedback_user_id ON recommendation_feedback (user_id);
CREATE INDEX IF NOT EXISTS ix_recommendation_feedback_job_id ON recommendation_feedback (job_id);
CREATE INDEX IF NOT EXISTS ix_recommendation_feedback_type ON recommendation_feedback (feedback_type);

CREATE TABLE IF NOT EXISTS recommendation_snapshots (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    input_signature VARCHAR(64) NOT NULL,
    results_json TEXT NOT NULL,
    generated_at TIMESTAMP NOT NULL DEFAULT now(),
    expires_at TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_recommendation_snapshots_signature ON recommendation_snapshots (input_signature);

CREATE TABLE IF NOT EXISTS recommendation_events (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    event_type VARCHAR(20) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_recommendation_events_user_id ON recommendation_events (user_id);
CREATE INDEX IF NOT EXISTS ix_recommendation_events_job_id ON recommendation_events (job_id);
CREATE INDEX IF NOT EXISTS ix_recommendation_events_type ON recommendation_events (event_type);
CREATE INDEX IF NOT EXISTS ix_recommendation_events_created_at ON recommendation_events (created_at);
