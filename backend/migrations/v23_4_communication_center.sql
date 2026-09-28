-- V23.4: Communication Center, Interview & Deadline Reminders.
--
-- Additive only — no historical migration is modified. Adds exactly
-- one new table (notification_reminders — the reminder engine's own
-- durable idempotency/delivery record; see
-- app.models.domain.NotificationReminder's docstring for why this is
-- a new table rather than a reuse of V19.4's reminder_rules), extends
-- the existing user_notification_preferences table (V19.4/V23.1) with
-- two new columns, and adds a handful of new indexes on existing
-- tables to support this version's background reminder scan without
-- full table scans (spec section 27). See
-- docs/V23_4_COMMUNICATION_CENTER.md.
--
-- Base.metadata.create_all() (SQLite dev path) creates
-- notification_reminders from scratch on a fresh database
-- automatically — the CREATE TABLE below is, as with prior versions'
-- migrations, for an existing PostgreSQL deployment.

CREATE TABLE IF NOT EXISTS notification_reminders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_type VARCHAR(20) NOT NULL,
    source_id INTEGER NOT NULL,
    reminder_type VARCHAR(30) NOT NULL,
    scheduled_for TIMESTAMP NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    priority VARCHAR(10) NOT NULL DEFAULT 'NORMAL',
    notification_id INTEGER REFERENCES notifications(id) ON DELETE SET NULL,
    email_message_id INTEGER REFERENCES email_messages(id) ON DELETE SET NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error VARCHAR(500),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    sent_at TIMESTAMP
);

-- Idempotency (spec sections 6/15): the single constraint that makes
-- a worker retry / server restart / concurrent worker / manual rerun
-- unable to ever produce a duplicate reminder.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_notification_reminders_identity'
    ) THEN
        ALTER TABLE notification_reminders
            ADD CONSTRAINT uq_notification_reminders_identity
            UNIQUE (source_type, source_id, reminder_type, scheduled_for);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_notification_reminders_user_status ON notification_reminders (user_id, status);
CREATE INDEX IF NOT EXISTS ix_notification_reminders_scheduled_for ON notification_reminders (scheduled_for);
CREATE INDEX IF NOT EXISTS ix_notification_reminders_source_type ON notification_reminders (source_type);
CREATE INDEX IF NOT EXISTS ix_notification_reminders_source_id ON notification_reminders (source_id);
CREATE INDEX IF NOT EXISTS ix_notification_reminders_reminder_type ON notification_reminders (reminder_type);

-- Extend the existing preferences table (spec section 13: "Do NOT
-- create duplicate preference tables"). `timezone` defaults 'UTC' —
-- see UserNotificationPreference.timezone's docstring for why this is
-- a safe default rather than requiring a backfill; `digest_enabled`
-- defaults FALSE (opt-in), unlike the always-on email_* columns V23.2
-- added, since a digest is new bundled content nobody has received
-- before this version.
ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) NOT NULL DEFAULT 'UTC';
ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS digest_enabled BOOLEAN NOT NULL DEFAULT FALSE;

-- Supporting indexes for app.communication.reminders' global scans
-- (spec section 27 — avoid full table scans in the background job).
-- (ix_applications_user_applied_on already exists — V22.1.)
CREATE INDEX IF NOT EXISTS ix_applications_deadline_not_null ON applications (deadline);
CREATE INDEX IF NOT EXISTS ix_application_tasks_completed_due_at ON application_tasks (completed, due_at);
CREATE INDEX IF NOT EXISTS ix_application_interviews_result_scheduled_at ON application_interviews (result, scheduled_at);
