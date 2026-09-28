-- V23.2: Email Notification & Template Engine.
--
-- Additive only. Three new tables (system_email_templates,
-- email_messages, email_delivery_attempts) and 7 new columns on the
-- existing user_notification_preferences table (V19.4/V23.1). No
-- historical migration is modified. See docs/V23_2_EMAIL_SYSTEM.md.
--
-- NOTE: `system_email_templates` is intentionally NOT named
-- `email_templates` — that table already exists (V18.5, recruiter-
-- owned per-company ATS templates) and is a different concept. See
-- SystemEmailTemplate's docstring in app/models/domain.py.

CREATE TABLE IF NOT EXISTS system_email_templates (
    id SERIAL PRIMARY KEY,
    template_key VARCHAR(50) NOT NULL UNIQUE,
    subject VARCHAR(300) NOT NULL,
    html_body TEXT NOT NULL,
    text_body TEXT NOT NULL,
    variables_json TEXT NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 1,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS email_messages (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    template_key VARCHAR(50) NOT NULL,
    recipient VARCHAR(255) NOT NULL,
    subject VARCHAR(300) NOT NULL,
    variables_json TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'QUEUED',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 4,
    scheduled_at TIMESTAMP NOT NULL DEFAULT now(),
    sent_at TIMESTAMP,
    failed_at TIMESTAMP,
    last_error VARCHAR(500),
    dedupe_key VARCHAR(150),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_email_messages_user_dedupe_key UNIQUE (user_id, dedupe_key)
);
CREATE INDEX IF NOT EXISTS ix_email_messages_user_id ON email_messages (user_id);
CREATE INDEX IF NOT EXISTS ix_email_messages_template_key ON email_messages (template_key);
CREATE INDEX IF NOT EXISTS ix_email_messages_status ON email_messages (status);
CREATE INDEX IF NOT EXISTS ix_email_messages_scheduled_at ON email_messages (scheduled_at);
CREATE INDEX IF NOT EXISTS ix_email_messages_created_at ON email_messages (created_at);
-- The queue worker's core query: "due QUEUED/RETRYING rows" — see
-- app.email.service.process_queue.
CREATE INDEX IF NOT EXISTS ix_email_messages_status_scheduled_at ON email_messages (status, scheduled_at);

CREATE TABLE IF NOT EXISTS email_delivery_attempts (
    id SERIAL PRIMARY KEY,
    email_message_id INTEGER NOT NULL REFERENCES email_messages(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL,
    provider VARCHAR(20) NOT NULL,
    error VARCHAR(500),
    occurred_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_email_delivery_attempts_email_message_id ON email_delivery_attempts (email_message_id);
CREATE INDEX IF NOT EXISTS ix_email_delivery_attempts_occurred_at ON email_delivery_attempts (occurred_at);

ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS email_job BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS email_application BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS email_interview BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS email_deadline BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS email_recruiter BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS email_ai BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS email_system BOOLEAN NOT NULL DEFAULT TRUE;
