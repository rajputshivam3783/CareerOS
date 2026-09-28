-- V24.4: Recruiter Analytics & AI Hiring Intelligence.
--
-- One new cache table only — no historical migration modified, no
-- existing table duplicated. Every deterministic analytic in this
-- version is *derived* at query time from tables that already exist
-- (applicants, recruiter_pipeline_history, jobs, interviews,
-- offer_letters) — see docs/V24_4_RECRUITER_ANALYTICS_AI.md
-- "Analytics data sources". The only thing that needs its own storage
-- is the AI-output cache, same content-hash design as V22.4's
-- application_ai_insights.
--
-- Base.metadata.create_all() (SQLite dev path) creates this table
-- from scratch on a fresh database automatically — the statement
-- below is, as with prior versions' migrations, for an existing
-- PostgreSQL deployment.

CREATE TABLE IF NOT EXISTS recruiter_ai_insights (
    id SERIAL PRIMARY KEY,
    scope_type VARCHAR(20) NOT NULL,
    scope_id INTEGER NOT NULL,
    kind VARCHAR(40) NOT NULL,
    context_key VARCHAR(64) NOT NULL,
    content_json TEXT NOT NULL,
    provider VARCHAR(30),
    model VARCHAR(60),
    degraded BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_recruiter_ai_insight UNIQUE (scope_type, scope_id, kind, context_key)
);

CREATE INDEX IF NOT EXISTS ix_recruiter_ai_insights_scope_type ON recruiter_ai_insights (scope_type);
CREATE INDEX IF NOT EXISTS ix_recruiter_ai_insights_scope_id ON recruiter_ai_insights (scope_id);
CREATE INDEX IF NOT EXISTS ix_recruiter_ai_insights_kind ON recruiter_ai_insights (kind);
CREATE INDEX IF NOT EXISTS ix_recruiter_ai_insights_context_key ON recruiter_ai_insights (context_key);
CREATE INDEX IF NOT EXISTS ix_recruiter_ai_insights_created_at ON recruiter_ai_insights (created_at);
