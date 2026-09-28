-- V22.4: AI Application Intelligence & Follow-ups.
-- Adds one new cache table for generated AI output. No existing table,
-- migration, or column is modified. See
-- docs/V22_4_AI_APPLICATION_INTELLIGENCE.md.

CREATE TABLE IF NOT EXISTS application_ai_insights (
    id SERIAL PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    kind VARCHAR(40) NOT NULL,          -- narrative / follow_up / interview_prep
    context_key VARCHAR(64) NOT NULL,   -- content hash of the inputs that determine the output
    content_json TEXT NOT NULL,         -- generated output only — never the prompt sent to the model
    provider VARCHAR(30),
    model VARCHAR(80),
    degraded BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_application_ai_insight UNIQUE (application_id, kind, context_key)
);
CREATE INDEX IF NOT EXISTS ix_application_ai_insights_application_id
    ON application_ai_insights (application_id);
CREATE INDEX IF NOT EXISTS ix_application_ai_insights_kind
    ON application_ai_insights (kind);
CREATE INDEX IF NOT EXISTS ix_application_ai_insights_created_at
    ON application_ai_insights (created_at);
