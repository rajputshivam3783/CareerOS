"""V21.1 — the normalized searchable document model.

``EntityType`` is the closed set of things that can appear in search
results. Note that JOB / GOVERNMENT_RECRUITMENT / INTERNSHIP /
APPRENTICESHIP are all backed by the *same* ``Job`` table (see
app.models.domain.Job — it already unifies these via ``job_type``,
per V19.1's Government Recruitment Core and V18.2's job management).
This module does not create four different job tables; it derives
four different *search entity types* from one ``Job.job_type`` field,
so a person filtering by "Internship" sees internships without a
separate internship model existing anywhere.

Each ``build_*_document`` function maps one source-of-truth row to a
plain dict shaped like ``SearchIndexDocument`` columns (see
app.search.models) — the indexer upserts that dict as a row.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from enum import Enum

from sqlalchemy.orm import Session

from app.models.domain import GovernmentOrganization, Job, LearningResource, Organization, Skill
from app.search.normalization import (
    build_search_text,
    normalize_location,
    normalize_organization,
    normalize_skills,
    normalize_title,
)


class EntityType(str, Enum):
    JOB = "JOB"
    GOVERNMENT_RECRUITMENT = "GOVERNMENT_RECRUITMENT"
    INTERNSHIP = "INTERNSHIP"
    APPRENTICESHIP = "APPRENTICESHIP"
    COMPANY = "COMPANY"
    ORGANIZATION = "ORGANIZATION"
    SKILL = "SKILL"
    LEARNING_RESOURCE = "LEARNING_RESOURCE"


# Job.job_type -> search EntityType. Anything not listed (e.g.
# "Private", or a future job_type value) falls back to JOB.
_JOB_TYPE_TO_ENTITY_TYPE = {
    "Government": EntityType.GOVERNMENT_RECRUITMENT,
    "Internship": EntityType.INTERNSHIP,
    "Apprenticeship": EntityType.APPRENTICESHIP,
}

JOB_FAMILY_ENTITY_TYPES = frozenset(
    {EntityType.JOB, EntityType.GOVERNMENT_RECRUITMENT, EntityType.INTERNSHIP, EntityType.APPRENTICESHIP}
)


@dataclass
class SearchDocument:
    """In-memory shape mirroring SearchIndexDocument's columns, used
    as the interchange format between document builders, the indexer,
    and (for a not-yet-persisted preview) callers that just want the
    normalized shape without touching the database."""

    entity_type: EntityType
    entity_id: int
    title: str
    description: str | None = None
    organization: str | None = None
    location: str | None = None
    category: str | None = None
    job_type: str | None = None
    employment_type: str | None = None
    work_mode: str | None = None
    experience_required: str | None = None
    education: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    ad_number: str | None = None
    skills: list[str] | None = None
    tags: list[str] | None = None
    posted_date: date | None = None
    deadline: date | None = None
    status: str = "published"
    visibility: str = "public"
    owner_user_id: int | None = None
    source: str | None = None
    quality_score: float = 0.0
    metadata: dict | None = None

    def as_row_kwargs(self) -> dict:
        skills_text = ",".join(self.skills) if self.skills else None
        tags_text = ",".join(self.tags) if self.tags else None
        # Alias-expanded forms of title/organization/location are appended
        # (not substituted) so a query in either the abbreviated or full
        # form ("Sr" / "Senior", "SSC" / "Staff Selection Commission",
        # "BLR" / "Bangalore") still hits this document via plain token
        # matching, without losing the original text.
        search_text = build_search_text(
            self.title,
            normalize_title(self.title),
            self.description,
            self.organization,
            normalize_organization(self.organization),
            self.location,
            normalize_location(self.location),
            self.category,
            skills_text,
            tags_text,
            self.ad_number,
        )
        return {
            "entity_type": self.entity_type.value,
            "entity_id": self.entity_id,
            "title": self.title or "",
            "description": self.description,
            "organization": self.organization,
            "location": self.location,
            "category": self.category,
            "job_type": self.job_type,
            "employment_type": self.employment_type,
            "work_mode": self.work_mode,
            "experience_required": self.experience_required,
            "education": self.education,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "ad_number": self.ad_number,
            "skills_text": skills_text,
            "tags": tags_text,
            "posted_date": self.posted_date,
            "deadline": self.deadline,
            "status": self.status,
            "visibility": self.visibility,
            "owner_user_id": self.owner_user_id,
            "source": self.source,
            "quality_score": self.quality_score,
            "metadata_json": json.dumps(self.metadata) if self.metadata else None,
            "search_text": search_text,
        }


def _parse_salary_bounds(salary: str | None) -> tuple[float | None, float | None]:
    """Best-effort numeric bounds out of Job.salary's free-text field
    (e.g. "₹8,00,000 - ₹12,00,000 per annum"), for salary-range
    filtering/sorting. Returns (None, None) when nothing numeric is
    found rather than guessing — a free-text field that says
    "Negotiable" has no salary range to filter on, and this must never
    fabricate one."""
    if not salary:
        return None, None
    import re

    numbers = [float(n.replace(",", "")) for n in re.findall(r"[\d,]+(?:\.\d+)?", salary)]
    if not numbers:
        return None, None
    return min(numbers), max(numbers)


def _parse_job_skills(raw: str | None) -> list[str]:
    """Job.skills is documented (see the model's own comment) as
    comma-separated, and app/interview_ai/question_engine.py reads it
    that way — but app/api/recruiter.py actually writes it as a
    JSON-encoded array (``json.dumps(payload.skills)``). That's a
    pre-existing format inconsistency in a module V21.1 was told not
    to touch (AI Interview System) / not to redesign (recruiter job
    creation), so rather than "fixing" either of those call sites,
    this parses defensively: JSON array first, comma-separated
    fallback. See CHANGELOG_V21_1.md "Found but not fixed"."""
    if not raw:
        return []
    text = raw.strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(s).strip() for s in parsed if str(s).strip()]
        except (json.JSONDecodeError, TypeError):
            pass
    return [s.strip() for s in text.split(",") if s.strip()]


def build_job_document(db: Session, job: Job) -> SearchDocument:
    entity_type = _JOB_TYPE_TO_ENTITY_TYPE.get(job.job_type, EntityType.JOB)
    raw_skills = _parse_job_skills(job.skills)
    # V21.2: internships/apprenticeships store compensation in
    # `stipend`, not `salary` — Job practically only ever populates
    # one or the other depending on job_type. Reusing salary_min/max
    # for stipend too means the SALARY RANGE filter/sort already
    # built for private jobs works for internship stipends as well,
    # without a second indexed column or a second filter code path.
    salary_min, salary_max = _parse_salary_bounds(job.salary or job.stipend)

    # Visibility: a recruiter-owned posting is private until published;
    # once published it's public like any other job (matches the
    # existing convention across app/api/platform.py, government_core.py
    # etc. of gating public listing endpoints on status == "published").
    visibility = "public" if job.status == "published" else "private"

    return SearchDocument(
        entity_type=entity_type,
        entity_id=job.id,
        title=job.title,
        description=job.description,
        organization=job.organization,
        location=job.location,
        category=job.category,
        job_type=job.job_type,
        employment_type=job.employment_type,
        work_mode=job.work_mode,
        experience_required=job.experience_required,
        education=job.qualification,
        salary_min=salary_min,
        salary_max=salary_max,
        ad_number=job.ad_number,
        skills=normalize_skills(db, raw_skills),
        tags=[t for t in [job.industry, job.govt_level] if t],
        posted_date=job.start_date,
        deadline=job.deadline,
        status=job.status,
        visibility=visibility,
        owner_user_id=job.owner_user_id,
        source=job.source_name,
        quality_score=1.0 if job.verified else 0.0,
        metadata={
            "slug": job.slug,
            "apply_url": job.apply_url,
            "official_url": job.official_url,
            "vacancies": job.vacancies,
            # V21.2 additions — result cards need these per JOB_RESULT_CARDS;
            # additive only, no new column, nothing here duplicates a filter
            # field already indexed separately (job_type/salary_min/max/etc.).
            "verified": job.verified,
            "skills": normalize_skills(db, raw_skills),
            "salary_display": job.salary,
            "stipend_display": job.stipend,
            "duration": job.duration,
            "govt_level": job.govt_level,
            "selection_process": job.selection_process,
            "notification_url": job.notification_url,
            "answer_key_url": job.answer_key_url,
            "admit_card_url": job.admit_card_url,
            "admit_card_date": job.admit_card_date.isoformat() if job.admit_card_date else None,
            "result_url": job.result_url,
            "result_date": job.result_date.isoformat() if job.result_date else None,
            "exam_date": job.exam_date.isoformat() if job.exam_date else None,
            "age_limit": job.age_limit,
            "application_fee": job.application_fee,
            "pay_level": job.pay_level,
            "industry": job.industry,
            "owner_is_recruiter": job.owner_user_id is not None,
        },
    )


def build_government_organization_document(org: GovernmentOrganization) -> SearchDocument:
    return SearchDocument(
        entity_type=EntityType.ORGANIZATION,
        entity_id=org.id,
        title=org.name,
        description=org.department,
        organization=org.name,
        category=org.govt_level,
        status="published" if org.status == "active" else org.status,
        visibility="public" if org.status == "active" else "private",
        source="government",
        quality_score=1.0,
        metadata={"short_name": org.short_name, "ministry": org.ministry, "website": org.official_website},
        tags=[t for t in [org.govt_level] if t],
    )


def build_company_document(org: Organization) -> SearchDocument:
    # Matches app.api.company.list_companies' public visibility rule:
    # any company that has claimed a slug is publicly listable.
    visibility = "public" if org.slug else "private"
    return SearchDocument(
        entity_type=EntityType.COMPANY,
        entity_id=org.id,
        title=org.name,
        description=org.description,
        organization=org.name,
        location=org.location,
        category=org.industry,
        status="published" if org.slug else "draft",
        visibility=visibility,
        owner_user_id=org.owner_user_id,
        source="company_directory",
        quality_score=1.0 if org.verification_status == "verified" else 0.0,
        metadata={"slug": org.slug, "website": org.website, "company_size": org.company_size},
    )


def build_skill_document(skill: Skill) -> SearchDocument:
    return SearchDocument(
        entity_type=EntityType.SKILL,
        entity_id=skill.id,
        title=skill.display_name,
        description=skill.description,
        category=skill.category,
        status="published",
        visibility="public",
        source="skill_catalog",
        quality_score=1.0,
        tags=[t for t in [skill.subcategory, skill.difficulty] if t],
    )


def build_learning_resource_document(db: Session, resource: LearningResource, skill: Skill | None) -> SearchDocument:
    # Matches app.skill_intelligence.resources' candidate-visibility
    # gate: published AND admin-verified (see LearningResource's
    # docstring — "never fabricate resource URLs").
    visibility = "public" if (resource.status == "published" and resource.is_verified) else "private"
    return SearchDocument(
        entity_type=EntityType.LEARNING_RESOURCE,
        entity_id=resource.id,
        title=resource.title,
        description=resource.objective,
        organization=resource.provider,
        category=resource.resource_type,
        skills=normalize_skills(db, [skill.canonical_name]) if skill else None,
        status=resource.status,
        visibility=visibility,
        source="learning_catalog",
        quality_score=(resource.rating or 0.0) / 5.0 if resource.rating else (1.0 if resource.is_verified else 0.0),
        metadata={"url": resource.url, "difficulty": resource.difficulty, "is_free": resource.is_free},
        tags=[t for t in [resource.difficulty, resource.language] if t],
    )
