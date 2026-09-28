-- V7: Application OS — exam lifecycle fields + notifications.
-- Non-destructive — safe to run against an existing CareerOS database.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS admit_card_url VARCHAR(1000);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS admit_card_date DATE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS result_url VARCHAR(1000);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS result_date DATE;
CREATE INDEX IF NOT EXISTS ix_jobs_result_date ON jobs(result_date);

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    notification_type VARCHAR(30) NOT NULL,
    title VARCHAR(220) NOT NULL,
    message TEXT NOT NULL,
    read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications(user_id);
CREATE INDEX IF NOT EXISTS ix_notifications_type ON notifications(notification_type);
CREATE INDEX IF NOT EXISTS ix_notifications_read ON notifications(read);

ALTER TABLE alerts ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMP;
