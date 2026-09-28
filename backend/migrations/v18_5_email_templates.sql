-- V18.5: Recruiter email templates — an editable copy of the five ATS
-- notification templates (application received / interview invitation /
-- interview reminder / offer / rejection) per company. Additive only;
-- does not touch Notifications, Auth, or Security. Rows are seeded
-- lazily by the API from app.core.constants.EMAIL_TEMPLATE_DEFAULTS,
-- not by this migration, so no data backfill is required here.

CREATE TABLE IF NOT EXISTS email_templates (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    template_type VARCHAR(40) NOT NULL,
    subject VARCHAR(500) NOT NULL,
    body TEXT NOT NULL,
    is_custom BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_email_template_company_type UNIQUE (company_id, template_type)
);

CREATE INDEX IF NOT EXISTS ix_email_templates_company_id ON email_templates(company_id);
CREATE INDEX IF NOT EXISTS ix_email_templates_template_type ON email_templates(template_type);
