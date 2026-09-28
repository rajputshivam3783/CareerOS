ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS recruiter_status VARCHAR(30);
CREATE TABLE IF NOT EXISTS email_verifications (id SERIAL PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,code_hash VARCHAR(128) NOT NULL,purpose VARCHAR(30) DEFAULT 'verify_email',expires_at TIMESTAMP NOT NULL,consumed BOOLEAN DEFAULT FALSE,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_email_verifications_user_id ON email_verifications(user_id);
-- Existing local users predate OTP; preserve their ability to log in after upgrade.
UPDATE users SET email_verified=TRUE WHERE email_verified=FALSE AND created_at < CURRENT_TIMESTAMP;
