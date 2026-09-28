-- V20.5 (Phase 1): AI Learning & Skill Intelligence — Skill Intelligence
-- core. Additive only — no existing table is dropped, renamed, or has a
-- column removed. Safe to run against an existing CareerOS database.
--
-- SQLite (dev/test) doesn't need this file: Base.metadata.create_all()
-- creates every table below automatically on a fresh database. Run
-- against Postgres exactly like every prior vNN_M migration.
--
-- Does NOT touch resumes, resume_analyses, resume_job_matches,
-- career_preferences, career_action_items, mock_interview_reports, or
-- any V16-V20.4 table — those are read from, never altered, by
-- app.skill_intelligence.gap (see SKILL_INTELLIGENCE.md).

CREATE TABLE IF NOT EXISTS skills (
    id SERIAL PRIMARY KEY,
    canonical_name VARCHAR(120) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    category VARCHAR(20) NOT NULL,
    subcategory VARCHAR(40) NOT NULL,
    difficulty VARCHAR(20) NOT NULL DEFAULT 'beginner',
    description TEXT,
    is_admin_added BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_skill_canonical_name UNIQUE (canonical_name)
);
CREATE INDEX IF NOT EXISTS ix_skills_canonical_name ON skills (canonical_name);
CREATE INDEX IF NOT EXISTS ix_skills_category ON skills (category);
CREATE INDEX IF NOT EXISTS ix_skills_subcategory ON skills (subcategory);

CREATE TABLE IF NOT EXISTS skill_aliases (
    id SERIAL PRIMARY KEY,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    alias VARCHAR(120) NOT NULL,
    CONSTRAINT uq_skill_alias UNIQUE (alias)
);
CREATE INDEX IF NOT EXISTS ix_skill_aliases_skill_id ON skill_aliases (skill_id);
CREATE INDEX IF NOT EXISTS ix_skill_aliases_alias ON skill_aliases (alias);

CREATE TABLE IF NOT EXISTS skill_relationships (
    id SERIAL PRIMARY KEY,
    from_skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    to_skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    relationship_type VARCHAR(20) NOT NULL,
    CONSTRAINT uq_skill_relationship UNIQUE (from_skill_id, to_skill_id, relationship_type)
);
CREATE INDEX IF NOT EXISTS ix_skill_relationships_from_skill_id ON skill_relationships (from_skill_id);
CREATE INDEX IF NOT EXISTS ix_skill_relationships_to_skill_id ON skill_relationships (to_skill_id);
CREATE INDEX IF NOT EXISTS ix_skill_relationships_type ON skill_relationships (relationship_type);

