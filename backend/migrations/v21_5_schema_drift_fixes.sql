-- V21.5 stabilization audit — schema drift fix.
--
-- app/models/domain.py's Partner model has had `email_verified` and
-- `recruiter_status` columns with no migration anywhere that ever
-- added them to the `partners` table — confirmed by actually running
-- every migration against a fresh Postgres database and diffing the
-- resulting schema against the ORM's column list. Neither column is
-- referenced anywhere else in the codebase (grepped for
-- `.email_verified`/`.recruiter_status` on a Partner instance
-- specifically — the only other hits are on the unrelated `User`
-- model, which already has its own `email_verified` column from an
-- earlier migration), so this is dead-but-declared state rather than
-- something actively breaking a real feature. Still fixed here so the
-- schema and the ORM agree, since that mismatch would otherwise
-- surface unpredictably (e.g. the moment anything does start reading
-- or writing partner.email_verified) with the actual root cause
-- (SELECTing a column that doesn't exist) far from this migration.

ALTER TABLE partners ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE partners ADD COLUMN IF NOT EXISTS recruiter_status VARCHAR(30);
