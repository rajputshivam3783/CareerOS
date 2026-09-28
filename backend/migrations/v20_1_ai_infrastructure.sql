-- V20.1: AI Infrastructure & LLM Framework. Additive only — no existing
-- table is dropped, renamed, or has a column removed. Safe to run against
-- an existing CareerOS database.
--
-- SQLite (dev/test) doesn't need this file: Base.metadata.create_all()
-- creates every table below automatically on a fresh database, exactly
-- like every prior version's migration note.

CREATE TABLE IF NOT EXISTS ai_conversations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    session_key VARCHAR(120) NOT NULL,
    title VARCHAR(200),
    context_type VARCHAR(60),
    summary TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ai_conversations_user_id ON ai_conversations (user_id);
CREATE INDEX IF NOT EXISTS ix_ai_conversations_session_key ON ai_conversations (session_key);
CREATE INDEX IF NOT EXISTS ix_ai_conversations_context_type ON ai_conversations (context_type);

CREATE TABLE IF NOT EXISTS ai_messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    provider VARCHAR(30),
    model VARCHAR(80),
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ai_messages_conversation_id ON ai_messages (conversation_id);
CREATE INDEX IF NOT EXISTS ix_ai_messages_created_at ON ai_messages (created_at);

CREATE TABLE IF NOT EXISTS ai_prompt_templates (
    id SERIAL PRIMARY KEY,
    key VARCHAR(80) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    template TEXT NOT NULL,
    variables TEXT,
    description VARCHAR(300),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_ai_prompt_template_version UNIQUE (key, version)
);
CREATE INDEX IF NOT EXISTS ix_ai_prompt_templates_key ON ai_prompt_templates (key);

CREATE TABLE IF NOT EXISTS ai_usage_logs (
    id SERIAL PRIMARY KEY,
    service VARCHAR(40) NOT NULL,
    operation VARCHAR(60),
    provider VARCHAR(30) NOT NULL,
    model VARCHAR(80),
    used_fallback BOOLEAN NOT NULL DEFAULT FALSE,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_estimate_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ai_usage_logs_service ON ai_usage_logs (service);
CREATE INDEX IF NOT EXISTS ix_ai_usage_logs_provider ON ai_usage_logs (provider);
CREATE INDEX IF NOT EXISTS ix_ai_usage_logs_success ON ai_usage_logs (success);
CREATE INDEX IF NOT EXISTS ix_ai_usage_logs_created_at ON ai_usage_logs (created_at);
