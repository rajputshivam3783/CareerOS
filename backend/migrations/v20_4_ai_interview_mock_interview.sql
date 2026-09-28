-- V20.4: AI Interview & Mock Interview System. Additive only — no
-- existing table is dropped, renamed, or has a column removed. Safe
-- to run against an existing CareerOS database (including one already
-- on V20.1-V20.3).
--
-- V20.6 AUDIT NOTE: this migration was missing entirely prior to
-- V20.6 — V20.4 shipped with SQLAlchemy models only
-- (app.models.domain.MockInterview*), which meant SQLite/dev
-- environments worked fine (Base.metadata.create_all() creates every
-- table automatically on a fresh database) but a production Postgres
-- deployment following this project's per-version migration
-- convention would have been missing these six tables entirely. This
-- file was authored to exactly match the existing SQLAlchemy model
-- definitions — see AI_PRODUCTION_ARCHITECTURE.md / CHANGELOG_V20_6.md
-- for how this was found and verified.

CREATE TABLE IF NOT EXISTS mock_interview_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    interview_type VARCHAR(30) NOT NULL,
    target_role VARCHAR(160),
    experience_level VARCHAR(40),
    difficulty VARCHAR(20) NOT NULL DEFAULT 'medium',
    duration_minutes INTEGER NOT NULL DEFAULT 30,
    planned_question_count INTEGER NOT NULL DEFAULT 8,
    focus_skills TEXT,
    programming_language VARCHAR(40),
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    current_question_index INTEGER NOT NULL DEFAULT 0,
    current_difficulty VARCHAR(20) NOT NULL DEFAULT 'medium',
    consecutive_strong_answers INTEGER NOT NULL DEFAULT 0,
    consecutive_weak_answers INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMP,
    paused_at TIMESTAMP,
    completed_at TIMESTAMP,
    total_paused_seconds INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_mock_interview_sessions_user_id ON mock_interview_sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_mock_interview_sessions_job_id ON mock_interview_sessions (job_id);
CREATE INDEX IF NOT EXISTS ix_mock_interview_sessions_interview_type ON mock_interview_sessions (interview_type);
CREATE INDEX IF NOT EXISTS ix_mock_interview_sessions_status ON mock_interview_sessions (status);

CREATE TABLE IF NOT EXISTS mock_interview_questions (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES mock_interview_sessions(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    category VARCHAR(60) NOT NULL,
    difficulty VARCHAR(20) NOT NULL,
    question_text TEXT NOT NULL,
    parent_question_id INTEGER REFERENCES mock_interview_questions(id) ON DELETE SET NULL,
    source VARCHAR(30) NOT NULL DEFAULT 'question_bank',
    source_detail VARCHAR(300),
    asked_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_mock_interview_questions_session_id ON mock_interview_questions (session_id);
CREATE INDEX IF NOT EXISTS ix_mock_interview_questions_category ON mock_interview_questions (category);

CREATE TABLE IF NOT EXISTS mock_interview_answers (
    id SERIAL PRIMARY KEY,
    question_id INTEGER NOT NULL UNIQUE REFERENCES mock_interview_questions(id) ON DELETE CASCADE,
    answer_text TEXT NOT NULL,
    skipped BOOLEAN NOT NULL DEFAULT false,
    submitted_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_mock_interview_answers_question_id ON mock_interview_answers (question_id);

CREATE TABLE IF NOT EXISTS mock_interview_evaluations (
    id SERIAL PRIMARY KEY,
    answer_id INTEGER NOT NULL UNIQUE REFERENCES mock_interview_answers(id) ON DELETE CASCADE,
    overall_score INTEGER NOT NULL,
    correctness_score INTEGER NOT NULL,
    technical_depth_score INTEGER NOT NULL,
    relevance_score INTEGER NOT NULL,
    clarity_score INTEGER NOT NULL,
    communication_score INTEGER NOT NULL,
    structure_score INTEGER NOT NULL,
    confidence_score INTEGER NOT NULL,
    completeness_score INTEGER NOT NULL,
    explanation TEXT NOT NULL,
    strengths_json TEXT NOT NULL DEFAULT '[]',
    weaknesses_json TEXT NOT NULL DEFAULT '[]',
    missing_json TEXT NOT NULL DEFAULT '[]',
    improvement_tips_json TEXT NOT NULL DEFAULT '[]',
    stronger_example TEXT,
    triggered_followup BOOLEAN NOT NULL DEFAULT false,
    difficulty_adjustment VARCHAR(20) NOT NULL DEFAULT 'same',
    provider VARCHAR(30),
    model VARCHAR(80),
    degraded BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_mock_interview_evaluations_answer_id ON mock_interview_evaluations (answer_id);

CREATE TABLE IF NOT EXISTS mock_interview_reports (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL UNIQUE REFERENCES mock_interview_sessions(id) ON DELETE CASCADE,
    overall_score INTEGER NOT NULL,
    technical_score INTEGER NOT NULL,
    communication_score INTEGER NOT NULL,
    problem_solving_score INTEGER NOT NULL,
    role_fit_score INTEGER NOT NULL,
    confidence_score INTEGER NOT NULL,
    strengths_json TEXT NOT NULL DEFAULT '[]',
    weaknesses_json TEXT NOT NULL DEFAULT '[]',
    technical_gaps_json TEXT NOT NULL DEFAULT '[]',
    communication_feedback TEXT NOT NULL,
    recommended_topics_json TEXT NOT NULL DEFAULT '[]',
    summary TEXT NOT NULL,
    next_steps_json TEXT NOT NULL DEFAULT '[]',
    questions_answered INTEGER NOT NULL DEFAULT 0,
    questions_skipped INTEGER NOT NULL DEFAULT 0,
    generated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_mock_interview_reports_session_id ON mock_interview_reports (session_id);

CREATE TABLE IF NOT EXISTS mock_interview_coding_submissions (
    id SERIAL PRIMARY KEY,
    question_id INTEGER NOT NULL UNIQUE REFERENCES mock_interview_questions(id) ON DELETE CASCADE,
    language VARCHAR(40) NOT NULL,
    code_text TEXT NOT NULL,
    sandbox_status VARCHAR(20) NOT NULL DEFAULT 'unavailable',
    sandbox_message TEXT,
    stdout TEXT,
    stderr TEXT,
    submitted_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_mock_interview_coding_submissions_question_id ON mock_interview_coding_submissions (question_id);
