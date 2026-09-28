-- V16: Backend hardening — per-actor audit trail.
-- Non-destructive — safe to run against an existing CareerOS database.
-- All new columns are nullable so existing audit_logs rows (written
-- before actor/request-id tracking existed) remain valid as-is.

ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS actor_type VARCHAR(20);
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS actor_id VARCHAR(120);
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS actor_label VARCHAR(160);
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS request_id VARCHAR(64);
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS ip_address VARCHAR(64);

CREATE INDEX IF NOT EXISTS ix_audit_logs_actor_type ON audit_logs(actor_type);
CREATE INDEX IF NOT EXISTS ix_audit_logs_request_id ON audit_logs(request_id);
