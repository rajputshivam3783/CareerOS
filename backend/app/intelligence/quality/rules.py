"""V25.3 — deterministic data-quality rules (spec section 14).

A rule is a small declarative object: an id, the entity it inspects, a
severity, a human explanation of why it matters, a suggested
remediation, and a SQLAlchemy ``select`` that returns the offending
rows. The runner (``runner.py``) does counting, pagination and
grouping generically, so adding a rule is one entry in ``RULES`` and
no new query-plumbing anywhere.

WHY DECLARATIVE
---------------
Section 14 asks for reusable, extensible rules that do not duplicate
validation logic. Expressing each as a query rather than a Python
predicate over loaded rows means:

- counting is ``SELECT COUNT(*)`` rather than "load the table and
  count in Python", so a rule stays cheap on a large table;
- pagination is ``LIMIT/OFFSET`` on the same statement;
- a rule cannot accidentally mutate anything, because a ``select`` is
  all it is.

NOTHING HERE MODIFIES DATA
--------------------------
Section 13 is explicit that production data must not be changed
without an explicit safe workflow. This module contains no UPDATE,
DELETE or INSERT against any inspected table, and the runner exposes
no "fix" operation. The only writable artifact in the whole
data-quality feature is an administrator's own triage note on an
issue (``DataQualityIssueState``), which records a human decision and
never touches the underlying row.

RELATIONSHIP TO EXISTING VALIDATION
-----------------------------------
These rules detect data that is *already persisted* and wrong or
incomplete. They deliberately do not re-implement request-time
validation (Pydantic schemas on the write endpoints), which prevents
bad data arriving in the first place. The two do different jobs:
Pydantic guards the front door; these rules inspect what is already
in the house, including rows created by ingestion adapters, earlier
schema versions, and imports that predate current validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import Select, and_, func, or_, select

from app.models.domain import Applicant, Application, Job, Profile, Resume, User

SEVERITIES = ("critical", "high", "medium", "low")

# A job untouched for this long that is still sitting in the review
# queue is stale by any reasonable operational standard.
STALE_REVIEW_DAYS = 30
STALE_PUBLISHED_DAYS = 180


@dataclass(frozen=True)
class QualityRule:
    """One deterministic data-quality check."""

    rule_id: str
    entity_type: str  # job | candidate | application | skill
    title: str
    severity: str
    description: str
    remediation: str
    statement: Callable[[], Select]
    # The column used to label an offending row in the issue list.
    label: Callable[[object], str]
    id_attr: str = "id"

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "entity_type": self.entity_type,
            "title": self.title,
            "severity": self.severity,
            "description": self.description,
            "remediation": self.remediation,
        }


def _blank(column):
    """A text column that is NULL or effectively empty."""
    return or_(column.is_(None), func.trim(column) == "")


# Deliberately permissive: this flags values that are clearly not
# usable URLs (no scheme), not values that fail a strict RFC parse.
# A false positive here sends an administrator to inspect a perfectly
# good row, which is a worse outcome than missing an exotic-but-valid
# URL.
_URL_OK_PREFIXES = ("http://", "https://")


def _invalid_url(column):
    return and_(
        column.isnot(None),
        func.trim(column) != "",
        func.lower(column).notlike("http://%"),
        func.lower(column).notlike("https://%"),
    )


def _job_label(job) -> str:
    return f"#{job.id} {job.title}"


def _user_label(user) -> str:
    # Email, not name: an administrator triaging an incomplete profile
    # needs to identify the account, and email is the account
    # identifier already shown throughout the V25.2 admin surface.
    return f"#{user.id} {user.email}"


def _application_label(row) -> str:
    return f"application #{row.id}"


RULES: tuple[QualityRule, ...] = (
    # ---------------- Jobs ----------------
    QualityRule(
        rule_id="job_missing_title",
        entity_type="job",
        title="Job has no title",
        severity="critical",
        description="A job with no title cannot be searched, indexed or meaningfully displayed.",
        remediation="Edit the job to add a title, or reject it if it was ingested in error.",
        statement=lambda: select(Job).where(_blank(Job.title)),
        label=_job_label,
    ),
    QualityRule(
        rule_id="job_missing_description",
        entity_type="job",
        title="Published job has a placeholder or empty description",
        severity="high",
        description=(
            "The description is empty or still the ingestion placeholder, so candidates "
            "cannot tell what the role involves."
        ),
        remediation="Add a real description, or unpublish the listing until one is available.",
        statement=lambda: select(Job).where(
            Job.status == "published",
            or_(_blank(Job.description), func.trim(Job.description) == "See official notification"),
        ),
        label=_job_label,
    ),
    QualityRule(
        rule_id="job_missing_apply_route",
        entity_type="job",
        title="Published job has no way to apply",
        severity="critical",
        description=(
            "The job has no apply URL, no official URL and no CareerOS owner, so a candidate "
            "who opens it has no route to apply at all."
        ),
        remediation="Add an apply or official URL, or assign a recruiter owner for direct applications.",
        statement=lambda: select(Job).where(
            Job.status == "published",
            _blank(Job.apply_url),
            _blank(Job.official_url),
            Job.owner_user_id.is_(None),
        ),
        label=_job_label,
    ),
    QualityRule(
        rule_id="job_invalid_url",
        entity_type="job",
        title="Job has a URL without a valid scheme",
        severity="medium",
        description="An apply, official or notification URL does not begin with http:// or https://.",
        remediation="Correct the URL so it is absolute, or clear it.",
        statement=lambda: select(Job).where(
            or_(_invalid_url(Job.apply_url), _invalid_url(Job.official_url), _invalid_url(Job.notification_url))
        ),
        label=_job_label,
    ),
    QualityRule(
        rule_id="job_invalid_status",
        entity_type="job",
        title="Job has an unrecognized status",
        severity="high",
        description=(
            "The status is not one of the values the moderation workflow understands, so the "
            "job may be invisible to every list that filters by status."
        ),
        remediation="Set the job to a valid status through the moderation screen.",
        statement=lambda: select(Job).where(
            Job.status.notin_(["draft", "review", "published", "rejected", "suspended", "closed", "archived"])
        ),
        label=_job_label,
    ),
    QualityRule(
        rule_id="job_published_without_timestamp",
        entity_type="job",
        title="Published job has no publication timestamp",
        severity="medium",
        description=(
            "The job is published but published_at is empty, so it is excluded from every "
            "time-based analytic and trend."
        ),
        remediation="Republish through the moderation screen, which sets the timestamp.",
        statement=lambda: select(Job).where(Job.status == "published", Job.published_at.is_(None)),
        label=_job_label,
    ),
    QualityRule(
        rule_id="job_stale_in_review",
        entity_type="job",
        title="Job has sat in the review queue too long",
        severity="medium",
        description=f"The job has been awaiting moderation for more than {STALE_REVIEW_DAYS} days.",
        remediation="Approve or reject the job from the moderation queue.",
        statement=lambda: select(Job).where(
            Job.status == "review",
            Job.created_at < datetime.utcnow() - timedelta(days=STALE_REVIEW_DAYS),
        ),
        label=_job_label,
    ),
    QualityRule(
        rule_id="job_published_past_deadline",
        entity_type="job",
        title="Published job is past its application deadline",
        severity="medium",
        description=(
            "The listing is still published although its deadline has passed. Expiry is not an "
            "automatic status change in CareerOS, so these accumulate."
        ),
        remediation="Close the listing, or extend the deadline if it is still open.",
        statement=lambda: select(Job).where(
            Job.status == "published", Job.deadline.isnot(None), Job.deadline < datetime.utcnow().date()
        ),
        label=_job_label,
    ),
    QualityRule(
        rule_id="job_stale_published",
        entity_type="job",
        title="Published job has not been updated in a long time",
        severity="low",
        description=(
            f"The listing has been published for more than {STALE_PUBLISHED_DAYS} days with no "
            "deadline set, so nothing will ever retire it."
        ),
        remediation="Confirm the role is still open, set a deadline, or close the listing.",
        statement=lambda: select(Job).where(
            Job.status == "published",
            Job.deadline.is_(None),
            Job.published_at.isnot(None),
            Job.published_at < datetime.utcnow() - timedelta(days=STALE_PUBLISHED_DAYS),
        ),
        label=_job_label,
    ),
    QualityRule(
        rule_id="job_missing_skills",
        entity_type="job",
        title="Recruiter-owned published job lists no skills",
        severity="low",
        description=(
            "The job specifies no skills, so it contributes nothing to skill demand analytics "
            "and matches poorly against candidate skills."
        ),
        remediation="Add the skills the role actually requires.",
        statement=lambda: select(Job).where(
            Job.status == "published", Job.owner_user_id.isnot(None), _blank(Job.skills)
        ),
        label=_job_label,
    ),
    # ---------------- Candidates ----------------
    QualityRule(
        rule_id="candidate_missing_profile",
        entity_type="candidate",
        title="Active candidate has no profile row",
        severity="medium",
        description=(
            "The account has never saved a profile, so it cannot be matched, recommended to, "
            "or analyzed."
        ),
        remediation="No administrator action — prompt the candidate to complete their profile.",
        statement=lambda: select(User).where(
            User.role == "candidate",
            User.active.is_(True),
            User.id.notin_(select(Profile.user_id)),
        ),
        label=_user_label,
    ),
    QualityRule(
        rule_id="candidate_profile_missing_skills",
        entity_type="candidate",
        title="Candidate profile lists no skills and has no resume",
        severity="low",
        description=(
            "Neither profile skills nor an uploaded resume exist, so CareerOS has no skill data "
            "for this candidate at all."
        ),
        remediation="No administrator action — prompt the candidate to add skills or upload a resume.",
        statement=lambda: select(User)
        .join(Profile, Profile.user_id == User.id)
        .where(
            User.role == "candidate",
            User.active.is_(True),
            _blank(Profile.skills),
            User.id.notin_(select(Resume.user_id)),
        ),
        label=_user_label,
    ),
    QualityRule(
        rule_id="candidate_resume_without_text",
        entity_type="candidate",
        title="Uploaded resume has no extracted text",
        severity="medium",
        description=(
            "Text extraction produced nothing, usually a scanned or image-only document, so "
            "resume matching and skill detection cannot run."
        ),
        remediation="No administrator action — the candidate should re-upload a text-based resume.",
        statement=lambda: select(User)
        .join(Resume, Resume.user_id == User.id)
        .where(_blank(Resume.extracted_text)),
        label=_user_label,
    ),
    # ---------------- Applications ----------------
    QualityRule(
        rule_id="application_orphan_job",
        entity_type="application",
        title="Application references a job that no longer exists",
        severity="high",
        description=(
            "The referenced job row is gone. Foreign keys normally prevent this; rows like these "
            "usually predate the constraint or arrived through a direct import."
        ),
        remediation="Investigate before removing — the application may still be the candidate's record.",
        statement=lambda: select(Applicant).where(Applicant.job_id.notin_(select(Job.id))),
        label=_application_label,
    ),
    QualityRule(
        rule_id="application_orphan_user",
        entity_type="application",
        title="Application references a user that no longer exists",
        severity="high",
        description="The applying user row is gone, leaving an application no one owns.",
        remediation="Investigate before removing.",
        statement=lambda: select(Applicant).where(Applicant.user_id.notin_(select(User.id))),
        label=_application_label,
    ),
    QualityRule(
        rule_id="application_inconsistent_hired_state",
        entity_type="application",
        title="Application is marked hired but its pipeline stage disagrees",
        severity="medium",
        description=(
            "hired_at is set while the pipeline stage is not 'hired', so the hiring funnel and "
            "the applicant record tell different stories."
        ),
        remediation="Correct the pipeline stage, or clear the hired timestamp if it was set in error.",
        statement=lambda: select(Applicant).where(
            Applicant.hired_at.isnot(None), func.coalesce(Applicant.pipeline_stage, "") != "hired"
        ),
        label=_application_label,
    ),
    QualityRule(
        rule_id="application_invalid_stage",
        entity_type="application",
        title="Application has an unrecognized pipeline stage",
        severity="medium",
        description=(
            "The stage is not part of the V24.3 canonical workflow, so the application is "
            "invisible to every stage-filtered pipeline view."
        ),
        remediation="Move the applicant to a valid stage from the pipeline board.",
        statement=lambda: select(Applicant).where(
            Applicant.pipeline_stage.isnot(None),
            Applicant.pipeline_stage.notin_(
                [
                    "new",
                    "reviewing",
                    "shortlisted",
                    "assessment",
                    "interview",
                    "offer",
                    "hired",
                    "rejected",
                    "withdrawn",
                ]
            ),
        ),
        label=_application_label,
    ),
    QualityRule(
        rule_id="tracker_application_orphan_user",
        entity_type="application",
        title="Tracker application references a user that no longer exists",
        severity="medium",
        description="A row in the candidate's private application tracker has no owning user.",
        remediation="Investigate before removing.",
        statement=lambda: select(Application).where(Application.user_id.notin_(select(User.id))),
        label=_application_label,
    ),
)

RULES_BY_ID: dict[str, QualityRule] = {rule.rule_id: rule for rule in RULES}


def duplicate_job_groups_statement() -> Select:
    """Candidate duplicate jobs, grouped rather than row-by-row.

    Duplicates are defined conservatively as **same title + same
    organization**, which is the same pair the V2 ingestion
    deduplication already treats as identical. It is reported as a
    signal for a human to review, never acted on: two genuinely
    different postings can legitimately share a title and an
    employer (different locations, different years), so automatic
    merging here would destroy real listings.
    """
    return (
        select(
            Job.title,
            Job.organization,
            func.count().label("occurrences"),
            func.min(Job.id).label("first_job_id"),
        )
        .where(Job.status.in_(["published", "review"]))
        .group_by(Job.title, Job.organization)
        .having(func.count() > 1)
        .order_by(func.count().desc())
    )


_SKILL_SPLIT_RE = re.compile(r"\s*,\s*")


def job_skill_names(job: Job) -> list[str]:
    if not job.skills:
        return []
    return [part for part in _SKILL_SPLIT_RE.split(job.skills) if part.strip()]
