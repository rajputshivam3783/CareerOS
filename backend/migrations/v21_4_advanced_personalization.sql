-- V21.4: Advanced Personalization & Intelligent Ranking.
-- Non-destructive and backward compatible — safe to run against an
-- existing CareerOS database. Extends two V21.3 tables (both changes
-- widen constraints / add nullable columns, never narrow or drop
-- anything an existing row or query depends on) and adds three new
-- tables. Does not alter jobs, users, skills, applications,
-- saved_jobs, search_index_documents, recommendation_feedback, or
-- recommendation_snapshots. See PERSONALIZATION_ARCHITECTURE.md.

-- --- Extend V21.3's recommendation_events (BEHAVIOR SIGNALS) ---
-- job_id becomes nullable: "search" and "filter_usage" behavioral
-- signals (new in V21.4) aren't tied to one job. Existing rows are
-- unaffected (job_id already NOT NULL and populated for all of them).
ALTER TABLE recommendation_events ALTER COLUMN job_id DROP NOT NULL;
-- filters_json: short structured metadata for filter_usage/feed_view
-- events (e.g. which filter dimension was toggled, or a feed's result
-- count + latency for admin metrics) — never free-text search queries
-- or any other candidate-authored text. Nullable, so every existing
-- row reads back as NULL with no behavior change.
ALTER TABLE recommendation_events ADD COLUMN IF NOT EXISTS filters_json TEXT;
-- experiment_variant: which A/B TESTING FOUNDATION variant (if any)
-- was active when this event was recorded, for future experiment
-- metrics. NULL for every event today, since no experiment is active
-- by default (see RANKING_EXPERIMENTS.md) — zero behavior change.
ALTER TABLE recommendation_events ADD COLUMN IF NOT EXISTS experiment_variant VARCHAR(40);

-- --- Extend V21.3's recommendation_preferences (USER CONTROLS) ---
-- personalization_enabled: the "Personalized Recommendations ON/OFF"
-- toggle. Defaults TRUE so every existing candidate's behavior is
-- unchanged until they explicitly opt out.
ALTER TABLE recommendation_preferences ADD COLUMN IF NOT EXISTS personalization_enabled BOOLEAN NOT NULL DEFAULT TRUE;

-- --- New: aggregated, time-decayed behavioral signals ---
-- One row per (user, signal_type, signal_key) — e.g.
-- ('skill', 'python'), ('company', 'Acme Corp'),
-- ('location', 'Noida'), ('job_type', 'Government'),
-- ('role_keyword', 'backend'). `score` is a running exponentially
-- time-decayed weighted sum (see BEHAVIOR_SIGNALS.md), updated
-- incrementally on every event — ranking reads this table directly
-- rather than re-scanning raw event history, and no unbounded
-- per-event history needs to be kept for ranking purposes (PERFORMANCE
-- + DATA RETENTION requirements).
CREATE TABLE IF NOT EXISTS behavior_signal_aggregates (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    signal_type VARCHAR(20) NOT NULL,
    signal_key VARCHAR(120) NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    event_count INTEGER NOT NULL DEFAULT 0,
    last_event_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, signal_type, signal_key)
);
CREATE INDEX IF NOT EXISTS ix_behavior_signal_aggregates_user_id ON behavior_signal_aggregates (user_id);

-- --- New: admin-configurable ranking parameters (RANKING CONFIGURATION) ---
-- Single-row-per-key store so weights/decay/penalties can be tuned
-- without a redeploy. Never exposed to normal candidates — see
-- app/api/recommendations.py's admin_guard-gated endpoints. Empty by
-- default: absence of a row for a key means "use the documented
-- code-level default" (see RANKING_ENGINE_V21_4.md) — this table only
-- ever *overrides* defaults, so an empty table is a fully valid,
-- fully functional state.
CREATE TABLE IF NOT EXISTS ranking_configuration (
    config_key VARCHAR(60) PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);

-- --- New: A/B TESTING FOUNDATION (dormant unless an admin explicitly
-- activates one) ---
-- No per-user assignment table: variant assignment is a deterministic
-- pure function of (user_id, experiment_key) — see
-- app.recommendations.experiments — so it never needs to be persisted
-- or can drift out of sync with this table.
CREATE TABLE IF NOT EXISTS ranking_experiments (
    id SERIAL PRIMARY KEY,
    experiment_key VARCHAR(60) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft / active / stopped
    variants_json TEXT NOT NULL, -- e.g. {"control": 50, "variant_b": 50}
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
