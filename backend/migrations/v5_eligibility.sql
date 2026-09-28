-- V5: eligibility AI — age-relaxation profile fields.
-- Non-destructive — safe to run against an existing CareerOS database.
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS reservation_category VARCHAR(30);
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS is_pwd BOOLEAN DEFAULT FALSE;
