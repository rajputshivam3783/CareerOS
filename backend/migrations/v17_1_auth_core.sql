-- V17.1: Enterprise Authentication Core.
-- Non-destructive — safe to run against an existing CareerOS database.
-- New columns are nullable and new tables are additive, so existing
-- users/rows created before this migration remain valid as-is.
-- (SQLite/local dev doesn't use this file — see app/db/session.py /
-- app/main.py, which create the same shape via Base.metadata.create_all.)

-- users: duplicate-phone validation support, and recruiter company
-- profile fields captured at registration (previously not stored).
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(32);
ALTER TABLE users ADD COLUMN IF NOT EXISTS company_name VARCHAR(220);
ALTER TABLE users ADD COLUMN IF NOT EXISTS company_website VARCHAR(500);
ALTER TABLE users ADD COLUMN IF NOT EXISTS company_email VARCHAR(320);

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_phone ON users(phone);

-- user_sessions: one row per logged-in device. Parent of a
-- refresh_tokens rotation chain (see below).
CREATE TABLE IF NOT EXISTS user_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id VARCHAR(120) NOT NULL,
    device_label VARCHAR(220),
    ip_address VARCHAR(64),
    user_agent VARCHAR(400),
    remember_me BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_user_sessions_device_id ON user_sessions(device_id);

-- refresh_tokens: hashed refresh tokens, rotated on every use.
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES user_sessions(id) ON DELETE CASCADE,
    token_hash VARCHAR(128) NOT NULL UNIQUE,
    expires_at TIMESTAMP NOT NULL,
    revoked_at TIMESTAMP,
    replaced_by_id INTEGER REFERENCES refresh_tokens(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS ix_refresh_tokens_session_id ON refresh_tokens(session_id);
CREATE INDEX IF NOT EXISTS ix_refresh_tokens_token_hash ON refresh_tokens(token_hash);

-- password_history: previous password hashes, so reset/change can
-- reject immediate reuse. Never used for anything else.
CREATE TABLE IF NOT EXISTS password_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    password_hash VARCHAR(500) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_password_history_user_id ON password_history(user_id);
