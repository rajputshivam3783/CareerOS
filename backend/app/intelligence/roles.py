"""V25.3 — target roles (spec section 4).

A "target role" in CareerOS is a job title string. There is no roles
table, and this version does not invent one: a role is resolved to a
*corpus of real published jobs whose titles match it*, and everything
reported about the role is an aggregate over that corpus. If no jobs
match, the answer is "no CareerOS jobs match this role", not a
generated role description.

WHERE A TARGET ROLE MAY COME FROM
---------------------------------
Section 4 allows explicit selection or existing CareerOS data, and
nothing else. In priority order:

1. An explicit ``role`` query parameter the candidate typed or picked.
2. ``CareerPreference.target_role`` — the role the candidate set
   themselves in the V20.3 Career Copilot.
3. ``Profile.preferred_roles`` — the first entry of the roles the
   candidate listed on their own profile.

Never inferred from their resume text, their application history,
their education, or their name. If none of the three is present, the
API says the candidate has not set a target role and offers the
observed-role list to choose from — it does not pick one for them.

ROLE MATCHING
-------------
Substring match on the normalized job title, after the V21.1 title
alias map folds "Sr."/"Senior" and "SWE"/"Software Engineer"
together. Deliberately conservative: a candidate asking about "Data
Analyst" gets jobs whose title contains that phrase, not jobs a
similarity model thought were adjacent. Over-matching here would
silently change what every downstream number means.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.intelligence import corpus as corpus_mod
from app.models.domain import CareerPreference, Job, Profile
from app.search.normalization import normalize_title

# Titles shorter than this match far too much to be a useful role.
MIN_ROLE_QUERY_LENGTH = 3


@dataclass
class TargetRole:
    role: str | None
    source: str  # "explicit" | "career_preference" | "profile_preferred_roles" | "none"

    def as_dict(self) -> dict:
        return {
            "role": self.role,
            "source": self.source,
            "source_description": {
                "explicit": "The role you selected for this view.",
                "career_preference": "Your saved target role from your career preferences.",
                "profile_preferred_roles": "The first role listed in your profile's preferred roles.",
                "none": "You have not set a target role. CareerOS does not infer one for you.",
            }[self.source],
        }


def resolve_target_role(db: Session, user_id: int, explicit: str | None = None) -> TargetRole:
    """Resolve a candidate's target role from allowed sources only."""
    if explicit and len(explicit.strip()) >= MIN_ROLE_QUERY_LENGTH:
        return TargetRole(role=explicit.strip(), source="explicit")

    preference = db.get(CareerPreference, user_id)
    if preference and preference.target_role and preference.target_role.strip():
        return TargetRole(role=preference.target_role.strip(), source="career_preference")

    profile = db.get(Profile, user_id)
    if profile and profile.preferred_roles:
        first = next((part.strip() for part in profile.preferred_roles.split(",") if part.strip()), None)
        if first:
            return TargetRole(role=first, source="profile_preferred_roles")

    return TargetRole(role=None, source="none")


def role_filter(role: str, base: corpus_mod.CorpusFilter | None = None) -> corpus_mod.CorpusFilter:
    """A corpus filter narrowed to one role, preserving other filters."""
    spec = base or corpus_mod.CorpusFilter()
    return corpus_mod.CorpusFilter(
        days=spec.days,
        role_query=normalize_title(role) or role,
        location=spec.location,
        category=spec.category,
        job_type=spec.job_type,
        work_mode=spec.work_mode,
        employment_type=spec.employment_type,
        owner_user_ids=spec.owner_user_ids,
        statuses=spec.statuses,
    )


def observed_roles(db: Session, spec: corpus_mod.CorpusFilter, *, limit: int = 25) -> list[dict]:
    """The role titles that actually exist in the corpus, by volume.

    Grouped on the raw ``jobs.title`` in SQL. Titles are not clustered
    into canonical role families — CareerOS has no role taxonomy, and
    clustering "Senior Backend Engineer" and "Backend Developer"
    together would be a judgement call this layer is not entitled to
    make silently. The result is therefore a title-frequency list,
    named as such.
    """
    query = select(Job.title, func.count()).select_from(Job)
    for clause in corpus_mod._clauses(spec):
        query = query.where(clause)
    rows = db.execute(query.group_by(Job.title).order_by(func.count().desc()).limit(limit)).all()
    return [{"title": title, "job_count": int(count)} for title, count in rows]


def role_titles_matching(db: Session, role: str, spec: corpus_mod.CorpusFilter, *, limit: int = 15) -> list[dict]:
    """The distinct job titles a role query actually matched.

    Returned alongside every role analysis so the candidate can see
    the corpus definition rather than trusting it — if "Analyst"
    pulled in "Financial Analyst" and "Policy Analyst", that is
    visible instead of hidden inside an aggregate.
    """
    return observed_roles(db, role_filter(role, spec), limit=limit)
