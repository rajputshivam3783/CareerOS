-- V25.3: Data Intelligence, Career & Market Analytics.
--
-- Additive only. One new table and a set of indexes that serve queries
-- V25.3 introduces. No existing table is altered, no column is added to
-- an existing table, no column is removed or retyped, and no data is
-- rewritten — so every row written by V1-V25.2 stays valid with no
-- backfill, and rolling this migration back means dropping the new
-- table and the new indexes and nothing else.
--
-- As with every prior migration in this project, Base.metadata.create_all()
-- (the SQLite dev/test path — see app/db/session.py) creates all of this
-- from the current ORM models on a fresh database automatically. This
-- file applies the same change to an existing PostgreSQL deployment
-- (see scripts/run_migrations.py), and is safe to re-run.
--
-- ---------------------------------------------------------------------
-- WHAT IS DELIBERATELY NOT HERE (spec sections 15 and 30)
-- ---------------------------------------------------------------------
-- No aggregate tables, no analytics snapshots, and no materialized
-- views. Spec section 15 says to create them ONLY when necessary for
-- performance and to prefer real-time calculation when it is efficient
-- enough. Every V25.3 aggregate is a GROUP BY or COUNT over indexed
-- columns, bounded by a date window and a page size, over tables whose
-- size is measured in jobs and applications rather than in raw events.
-- Duplicating that data into a parallel analytics schema would buy
-- performance that has not been shown to be needed, at the cost of a
-- freshness problem, a refresh job, and a reconciliation burden — and
-- materialized views in particular exist in PostgreSQL but not SQLite,
-- which would give this application's two supported backends different
-- freshness semantics for the same endpoint.
--
-- No new analytics event table either. Everything section 16 lists is
-- already recorded by recommendation_events, application_events,
-- application_status_history, recruiter_pipeline_history,
-- search_query_logs, recent_searches, saved_jobs and applicants. See
-- the comment block above DataQualityIssueState in app/models/domain.py.
--
-- If aggregation ever does become the bottleneck, the documented next
-- step is in docs/V25_3_DATA_INTELLIGENCE.md: a nightly rollup of
-- (date, skill, job_count) only — never a copy of the jobs table.

-- ---------------------------------------------------------------------
-- 1. data_quality_issue_states — administrator triage decisions.
--
-- Data-quality ISSUES are not stored; they are recomputed from the rule
-- catalog on every request so the report can never drift from the data.
-- This table stores only the human judgement a recomputation cannot
-- reproduce ("acknowledged", "wont_fix", plus a note).
--
-- entity_id is deliberately NOT a foreign key: one row may refer to a
-- job, a user or an applicant depending on its rule, and several rules
-- exist precisely to find rows whose references are already broken — a
-- foreign key would make those orphans impossible to triage.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS data_quality_issue_states (
    id SERIAL PRIMARY KEY,
    rule_id VARCHAR(80) NOT NULL,
    entity_id INTEGER NOT NULL,
    state VARCHAR(20) NOT NULL DEFAULT 'open',
    note TEXT,
    updated_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_data_quality_issue_state UNIQUE (rule_id, entity_id)
);
CREATE INDEX IF NOT EXISTS ix_data_quality_issue_states_rule_id ON data_quality_issue_states (rule_id);
CREATE INDEX IF NOT EXISTS ix_data_quality_issue_states_entity_id ON data_quality_issue_states (entity_id);
CREATE INDEX IF NOT EXISTS ix_data_quality_issue_states_state ON data_quality_issue_states (state);
-- Serves the triage-state lookup the issue list performs for each page
-- of results (one query for the whole page, never one per row).
CREATE INDEX IF NOT EXISTS ix_data_quality_issue_states_rule_state
    ON data_quality_issue_states (rule_id, state);

-- ---------------------------------------------------------------------
-- 2. Indexes for the corpus filter every V25.3 analytic shares.
--
-- app/intelligence/corpus.py builds every job set from
-- "status = 'published' AND published_at >= <window>", then groups by
-- one of a small number of columns. Without these, each aggregation
-- degrades to a sequential scan as the jobs table grows (spec section 25).
-- ---------------------------------------------------------------------

-- The shared corpus predicate. Note V25.2 already added
-- ix_jobs_status_created (status, created_at DESC) for the moderation
-- queue; this is the publication-date equivalent the analytics layer
-- needs, since market activity is measured from published_at rather
-- than created_at.
CREATE INDEX IF NOT EXISTS ix_jobs_status_published_at ON jobs (status, published_at DESC);

-- Grouping keys used by market/admin distributions. Each is a narrow
-- composite on (status, <group column>) so the corpus filter and the
-- GROUP BY are served by the same index.
CREATE INDEX IF NOT EXISTS ix_jobs_status_category ON jobs (status, category);
CREATE INDEX IF NOT EXISTS ix_jobs_status_location ON jobs (status, location);
CREATE INDEX IF NOT EXISTS ix_jobs_status_work_mode ON jobs (status, work_mode);
CREATE INDEX IF NOT EXISTS ix_jobs_status_job_type ON jobs (status, job_type);

-- Organization-scoped intelligence resolves an organization's jobs
-- through Job.owner_user_id IN (member ids) — the same ownership
-- relationship V24.x and V25.2 use — and then filters by status.
CREATE INDEX IF NOT EXISTS ix_jobs_owner_status ON jobs (owner_user_id, status);

-- Candidate career intelligence reads one candidate's own applications
-- ordered by date; organization intelligence groups applications by job.
CREATE INDEX IF NOT EXISTS ix_applicants_user_created ON applicants (user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_applicants_job_stage ON applicants (job_id, pipeline_stage);

-- Ingestion activity sums runs per source inside a date window.
CREATE INDEX IF NOT EXISTS ix_ingestion_runs_source_started ON ingestion_runs (source_name, started_at);
