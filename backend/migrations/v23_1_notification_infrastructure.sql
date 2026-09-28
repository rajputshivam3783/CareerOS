-- V23.1: Notification Infrastructure & Event System.
--
-- Additive only — no historical migration is modified. Extends the
-- existing `notifications` table (V7, already extended once by V19.4
-- with `archived`) with new nullable/safely-defaulted columns rather
-- than creating a second notifications table, and extends the
-- existing `user_notification_preferences` table (V19.4) with 7 new
-- per-category boolean toggles. See
-- docs/V23_1_NOTIFICATION_INFRASTRUCTURE.md.
--
-- Base.metadata.create_all() (SQLite dev path) creates every table
-- below from scratch on a fresh database automatically — these
-- ALTER TABLE statements are, as with V19.4's `archived` column,
-- for an existing PostgreSQL deployment that already has these two
-- tables from an earlier version.

ALTER TABLE notifications ADD COLUMN IF NOT EXISTS category VARCHAR(20);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS priority VARCHAR(10) NOT NULL DEFAULT 'NORMAL';
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS read_at TIMESTAMP;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS action_url VARCHAR(300);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS metadata_json TEXT;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT now();
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(150);

-- Idempotency: one (user_id, dedupe_key) pair can exist at most once.
-- Multiple NULLs are always allowed under a UNIQUE constraint in both
-- PostgreSQL and SQLite, so every pre-V23.1 row (NULL dedupe_key)
-- never collides with anything.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_notifications_user_dedupe_key'
    ) THEN
        ALTER TABLE notifications
            ADD CONSTRAINT uq_notifications_user_dedupe_key UNIQUE (user_id, dedupe_key);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_notifications_user_id_read ON notifications (user_id, read);
CREATE INDEX IF NOT EXISTS ix_notifications_user_id_created_at ON notifications (user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_notifications_category ON notifications (category);
CREATE INDEX IF NOT EXISTS ix_notifications_priority ON notifications (priority);

ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS notify_job BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS notify_application BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS notify_interview BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS notify_deadline BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS notify_recruiter BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS notify_ai BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE user_notification_preferences ADD COLUMN IF NOT EXISTS notify_system BOOLEAN NOT NULL DEFAULT TRUE;
