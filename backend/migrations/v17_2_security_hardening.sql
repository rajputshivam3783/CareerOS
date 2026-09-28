-- V17.2: Enterprise Security Hardening — account lockout + OTP attempts.
-- Non-destructive — safe to run against an existing CareerOS database.
-- All new columns are nullable or zero-defaulted so existing rows stay
-- valid as-is.

ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_failed_login_at TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS lock_count INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS ix_users_locked_until ON users(locked_until);

ALTER TABLE email_verifications ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;
