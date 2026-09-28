-- V21.2: Advanced Job Search & Discovery.
-- Non-destructive — safe to run against an existing CareerOS database.
-- Adds exactly one new table (recent_searches). Does not alter,
-- rename, or drop search_index_documents, search_query_logs, or any
-- other existing table — the V21.1 search infrastructure this builds
-- on is untouched. See CHANGELOG_V21_2.md.

CREATE TABLE IF NOT EXISTS recent_searches (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    query VARCHAR(500) NOT NULL DEFAULT '',
    entity_types VARCHAR(300),
    filters_json TEXT,
    search_key VARCHAR(64) NOT NULL,
    result_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_recent_search_user_key UNIQUE (user_id, search_key)
);
CREATE INDEX IF NOT EXISTS ix_recent_searches_user_id ON recent_searches (user_id);
CREATE INDEX IF NOT EXISTS ix_recent_searches_search_key ON recent_searches (search_key);
CREATE INDEX IF NOT EXISTS ix_recent_searches_created_at ON recent_searches (created_at);
