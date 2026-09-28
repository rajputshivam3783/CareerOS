"""RETRIEVAL — Stage 1 of the two-stage retrieval+ranking architecture.

Per the spec ("Reuse V21.1 and V21.2 Search Service. Do not create a
separate job database. Use search/index infrastructure for candidate
retrieval"), this narrows the full job set down to a bounded candidate
pool via ``app.search.service.run_search`` — the same permission-aware,
indexed path every other consumer of job data goes through. Stage 2
(app.recommendations.matching/scoring/service) then scores and ranks
only this narrowed pool, never the whole ``jobs`` table.

RBAC / PRIVACY: retrieval always runs with a real ``SearchActor`` built
from the requesting user (never an elevated/admin actor), so a
candidate's recommendations can never include a private/draft/review/
recruiter-owned-by-someone-else job — the exact same visibility rule
V21.1 search already enforces (app.search.permissions.apply_visibility).

``log_analytics=False`` is passed to ``run_search`` deliberately —
recommendation retrieval is not a query the candidate typed, so it
must not appear in their Recent Searches (V21.2) or search analytics,
matching the precedent set in app.search.service's own no-result-
suggestion helper calls.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.domain import Job, RecommendationPreference
from app.recommendations.candidate_features import CandidateFeatures
from app.recommendations.job_features import is_closed_or_unavailable, is_expired
from app.search.document import EntityType
from app.search.permissions import SearchActor
from app.search.provider import SearchFilters
from app.search import service as search_service

_JOB_TYPE_ENTITY_MAP = {
    "include_government": EntityType.GOVERNMENT_RECRUITMENT,
    "include_private": EntityType.JOB,
    "include_internships": EntityType.INTERNSHIP,
    "include_apprenticeships": EntityType.APPRENTICESHIP,
}

RETRIEVAL_POOL_SIZE = 150


def _allowed_entity_types(preferences: RecommendationPreference | None) -> list[EntityType]:
    if preferences is None:
        return list(_JOB_TYPE_ENTITY_MAP.values())
    allowed = []
    for attr, entity_type in _JOB_TYPE_ENTITY_MAP.items():
        if getattr(preferences, attr, True):
            allowed.append(entity_type)
    return allowed or list(_JOB_TYPE_ENTITY_MAP.values())


def _retrieval_query_text(candidate: CandidateFeatures) -> str:
    """Best-effort free-text query built from real candidate signals
    (target role, top skills) — never fabricated. An empty string is a
    valid, honest result for a cold-start candidate with no signals
    yet; the provider's relevance sort still returns a sensible
    (recency-weighted) result set for a blank query."""
    parts: list[str] = []
    if candidate.target_role:
        parts.append(candidate.target_role)
    if candidate.profile_preferred_roles:
        parts.extend(candidate.profile_preferred_roles[:2])
    parts.extend(sorted(candidate.all_skill_tokens)[:6])
    return " ".join(parts).strip()


def retrieve_candidate_pool(db: Session, *, user, candidate: CandidateFeatures) -> list[Job]:
    """Stage 1: return a bounded list of Job rows the candidate is
    authorized to see, narrowed by their real skills/role/location
    signals and recommendation preferences. Stage 2 does all scoring."""
    actor = SearchActor.from_user(user)
    entity_types = _allowed_entity_types(candidate.preferences)

    location = candidate.preferred_location or candidate.profile_location
    filters = SearchFilters(location=location if location and location.lower() not in ("india", "anywhere") else None)

    query_text = _retrieval_query_text(candidate)

    response = search_service.run_search(
        db,
        query=query_text,
        filters=filters,
        entity_types=entity_types,
        page=1,
        page_size=RETRIEVAL_POOL_SIZE,
        sort="relevance" if query_text else "newest",
        actor=actor,
        log_analytics=False,
    )

    job_ids = [item.entity_id for item in response.items]

    # If a location filter over-narrowed the pool (common for a
    # candidate with a specific preferred city), widen once without a
    # location filter rather than returning too few candidates —
    # still bounded by RETRIEVAL_POOL_SIZE, still permission-checked.
    if len(job_ids) < 20 and filters.location:
        widened = search_service.run_search(
            db,
            query=query_text,
            filters=SearchFilters(),
            entity_types=entity_types,
            page=1,
            page_size=RETRIEVAL_POOL_SIZE,
            sort="relevance" if query_text else "newest",
            actor=actor,
            log_analytics=False,
        )
        seen = set(job_ids)
        job_ids.extend(item.entity_id for item in widened.items if item.entity_id not in seen)

    if not job_ids:
        return []

    rows = db.query(Job).filter(Job.id.in_(job_ids)).all()
    by_id = {row.id: row for row in rows}
    ordered = [by_id[jid] for jid in job_ids if jid in by_id]

    # Defensive re-check (EXCLUDED JOBS requirement) — belt-and-braces
    # on top of search visibility, since a stale index row or an
    # explanation/refresh path that re-fetches by id shouldn't surface
    # an expired/closed job even transiently.
    today = date.today()
    return [
        job for job in ordered
        if not is_expired(job, as_of=today)
        and not is_closed_or_unavailable(job)
        and job.id not in candidate.excluded_job_ids
    ]
