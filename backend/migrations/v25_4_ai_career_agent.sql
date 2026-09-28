-- V25.4: Advanced AI Career Agent & Automation.
--
-- Additive only. Four new tables (career_agent_conversations,
-- career_agent_messages, career_agent_actions, career_agent_preferences).
-- No historical migration is modified, no existing table is altered.
-- See docs/V25_4_AI_CAREER_AGENT.md and app/models/domain.py's V25.4
-- section for why these are deliberately NOT the existing
-- ai_conversations/ai_messages tables (V20.1, reused as-is by V20.3
-- Career Copilot).

CREATE TABLE IF NOT EXISTS career_agent_conversations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(200),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_career_agent_conversations_user_id ON career_agent_conversations (user_id);
CREATE INDEX IF NOT EXISTS ix_career_agent_conversations_status ON career_agent_conversations (status);
CREATE INDEX IF NOT EXISTS ix_career_agent_conversations_user_updated ON career_agent_conversations (user_id, updated_at);

CREATE TABLE IF NOT EXISTS career_agent_messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES career_agent_conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    provider VARCHAR(30),
    model VARCHAR(80),
    metadata_json TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_career_agent_messages_conversation_id ON career_agent_messages (conversation_id);
CREATE INDEX IF NOT EXISTS ix_career_agent_messages_created_at ON career_agent_messages (created_at);

CREATE TABLE IF NOT EXISTS career_agent_actions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id INTEGER REFERENCES career_agent_conversations(id) ON DELETE SET NULL,
    action_type VARCHAR(60) NOT NULL,
    risk_level VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING_CONFIRMATION',
    payload_json TEXT NOT NULL,
    result_json TEXT,
    error VARCHAR(500),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    completed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_career_agent_actions_user_id ON career_agent_actions (user_id);
CREATE INDEX IF NOT EXISTS ix_career_agent_actions_action_type ON career_agent_actions (action_type);
CREATE INDEX IF NOT EXISTS ix_career_agent_actions_status ON career_agent_actions (status);
CREATE INDEX IF NOT EXISTS ix_career_agent_actions_user_status ON career_agent_actions (user_id, status);
CREATE INDEX IF NOT EXISTS ix_career_agent_actions_conversation ON career_agent_actions (conversation_id);
CREATE INDEX IF NOT EXISTS ix_career_agent_actions_created_at ON career_agent_actions (created_at);

CREATE TABLE IF NOT EXISTS career_agent_preferences (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    proactive_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    frequency VARCHAR(20) NOT NULL DEFAULT 'daily',
    quiet_hours_start INTEGER,
    quiet_hours_end INTEGER,
    channels VARCHAR(120) NOT NULL DEFAULT 'in_app',
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
