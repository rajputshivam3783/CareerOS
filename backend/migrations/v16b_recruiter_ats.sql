-- V16b: Recruiter ATS — interview scheduling, candidate notes, reject
-- reasons, offer letters. Non-destructive — safe to run against an
-- existing CareerOS database.

ALTER TABLE applicants ADD COLUMN IF NOT EXISTS reject_reason TEXT;

CREATE TABLE IF NOT EXISTS applicant_notes (
    id SERIAL PRIMARY KEY,
    applicant_id INTEGER NOT NULL REFERENCES applicants(id) ON DELETE CASCADE,
    author_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    note TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_applicant_notes_applicant_id ON applicant_notes(applicant_id);

CREATE TABLE IF NOT EXISTS interviews (
    id SERIAL PRIMARY KEY,
    applicant_id INTEGER NOT NULL REFERENCES applicants(id) ON DELETE CASCADE,
    round_name VARCHAR(120) DEFAULT 'Interview',
    mode VARCHAR(20) DEFAULT 'video',
    scheduled_at TIMESTAMP NOT NULL,
    location_or_link VARCHAR(500),
    notes TEXT,
    status VARCHAR(20) DEFAULT 'scheduled',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_interviews_applicant_id ON interviews(applicant_id);
CREATE INDEX IF NOT EXISTS ix_interviews_status ON interviews(status);

CREATE TABLE IF NOT EXISTS offer_letters (
    id SERIAL PRIMARY KEY,
    applicant_id INTEGER NOT NULL UNIQUE REFERENCES applicants(id) ON DELETE CASCADE,
    position_title VARCHAR(220) NOT NULL,
    salary VARCHAR(120),
    start_date DATE,
    expiry_date DATE,
    letter_text TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'draft',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_offer_letters_status ON offer_letters(status);
