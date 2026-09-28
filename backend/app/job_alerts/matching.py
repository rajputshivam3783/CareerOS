"""V23.3 — the Smart Job Alerts matching engine.

Per spec section 6 ("Integrate with V21 search/recommendation
infrastructure. Do NOT create a separate ranking engine"), this module
creates no new scoring model. It is a thin two-stage pipeline over
infrastructure that already exists:

  1. STRUCTURAL CANDIDATE FILTERING — a JobAlert's criteria (keywords,
     title, skills, location, employment type, experience, salary,
     category, company, government/private) are translated into an
     ``app.search.provider.SearchFilters`` and run through the exact
     same ``DatabaseSearchProvider`` (app.search.provider) the
     interactive Search page uses — same visibility rules, same
     candidate cap, same indexed columns. This is also where "new job
     detection" (spec section 10) happens: candidates are filtered to
     ``SearchIndexDocument.created_at > since`` — the moment a job was
     *first indexed*, which does not move on a routine metadata edit
     (only ``indexed_at`` does) — so a job that already matched once
     is never re-surfaced just because it was updated. See
     app.search.hooks for the real-time write-path indexing that keeps
     this column trustworthy.

  2. RELEVANCE SCORING (only over the — already small — structural
     candidate set, never the whole table):
       - use_profile_personalization=True: calls
         app.recommendations.service.get_single_recommendation, the
         same fresh, per-job, per-user scoring V21.3/V21.4's
         "Recommendation Explanation" endpoint uses — a genuine reuse
         of the recommendation engine, not a reimplementation, and it
         naturally brings V21's skill/location/career-goal
         explanations and 0-100 overall_score with it.
       - use_profile_personalization=False (the default — spec: this
         is opt-in): uses app.search.ranking.score_document, the same
         deterministic, explainable, non-AI ranking Search itself
         uses, normalized onto a 0-100 scale for display consistency
         (see _normalize_ranking_score below) — score_document's own
         docstring is explicit that its raw total_score is relative
         and "never shown as an absolute percentage," so this module
         owns the one normalization step rather than exposing that
         internal number directly (spec section 7).

Neither path calls an LLM (spec section 16) — both are deterministic,
so a rerun of the same alert against the same data always reaches the
same verdict, which is what makes deduplication (JobAlertDelivery)
sound in the first place.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.domain import Job, JobAlert, User
from app.recommendations import service as recommendations_service
from app.search.document import JOB_FAMILY_ENTITY_TYPES, EntityType
from app.search.permissions import SearchActor
from app.search.provider import DatabaseSearchProvider, SearchFilters, SearchPage

# Bounds how many structurally-matching candidates get the (heavier)
# relevance-scoring pass per alert run — spec section 26 ("Avoid ...
# duplicate recommendation calculations"). The structural filter
# already narrows this far below "every job in the system"; this is a
# second, hard backstop.
MAX_CANDIDATES_PER_RUN = 200

_provider = DatabaseSearchProvider()


def _entity_types_for(alert: JobAlert) -> list[EntityType]:
    pref = (alert.govt_private_preference or "").lower()
    if pref == "government":
        return [EntityType.GOVERNMENT_RECRUITMENT]
    if pref == "private":
        # Private-sector postings fall back to plain EntityType.JOB in
        # app.search.document._JOB_TYPE_TO_ENTITY_TYPE (anything whose
        # Job.job_type isn't "Government"/"Internship"/"Apprenticeship").
        # Internships/apprenticeships are their own concept and are
        # deliberately excluded from "private" here, same as they're
        # excluded from "government".
        return [EntityType.JOB]
    return list(JOB_FAMILY_ENTITY_TYPES)


def _work_mode_filter(alert: JobAlert) -> str | None:
    pref = (alert.remote_preference or "").lower()
    if pref in ("", "any"):
        return None
    return pref.capitalize()  # "remote" -> "Remote", matching SearchIndexDocument.work_mode's stored casing


def build_filters(alert: JobAlert) -> tuple[str, SearchFilters]:
    """Translate one JobAlert's criteria into a (query_text, SearchFilters)
    pair for app.search.provider — see module docstring, stage 1."""
    query_parts = [p for p in (alert.keywords, alert.job_title) if p and p.strip()]
    query_text = " ".join(query_parts)

    skills = [s.strip() for s in (alert.skills or "").split(",") if s.strip()] or None

    filters = SearchFilters(
        entity_types=_entity_types_for(alert),
        location=alert.location or None,
        organization=alert.company or None,
        category=alert.job_category or None,
        employment_type=alert.employment_type or None,
        work_mode=_work_mode_filter(alert),
        experience=alert.experience_level or None,
        skills=skills,
        salary_min=alert.salary_min,
        salary_max=alert.salary_max,
        status="published",
    )
    return query_text, filters


def _normalize_ranking_score(total_score: float) -> int:
    """0-100 display scale — see module docstring on why this module,
    not app.search.ranking, owns this normalization."""
    return max(0, min(100, round(total_score * 100)))


def _deterministic_match_reasons(query_text: str, alert: JobAlert, doc, factors: dict[str, float]) -> list[str]:
    """Built only from real matching signals actually present on this
    document/query (spec section 17: "Do not invent explanations")."""
    reasons: list[str] = []
    if factors.get("exact_title_match") or factors.get("phrase_match"):
        reasons.append("Job title matches your alert")
    if alert.skills:
        alert_skills = {s.strip().lower() for s in alert.skills.split(",") if s.strip()}
        doc_skills = {s.strip().lower() for s in (doc.skills_text or "").split(",") if s.strip()}
        matched = alert_skills & doc_skills
        if matched:
            reasons.append(f"Matches {len(matched)} of your selected skills ({', '.join(sorted(matched))})")
    if factors.get("location_match"):
        reasons.append("Location matches your alert")
    if factors.get("organization_match"):
        reasons.append("Company matches your alert")
    if not query_text and not reasons:
        reasons.append("Matches your alert's filters")
    return reasons or ["Matches your alert's filters"]


def _personalized_match_reasons(rec) -> list[str]:
    reasons: list[str] = []
    if rec.matched_skills:
        reasons.append(f"Matches {len(rec.matched_skills)} of your profile skills ({', '.join(rec.matched_skills[:6])})")
    if rec.location_fit and rec.location_fit.lower() not in ("unknown", "not specified", ""):
        reasons.append(f"Location fit: {rec.location_fit}")
    if rec.explanation_summary:
        reasons.append(rec.explanation_summary)
    return reasons or ["Strong recommendation score from your CareerOS profile"]


class MatchCandidate:
    __slots__ = ("job_id", "relevance_score", "match_reasons")

    def __init__(self, job_id: int, relevance_score: int, match_reasons: list[str]):
        self.job_id = job_id
        self.relevance_score = relevance_score
        self.match_reasons = match_reasons


def find_matches(
    db: Session, alert: JobAlert, user: User, *, since: datetime | None, limit: int | None = None
) -> tuple[list[MatchCandidate], int]:
    """Runs the two-stage pipeline for one alert. Returns
    (candidates meeting the alert's own min_relevance_score — or all
    scored candidates if none is set — sorted best-first,
    total_structurally_scanned) — the second number is what
    JobAlertRun.candidates_scanned records (spec section 19).

    ``since=None`` skips the new-job-detection filter entirely — used
    by the alert creation form's live preview (spec section 5:
    "Example jobs that match this alert... use real existing jobs")
    and by GET .../matches, neither of which is a delivery run and so
    has no "since the last run" to measure from."""
    query_text, filters = build_filters(alert)
    result = _provider.search(
        db,
        query=query_text,
        filters=filters,
        actor=SearchActor.anonymous(),  # alerts only ever surface publicly visible jobs — see module docstring
        page=SearchPage(page=1, page_size=MAX_CANDIDATES_PER_RUN),
        sort="newest",
    )

    # New-job detection (spec section 10) — see module docstring.
    new_candidates = [sd for sd in result.items if since is None or sd.document.created_at > since]

    # Optional free-text `source` criterion — not an indexed
    # SearchFilters field (see app.search.provider.SearchFilters);
    # applied here as a cheap in-memory filter over the already-bounded
    # candidate set rather than widening a shared V21.1 dataclass for
    # one V23.3-specific field.
    if alert.source:
        source_norm = alert.source.strip().lower()
        new_candidates = [sd for sd in new_candidates if (sd.document.source or "").strip().lower() == source_norm]

    scanned = len(new_candidates)
    candidates: list[MatchCandidate] = []

    for sd in new_candidates:
        doc = sd.document
        if alert.use_profile_personalization and doc.entity_type in {e.value for e in JOB_FAMILY_ENTITY_TYPES}:
            job = db.get(Job, doc.entity_id)
            rec = recommendations_service.get_single_recommendation(db, user, doc.entity_id) if job else None
            if rec is None:
                continue  # job closed/expired/unavailable since indexing — get_single_recommendation already checked this
            score = rec.overall_score
            reasons = _personalized_match_reasons(rec)
        else:
            score = _normalize_ranking_score(sd.score)
            reasons = _deterministic_match_reasons(query_text, alert, doc, sd.factors)

        if alert.min_relevance_score is not None and score < alert.min_relevance_score:
            continue

        candidates.append(MatchCandidate(job_id=doc.entity_id, relevance_score=score, match_reasons=reasons))

    candidates.sort(key=lambda c: c.relevance_score, reverse=True)
    if limit is not None:
        candidates = candidates[:limit]
    return candidates, scanned
