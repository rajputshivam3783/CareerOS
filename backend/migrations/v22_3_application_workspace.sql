-- V22.3: Application Timeline, Notes & Documents.
-- Adds new child tables of the existing `applications` table (V7/V22.1)
-- — does NOT create a duplicate application system. Every application's
-- own status/status history is untouched; ApplicationStatusHistory is
-- reused (never duplicated) by the new unified timeline. No existing
-- migration file is edited. See docs/V22_3_APPLICATION_WORKSPACE.md.

-- --- Notes ---
CREATE TABLE IF NOT EXISTS application_notes (
    id SERIAL PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_application_notes_application_id_created_at
    ON application_notes (application_id, created_at);

-- --- Interviews ---
CREATE TABLE IF NOT EXISTS application_interviews (
    id SERIAL PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    interview_type VARCHAR(30) NOT NULL,
    round_name VARCHAR(120),
    scheduled_at TIMESTAMP,
    duration_minutes INTEGER,
    interviewer_name VARCHAR(220),
    interviewer_email VARCHAR(255),
    meeting_url VARCHAR(1000),
    location VARCHAR(220),
    notes TEXT,
    result VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED',
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_application_interviews_application_id_scheduled_at
    ON application_interviews (application_id, scheduled_at);

-- --- Tasks / follow-ups ---
CREATE TABLE IF NOT EXISTS application_tasks (
    id SERIAL PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    title VARCHAR(220) NOT NULL,
    description TEXT,
    due_at TIMESTAMP,
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_application_tasks_application_id_due_at
    ON application_tasks (application_id, due_at);

-- --- Documents (metadata only — raw bytes live on disk, see
-- app/applications/documents.py; the storage path is never persisted
-- in a form the frontend receives, only stored_filename here). ---
CREATE TABLE IF NOT EXISTS application_documents (
    id SERIAL PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    category VARCHAR(30) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(255) NOT NULL UNIQUE,
    file_size INTEGER NOT NULL,
    mime_type VARCHAR(120),
    uploaded_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_application_documents_application_id_uploaded_at
    ON application_documents (application_id, uploaded_at);

-- --- Unified activity/timeline events (status changes are NOT
-- duplicated here — the timeline reads ApplicationStatusHistory
-- directly; see app/applications/timeline.py). ---
CREATE TABLE IF NOT EXISTS application_events (
    id SERIAL PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    event_type VARCHAR(40) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    metadata_json TEXT,
    occurred_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_application_events_application_id_occurred_at
    ON application_events (application_id, occurred_at);
