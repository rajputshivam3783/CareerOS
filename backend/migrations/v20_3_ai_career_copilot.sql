-- V20.3: AI Career Copilot. Additive only — no existing table is
-- dropped, renamed, or has a column removed. Reuses V20.1's
-- ai_conversations/ai_messages/ai_prompt_templates/ai_usage_logs tables
-- as-is for conversation/message/prompt/usage storage — nothing new is
-- needed for those. Only two new tables here.
--
-- SQLite (dev/test) doesn't need this file: Base.metadata.create_all()
-- creates both tables below automatically on a fresh database.

CREATE TABLE IF NOT EXISTS career_preferences (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    target_role VARCHAR(160),
    preferred_industry VARCHAR(160),
    preferred_location VARCHAR(160),
    preferred_work_mode VARCHAR(30),
    experience_level VARCHAR(40),
    target_companies TEXT,
    salary_expectation VARCHAR(120),
    preferred_skills TEXT,
    learning_goals TEXT,
    career_goal TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS career_action_items (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dedupe_key VARCHAR(64) NOT NULL,
    bucket VARCHAR(20) NOT NULL,
    title VARCHAR(300) NOT NULL,
    reason TEXT NOT NULL,
    priority VARCHAR(10) NOT NULL,
    source VARCHAR(30) NOT NULL,
    related_job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    regenerated_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_career_action_item UNIQUE (user_id, dedupe_key)
);
CREATE INDEX IF NOT EXISTS ix_career_action_items_user_id ON career_action_items (user_id);
CREATE INDEX IF NOT EXISTS ix_career_action_items_status ON career_action_items (status);
CREATE INDEX IF NOT EXISTS ix_career_action_items_dedupe_key ON career_action_items (dedupe_key);
