-- V17.3: Enterprise RBAC, Session Management & Admin Controls.
-- Non-destructive — safe to run against an existing CareerOS database.
-- All new columns are nullable so existing rows stay valid as-is.
-- New role values (recruiter_manager, recruiter_admin, support_admin,
-- system_admin) need no schema change — users.role is a plain VARCHAR
-- with no DB-level enum constraint (same as every prior role/status
-- value added to this project).

ALTER TABLE users ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS suspension_reason VARCHAR(500);

CREATE TABLE IF NOT EXISTS role_permission_overrides (
    id SERIAL PRIMARY KEY,
    role VARCHAR(30) NOT NULL,
    permission VARCHAR(80) NOT NULL,
    granted BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_role_permission UNIQUE (role, permission)
);
CREATE INDEX IF NOT EXISTS ix_role_permission_overrides_role ON role_permission_overrides(role);
CREATE INDEX IF NOT EXISTS ix_role_permission_overrides_permission ON role_permission_overrides(permission);