-- ---------------------------------------------------------------------
-- Phase 2: Learning Paths & Resources
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS learning_resources (
    id SERIAL PRIMARY KEY,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    title VARCHAR(220) NOT NULL,
    provider VARCHAR(120),
    url VARCHAR(500),
    resource_type VARCHAR(30) NOT NULL,
    difficulty VARCHAR(20) NOT NULL DEFAULT 'beginner',
    duration_minutes INTEGER,
    language VARCHAR(40) NOT NULL DEFAULT 'English',
    is_free BOOLEAN NOT NULL DEFAULT true,
    rating FLOAT,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    is_verified BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_learning_resources_skill_id ON learning_resources (skill_id);
CREATE INDEX IF NOT EXISTS ix_learning_resources_resource_type ON learning_resources (resource_type);
CREATE INDEX IF NOT EXISTS ix_learning_resources_status ON learning_resources (status);
CREATE INDEX IF NOT EXISTS ix_learning_resources_is_verified ON learning_resources (is_verified);

CREATE TABLE IF NOT EXISTS learning_plans (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(220) NOT NULL,
    target_skill_id INTEGER REFERENCES skills(id) ON DELETE SET NULL,
    target_job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    target_date DATE,
    weekly_goal_hours FLOAT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_learning_plans_user_id ON learning_plans (user_id);
CREATE INDEX IF NOT EXISTS ix_learning_plans_status ON learning_plans (status);

CREATE TABLE IF NOT EXISTS learning_plan_modules (
    id SERIAL PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES learning_plans(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    resource_id INTEGER REFERENCES learning_resources(id) ON DELETE SET NULL,
    order_index INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'not_started',
    time_spent_minutes INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_learning_plan_module_order UNIQUE (plan_id, order_index)
);
CREATE INDEX IF NOT EXISTS ix_learning_plan_modules_plan_id ON learning_plan_modules (plan_id);
CREATE INDEX IF NOT EXISTS ix_learning_plan_modules_skill_id ON learning_plan_modules (skill_id);
CREATE INDEX IF NOT EXISTS ix_learning_plan_modules_status ON learning_plan_modules (status);

-- ---------------------------------------------------------------------
-- Phase 3: Assessments, Practice, Career Readiness
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS skill_assessments (
    id SERIAL PRIMARY KEY,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    title VARCHAR(220) NOT NULL,
    assessment_type VARCHAR(20) NOT NULL DEFAULT 'mcq',
    difficulty VARCHAR(20) NOT NULL DEFAULT 'beginner',
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_skill_assessments_skill_id ON skill_assessments (skill_id);
CREATE INDEX IF NOT EXISTS ix_skill_assessments_status ON skill_assessments (status);

CREATE TABLE IF NOT EXISTS assessment_questions (
    id SERIAL PRIMARY KEY,
    assessment_id INTEGER NOT NULL REFERENCES skill_assessments(id) ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    options_json TEXT NOT NULL,
    correct_option INTEGER NOT NULL,
    topic VARCHAR(80) NOT NULL,
    difficulty VARCHAR(20) NOT NULL DEFAULT 'beginner',
    explanation TEXT,
    order_index INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_assessment_questions_assessment_id ON assessment_questions (assessment_id);

CREATE TABLE IF NOT EXISTS assessment_attempts (
    id SERIAL PRIMARY KEY,
    assessment_id INTEGER NOT NULL REFERENCES skill_assessments(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
    total_questions INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    score_percentage FLOAT,
    weak_topics_json TEXT NOT NULL DEFAULT '[]',
    started_at TIMESTAMP NOT NULL DEFAULT now(),
    completed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_assessment_attempts_assessment_id ON assessment_attempts (assessment_id);
CREATE INDEX IF NOT EXISTS ix_assessment_attempts_user_id ON assessment_attempts (user_id);
CREATE INDEX IF NOT EXISTS ix_assessment_attempts_status ON assessment_attempts (status);

CREATE TABLE IF NOT EXISTS assessment_answers (
    id SERIAL PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES assessment_questions(id) ON DELETE CASCADE,
    selected_option INTEGER NOT NULL,
    is_correct BOOLEAN NOT NULL,
    CONSTRAINT uq_assessment_answer UNIQUE (attempt_id, question_id)
);
CREATE INDEX IF NOT EXISTS ix_assessment_answers_attempt_id ON assessment_answers (attempt_id);

CREATE TABLE IF NOT EXISTS practice_recommendations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    recommendation_type VARCHAR(30) NOT NULL,
    reason TEXT NOT NULL,
    priority_score INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_practice_recommendations_user_id ON practice_recommendations (user_id);
CREATE INDEX IF NOT EXISTS ix_practice_recommendations_skill_id ON practice_recommendations (skill_id);
CREATE INDEX IF NOT EXISTS ix_practice_recommendations_status ON practice_recommendations (status);

-- ---------------------------------------------------------------------
-- Phase 4: Learning Streak, Structured Project Briefs, Government
-- Integration (Government exam data reuses the existing V19.1 `jobs`
-- table (job_type='Government') and V8 `exam_prep_resources` table —
-- no new government tables are needed here, only these additive
-- columns on learning_plans / learning_resources).
-- ---------------------------------------------------------------------

ALTER TABLE learning_plans ADD COLUMN IF NOT EXISTS current_streak_days INTEGER NOT NULL DEFAULT 0;
ALTER TABLE learning_plans ADD COLUMN IF NOT EXISTS longest_streak_days INTEGER NOT NULL DEFAULT 0;
ALTER TABLE learning_plans ADD COLUMN IF NOT EXISTS last_activity_date DATE;

ALTER TABLE learning_resources ADD COLUMN IF NOT EXISTS objective TEXT;
ALTER TABLE learning_resources ADD COLUMN IF NOT EXISTS requirements TEXT;
ALTER TABLE learning_resources ADD COLUMN IF NOT EXISTS expected_output TEXT;
ALTER TABLE learning_resources ADD COLUMN IF NOT EXISTS evaluation_criteria TEXT;
