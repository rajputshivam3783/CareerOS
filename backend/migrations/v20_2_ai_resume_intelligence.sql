-- V20.2: AI Resume Intelligence. Additive only — no existing table is
-- dropped, renamed, or has a column removed. Safe to run against an
-- existing CareerOS database (including one already on V20.1).
--
-- SQLite (dev/test) doesn't need this file: Base.metadata.create_all()
-- creates every new table below automatically on a fresh database. The
-- ALTER TABLE for resumes.has_tables_or_columns below IS needed against
-- an existing SQLite file created before this column existed, same as
-- any other ALTER TABLE in this project's migrations.

ALTER TABLE resumes ADD COLUMN IF NOT EXISTS has_tables_or_columns BOOLEAN;

CREATE TABLE IF NOT EXISTS resume_analyses (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    profile_json TEXT NOT NULL,
    scores_json TEXT NOT NULL,
    analyzed_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS resume_job_matches (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    overall_score INTEGER NOT NULL,
    skills_score INTEGER NOT NULL,
    experience_score INTEGER NOT NULL,
    education_score INTEGER NOT NULL,
    keywords_score INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    computed_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_resume_job_match UNIQUE (user_id, job_id)
);
CREATE INDEX IF NOT EXISTS ix_resume_job_matches_user_id ON resume_job_matches (user_id);
CREATE INDEX IF NOT EXISTS ix_resume_job_matches_job_id ON resume_job_matches (job_id);

CREATE TABLE IF NOT EXISTS resume_ai_suggestions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind VARCHAR(40) NOT NULL,
    context_key VARCHAR(64) NOT NULL,
    content TEXT NOT NULL,
    provider VARCHAR(30),
    model VARCHAR(80),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_resume_ai_suggestion UNIQUE (user_id, kind, context_key)
);
CREATE INDEX IF NOT EXISTS ix_resume_ai_suggestions_user_id ON resume_ai_suggestions (user_id);
CREATE INDEX IF NOT EXISTS ix_resume_ai_suggestions_kind ON resume_ai_suggestions (kind);
