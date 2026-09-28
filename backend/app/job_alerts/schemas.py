"""V23.3 — request/response shapes for /api/v1/job-alerts*.

Kept separate from app.models.domain (same convention app.search.schemas
already established) so the wire format can evolve independently of
the ORM model.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

FREQUENCIES: tuple[str, ...] = ("INSTANT", "DAILY", "WEEKLY")
REMOTE_PREFERENCES: tuple[str, ...] = ("remote", "hybrid", "onsite", "any")
GOVT_PRIVATE_PREFERENCES: tuple[str, ...] = ("government", "private", "any")


class JobAlertCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    keywords: str | None = Field(default=None, max_length=300)
    job_title: str | None = Field(default=None, max_length=220)
    skills: str | None = None
    location: str | None = Field(default=None, max_length=160)
    remote_preference: str | None = None
    employment_type: str | None = Field(default=None, max_length=40)
    experience_level: str | None = Field(default=None, max_length=120)
    salary_min: float | None = Field(default=None, ge=0)
    salary_max: float | None = Field(default=None, ge=0)
    job_category: str | None = Field(default=None, max_length=100)
    govt_private_preference: str | None = None
    company: str | None = Field(default=None, max_length=220)
    source: str | None = Field(default=None, max_length=60)
    frequency: str = "INSTANT"
    min_relevance_score: int | None = Field(default=None, ge=0, le=100)
    use_profile_personalization: bool = False
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    @field_validator("frequency")
    @classmethod
    def _validate_frequency(cls, v: str) -> str:
        v = (v or "INSTANT").upper()
        if v not in FREQUENCIES:
            raise ValueError(f"frequency must be one of {FREQUENCIES}")
        return v

    @field_validator("remote_preference")
    @classmethod
    def _validate_remote(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.lower()
        if v not in REMOTE_PREFERENCES:
            raise ValueError(f"remote_preference must be one of {REMOTE_PREFERENCES}")
        return v

    @field_validator("govt_private_preference")
    @classmethod
    def _validate_govt_private(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.lower()
        if v not in GOVT_PRIVATE_PREFERENCES:
            raise ValueError(f"govt_private_preference must be one of {GOVT_PRIVATE_PREFERENCES}")
        return v

    @field_validator("salary_max")
    @classmethod
    def _validate_salary_range(cls, v: float | None, info) -> float | None:
        salary_min = info.data.get("salary_min")
        if v is not None and salary_min is not None and v < salary_min:
            raise ValueError("salary_max must be >= salary_min")
        return v


class JobAlertUpdateIn(BaseModel):
    """Every field optional — PATCH semantics (only supplied fields change)."""

    name: str | None = Field(default=None, min_length=1, max_length=160)
    keywords: str | None = None
    job_title: str | None = None
    skills: str | None = None
    location: str | None = None
    remote_preference: str | None = None
    employment_type: str | None = None
    experience_level: str | None = None
    salary_min: float | None = Field(default=None, ge=0)
    salary_max: float | None = Field(default=None, ge=0)
    job_category: str | None = None
    govt_private_preference: str | None = None
    company: str | None = None
    source: str | None = None
    frequency: str | None = None
    min_relevance_score: int | None = Field(default=None, ge=0, le=100)
    use_profile_personalization: bool | None = None
    enabled: bool | None = None

    @field_validator("frequency")
    @classmethod
    def _validate_frequency(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.upper()
        if v not in FREQUENCIES:
            raise ValueError(f"frequency must be one of {FREQUENCIES}")
        return v

    @field_validator("remote_preference")
    @classmethod
    def _validate_remote(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.lower()
        if v not in REMOTE_PREFERENCES:
            raise ValueError(f"remote_preference must be one of {REMOTE_PREFERENCES}")
        return v

    @field_validator("govt_private_preference")
    @classmethod
    def _validate_govt_private(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.lower()
        if v not in GOVT_PRIVATE_PREFERENCES:
            raise ValueError(f"govt_private_preference must be one of {GOVT_PRIVATE_PREFERENCES}")
        return v


class JobAlertOut(BaseModel):
    id: int
    name: str
    keywords: str | None
    job_title: str | None
    skills: str | None
    location: str | None
    remote_preference: str | None
    employment_type: str | None
    experience_level: str | None
    salary_min: float | None
    salary_max: float | None
    job_category: str | None
    govt_private_preference: str | None
    company: str | None
    source: str | None
    frequency: str
    min_relevance_score: int | None
    use_profile_personalization: bool
    enabled: bool
    last_run_at: datetime | None
    last_run_status: str | None
    last_match_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobAlertMatchOut(BaseModel):
    job_id: int
    title: str
    organization: str
    location: str | None
    job_type: str | None
    employment_type: str | None
    salary: str | None
    posted_date: str | None
    relevance_score: int
    match_reasons: list[str]
    already_delivered: bool


class JobAlertRunOut(BaseModel):
    id: int
    started_at: datetime
    completed_at: datetime | None
    status: str
    candidates_scanned: int
    jobs_matched: int
    notifications_created: int
    emails_queued: int
    error_summary: str | None

    model_config = {"from_attributes": True}
