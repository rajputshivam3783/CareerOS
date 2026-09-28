-- V19.4: Government Automation & Notification Engine. Additive only —
-- no existing table is dropped, renamed, or has a column removed.
-- Safe to run against an existing CareerOS database.
--
-- SQLite (dev/test) doesn't need this file: Base.metadata.create_all()
-- creates every new table below automatically on a fresh database. It
-- does NOT add new columns to an existing table, though — which is
-- why `notifications.archived` is still listed here explicitly, for
-- an existing Postgres deployment that already has a `notifications`
-- table from V7.

ALTER TABLE notifications ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS ix_notifications_archived ON notifications (archived);

CREATE TABLE IF NOT EXISTS subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subscription_type VARCHAR(30) NOT NULL,
    value VARCHAR(220),
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_subscription UNIQUE (user_id, subscription_type, value, job_id)
);
CREATE INDEX IF NOT EXISTS ix_subscriptions_user_id ON subscriptions (user_id);
CREATE INDEX IF NOT EXISTS ix_subscriptions_subscription_type ON subscriptions (subscription_type);
CREATE INDEX IF NOT EXISTS ix_subscriptions_job_id ON subscriptions (job_id);

CREATE TABLE IF NOT EXISTS user_notification_preferences (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    email_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    in_app_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    category_preferences TEXT,
    organization_preferences TEXT,
    quiet_hours_start INTEGER,
    quiet_hours_end INTEGER,
    digest_mode VARCHAR(20) NOT NULL DEFAULT 'instant',
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reminder_rules (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    reminder_type VARCHAR(30) NOT NULL,
    target_date DATE NOT NULL,
    offset_days INTEGER NOT NULL DEFAULT 0,
    fire_date DATE NOT NULL,
    auto_created BOOLEAN NOT NULL DEFAULT TRUE,
    fired_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_reminder_rules_user_id ON reminder_rules (user_id);
CREATE INDEX IF NOT EXISTS ix_reminder_rules_job_id ON reminder_rules (job_id);
CREATE INDEX IF NOT EXISTS ix_reminder_rules_reminder_type ON reminder_rules (reminder_type);
CREATE INDEX IF NOT EXISTS ix_reminder_rules_target_date ON reminder_rules (target_date);
CREATE INDEX IF NOT EXISTS ix_reminder_rules_fire_date ON reminder_rules (fire_date);

CREATE TABLE IF NOT EXISTS notification_templates (
    id SERIAL PRIMARY KEY,
    key VARCHAR(60) NOT NULL,
    channel VARCHAR(20) NOT NULL,
    subject VARCHAR(300),
    body TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_notification_template UNIQUE (key, channel)
);
CREATE INDEX IF NOT EXISTS ix_notification_templates_key ON notification_templates (key);

CREATE TABLE IF NOT EXISTS notification_delivery_log (
    id SERIAL PRIMARY KEY,
    notification_id INTEGER REFERENCES notifications(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    provider VARCHAR(40),
    error TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    sent_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_notification_delivery_log_notification_id ON notification_delivery_log (notification_id);
CREATE INDEX IF NOT EXISTS ix_notification_delivery_log_user_id ON notification_delivery_log (user_id);
CREATE INDEX IF NOT EXISTS ix_notification_delivery_log_channel ON notification_delivery_log (channel);
CREATE INDEX IF NOT EXISTS ix_notification_delivery_log_status ON notification_delivery_log (status);

CREATE TABLE IF NOT EXISTS automation_cursors (
    trigger VARCHAR(60) PRIMARY KEY,
    last_id INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS automation_logs (
    id SERIAL PRIMARY KEY,
    trigger VARCHAR(60) NOT NULL,
    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    notifications_created INTEGER NOT NULL DEFAULT 0,
    detail TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_automation_logs_trigger ON automation_logs (trigger);
