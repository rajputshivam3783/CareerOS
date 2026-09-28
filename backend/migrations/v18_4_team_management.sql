-- V18.4: Team management — recruiters who can be listed as members of
-- a company profile. Additive only; does not touch `users`, auth, or
-- role assignment. Every existing company gets a backfilled "owner"
-- row so the roster is never empty for a company that predates this
-- migration.

CREATE TABLE IF NOT EXISTS company_team_members (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL DEFAULT 'member',
    added_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_team_company_user UNIQUE (company_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_company_team_members_company_id ON company_team_members(company_id);
CREATE INDEX IF NOT EXISTS ix_company_team_members_user_id ON company_team_members(user_id);

INSERT INTO company_team_members (company_id, user_id, role, added_by_user_id)
SELECT o.id, o.owner_user_id, 'owner', o.owner_user_id
FROM organizations o
WHERE o.owner_user_id IS NOT NULL
ON CONFLICT (company_id, user_id) DO NOTHING;
