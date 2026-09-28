"""V18.5 — Recruiter email templates: an editable copy of the five ATS
notification templates (application received / interview invitation /
interview reminder / offer / rejection) per company.

Deliberately separate from app.api.recruiter and does not touch
app.api.company's endpoints — mounted alongside them under
``/recruiter/company/email-templates`` since a template set belongs to
the same company profile a recruiter owns. Storage + rendering only:
this module never sends an email itself (Notifications stays
untouched, per V18 scope) — it just gives a recruiter a place to
customize the wording other parts of the product would eventually send.
"""

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.constants import EMAIL_TEMPLATE_DEFAULTS, EMAIL_TEMPLATE_TYPES, EMAIL_TEMPLATE_VARIABLES
from app.core.security import require_recruiter
from app.db.session import get_db
from app.models.domain import EmailTemplate, Organization, User

router = APIRouter()

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

SAMPLE_VALUES = {
    "candidate_name": "Priya Sharma",
    "job_title": "Senior Backend Engineer",
    "company_name": "your company",
    "recruiter_name": "the hiring team",
    "interview_type": "Technical",
    "interview_date": "12 Aug 2026",
    "interview_time": "3:00 PM IST",
    "meeting_link": "https://meet.example.com/abc-defg",
}


def render_template(text: str, values: dict[str, str]) -> str:
    """Replaces ``{{variable}}`` placeholders with values, leaving any
    placeholder with no supplied value untouched rather than blanking
    it out — a preview or a partially-filled real send should never
    silently drop a variable no caller has data for yet."""

    def _sub(match: "re.Match[str]") -> str:
        key = match.group(1)
        return values[key] if key in values else match.group(0)

    return _PLACEHOLDER.sub(_sub, text)


def _owned_company_or_404(db: Session, recruiter: User) -> Organization:
    org = db.scalars(select(Organization).where(Organization.owner_user_id == recruiter.id)).first()
    if not org:
        raise HTTPException(404, "You haven't created a company profile yet")
    return org


def _valid_type_or_404(template_type: str) -> None:
    if template_type not in EMAIL_TEMPLATE_TYPES:
        raise HTTPException(404, f"Unknown template type. Must be one of {EMAIL_TEMPLATE_TYPES}")


def _get_or_seed(db: Session, org: Organization, template_type: str) -> EmailTemplate:
    """Returns the company's row for this template type, creating it
    from EMAIL_TEMPLATE_DEFAULTS on first access. Lazy seeding (rather
    than a migration-time backfill) means a new template type added to
    EMAIL_TEMPLATE_DEFAULTS later needs no migration to reach existing
    companies."""
    row = db.scalars(
        select(EmailTemplate).where(EmailTemplate.company_id == org.id, EmailTemplate.template_type == template_type)
    ).first()
    if row:
        return row
    default = EMAIL_TEMPLATE_DEFAULTS[template_type]
    row = EmailTemplate(
        company_id=org.id,
        template_type=template_type,
        subject=default["subject"],
        body=default["body"],
        is_custom=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _serialize(row: EmailTemplate) -> dict:
    return {
        "id": row.id,
        "template_type": row.template_type,
        "label": EMAIL_TEMPLATE_DEFAULTS[row.template_type]["label"],
        "subject": row.subject,
        "body": row.body,
        "is_custom": row.is_custom,
        "updated_at": row.updated_at,
    }


class TemplateIn(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)


class PreviewIn(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
    values: dict[str, str] | None = None


@router.get("/company/email-templates")
def list_templates(recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """All five template types for the recruiter's company, seeding
    any that haven't been opened/customized yet so the list is always
    complete rather than only showing rows that happen to exist."""
    org = _owned_company_or_404(db, recruiter)
    return [_serialize(_get_or_seed(db, org, t)) for t in EMAIL_TEMPLATE_TYPES]


@router.get("/company/email-templates/{template_type}")
def get_template(template_type: str, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    _valid_type_or_404(template_type)
    org = _owned_company_or_404(db, recruiter)
    return _serialize(_get_or_seed(db, org, template_type))


@router.put("/company/email-templates/{template_type}")
def update_template(
    template_type: str,
    payload: TemplateIn,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    _valid_type_or_404(template_type)
    org = _owned_company_or_404(db, recruiter)
    row = _get_or_seed(db, org, template_type)
    row.subject = payload.subject
    row.body = payload.body
    row.is_custom = True
    row.updated_by_user_id = recruiter.id
    db.commit()
    db.refresh(row)
    log_audit(db, "email_template.updated", "email_template", str(row.id), detail=template_type)
    db.commit()
    return _serialize(row)


@router.post("/company/email-templates/{template_type}/reset")
def reset_template(
    template_type: str, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)
):
    """Reverts a template to the built-in default text. Kept separate
    from PUT rather than inferring "reset" from a matching payload, so
    the audit trail records an explicit reset action."""
    _valid_type_or_404(template_type)
    org = _owned_company_or_404(db, recruiter)
    row = _get_or_seed(db, org, template_type)
    default = EMAIL_TEMPLATE_DEFAULTS[template_type]
    row.subject = default["subject"]
    row.body = default["body"]
    row.is_custom = False
    row.updated_by_user_id = recruiter.id
    db.commit()
    db.refresh(row)
    log_audit(db, "email_template.reset", "email_template", str(row.id), detail=template_type)
    db.commit()
    return _serialize(row)


@router.post("/company/email-templates/{template_type}/preview")
def preview_template(
    template_type: str,
    payload: PreviewIn,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    """Renders the given subject/body against sample candidate data (or
    caller-supplied overrides) without saving anything — lets the
    editor show "what a candidate would see" before the recruiter
    commits an edit."""
    _valid_type_or_404(template_type)
    _owned_company_or_404(db, recruiter)  # 404s if this recruiter has no company, same as the other endpoints
    values = {**SAMPLE_VALUES, **(payload.values or {})}
    return {
        "subject": render_template(payload.subject, values),
        "body": render_template(payload.body, values),
        "values_used": values,
    }


@router.get("/company/email-templates-meta/variables")
def list_variables(recruiter: User = Depends(require_recruiter)):
    """The placeholder variables the editor can offer as insertable
    tokens, plus the sample text used to render previews."""
    return {"variables": EMAIL_TEMPLATE_VARIABLES, "sample_values": SAMPLE_VALUES}
