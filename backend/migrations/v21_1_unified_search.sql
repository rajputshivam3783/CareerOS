-- V21.1: Unified Search Infrastructure.
-- Non-destructive — safe to run against an existing CareerOS database.
-- Adds exactly two new tables. Does not alter, rename, or drop any
-- existing table/column (Job, GovernmentOrganization, Organization,
-- Skill, LearningResource, etc. are untouched).

CREATE TABLE IF NOT EXISTS search_index_documents (
    id SERIAL PRIMARY KEY,
    entity_type VARCHAR(30) NOT NULL,
    entity_id INTEGER NOT NULL,

    title VARCHAR(300) NOT NULL DEFAULT '',
    description TEXT,
    organization VARCHAR(220),
    location VARCHAR(220),
    category VARCHAR(100),

    job_type VARCHAR(40),
    employment_type VARCHAR(40),
    work_mode VARCHAR(20),
    experience_required VARCHAR(120),
    education VARCHAR(220),
    salary_min DOUBLE PRECISION,
    salary_max DOUBLE PRECISION,
    ad_number VARCHAR(120),

    skills_text TEXT,
    tags TEXT,

    posted_date DATE,
    deadline DATE,

    status VARCHAR(30) NOT NULL DEFAULT 'published',
    visibility VARCHAR(20) NOT NULL DEFAULT 'public',
    owner_user_id INTEGER,

    source VARCHAR(60),
    quality_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    metadata_json TEXT,
    search_text TEXT NOT NULL DEFAULT '',

    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_search_doc_entity UNIQUE (entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS ix_search_index_documents_entity_type ON search_index_documents(entity_type);
CREATE INDEX IF NOT EXISTS ix_search_index_documents_entity_id ON search_index_documents(entity_id);
CREATE INDEX IF NOT EXISTS ix_search_index_documents_organization ON search_index_documents(organization);
CREATE INDEX IF NOT EXISTS ix_search_index_documents_location ON search_index_documents(location);
CREATE INDEX IF NOT EXISTS ix_search_index_documents_category ON search_index_documents(category);
CREATE INDEX IF NOT EXISTS ix_search_index_documents_job_type ON search_index_documents(job_type);
CREATE INDEX IF NOT EXISTS ix_search_index_documents_employment_type ON search_index_documents(employment_type);
CREATE INDEX IF NOT EXISTS ix_search_index_documents_work_mode ON search_index_documents(work_mode);
CREATE INDEX IF NOT EXISTS ix_search_index_documents_salary_min ON search_index_documents(salary_min);
CREATE INDEX IF NOT EXISTS ix_search_index_documents_salary_max ON search_index_documents(salary_max);
CREATE INDEX IF NOT EXISTS ix_search_index_documents_ad_number ON search_index_documents(ad_number);
CREATE INDEX IF NOT EXISTS ix_search_index_documents_posted_date ON search_index_documents(posted_date);
CREATE INDEX IF NOT EXISTS ix_search_index_documents_deadline ON search_index_documents(deadline);
CREATE INDEX IF NOT EXISTS ix_search_index_documents_status ON search_index_documents(status);
CREATE INDEX IF NOT EXISTS ix_search_index_documents_visibility ON search_index_documents(visibility);
CREATE INDEX IF NOT EXISTS ix_search_index_documents_owner_user_id ON search_index_documents(owner_user_id);

-- Case-insensitive substring/prefix/phrase matching against search_text
-- is done via ILIKE by the V21.1 DatabaseSearchProvider (see
-- backend/app/search/provider.py). A trigram index dramatically speeds
-- up ILIKE '%term%' queries once the table has meaningful volume; it's
-- optional (search still works without it, just slower on a full scan)
-- so this migration does not hard-fail if the extension can't be
-- created (e.g. insufficient privileges on a managed Postgres instance).
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE INDEX IF NOT EXISTS ix_search_index_documents_search_text_trgm
        ON search_index_documents USING gin (search_text gin_trgm_ops);
EXCEPTION WHEN insufficient_privilege OR feature_not_supported THEN
    RAISE NOTICE 'Skipping pg_trgm index on search_index_documents — extension unavailable/insufficient privilege. ILIKE search still works, just without the trigram speedup.';
END $$;

CREATE TABLE IF NOT EXISTS search_query_logs (
    id SERIAL PRIMARY KEY,
    query VARCHAR(500) NOT NULL DEFAULT '',
    entity_types VARCHAR(300),
    filters_json TEXT,
    result_count INTEGER NOT NULL DEFAULT 0,
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    had_results BOOLEAN NOT NULL DEFAULT TRUE,
    actor_role VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_search_query_logs_had_results ON search_query_logs(had_results);
CREATE INDEX IF NOT EXISTS ix_search_query_logs_created_at ON search_query_logs(created_at);

-- Populate the new index from existing data. Safe to re-run — the
-- application-level reindex (POST /api/v1/admin/search/reindex, or the
-- app.search.indexer.reindex_all Python entrypoint) is idempotent and
-- is the recommended way to do this in production, since it applies
-- the same normalization/permission logic as every subsequent
-- incremental update. This SQL migration deliberately does NOT
-- attempt to replicate that Python-side normalization in raw SQL —
-- run the reindex endpoint/CLI once after applying this migration.
