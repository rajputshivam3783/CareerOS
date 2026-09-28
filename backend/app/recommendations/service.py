"""RECOMMENDATION ARCHITECTURE — the one orchestrator.

V21.4 PERSONALIZED RANKING pipeline (extends V21.3's):

    Candidate Retrieval -> Base Match Score -> Personalization Signals
    -> Behavioral Signals -> Freshness -> Deadline Urgency -> Diversity
    -> Final Ranking

"Base Match Score" and "Personalization Signals" (career goal,
location, work mode, skills, resume, education) are computed together
in one pass by app.recommendations.matching.compute (they were already
the V21.3 pipeline); "Behavioral Signals" is the new `behavior`
component (app.recommendations.signals); "Freshness" is the existing
`recency` component; "Deadline Urgency" is the new
`deadline_urgency` component; "Diversity" is
app.recommendations.diversity's post-ranking reorder, unchanged in
position, extended in what it diversifies across.

``get_recommendations`` remains the single entry point every API
endpoint should call — mirroring app.search.service.run_search's role
for V21.1. See RECOMMENDATION_ARCHITECTURE.md /
PERSONALIZATION_ARCHITECTURE.md / RANKING_ENGINE_V21_4.md for the full
pipeline diagrams and rules referenced below.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.domain import Job, Profile, RecommendationPreference, User
from app.recommendations import (
    cache,
    candidate_features,
    cold_start,
    diversity,
    experiments,
    explanations,
    government,
    job_features,
    matching,
    ranking_config,
    retrieval,
    scoring,
    signals as signals_service,
)

DEFAULT_LIMIT = 20
MAX_RANKING_POOL = 200


@dataclass
class RankedRecommendation:
    job_id: int
    title: str
    organization: str
    job_type: str
    location: str
    salary: str | None
    employment_type: str | None
    work_mode: str | None
    deadline: str | None
    notification_url: str | None
    apply_url: str | None
    posted_date: str

    overall_score: int
    category: str
    category_tags: list[str]
    eligibility_bucket: str
    score_breakdown: dict[str, int]
    unavailable_components: list[str]

    explanation_summary: str
    matched_skills: list[str]
    missing_skills: list[str]
    missing_skills_in_progress: list[str]
    experience_fit: str
    location_fit: str
    career_goal_fit: str
    negative_reasons: list[str]

    already_saved: bool
    already_applied: bool

    government_relevance: dict | None = None

    # V21.4 — PERSONALIZED RANKING / EXPLAINABILITY
    personalized_match: bool = False
    personalization_reasons: list[str] = field(default_factory=list)


@dataclass
class RecommendationsResult:
    items: list[RankedRecommendation]
    total_before_limit: int
    is_cold_start: bool
    from_cache: bool
    generated_at: str
    personalization_enabled: bool = True
    experiment_variant: str | None = None


def _rank_pool(
    db: Session,
    user: User,
    candidate,
    pool: list[Job],
    behavior: signals_service.BehaviorSignals | None,
) -> list[RankedRecommendation]:
    profile = db.get(Profile, user.id)
    weights_config = ranking_config.get(db, "component_weights")
    scored: list[tuple[int, RankedRecommendation]] = []

    for job in pool:
        if job.id in candidate.excluded_job_ids:
            continue
        jf = job_features.build(job)
        match = matching.compute(candidate, job, jf, behavior=behavior)
        score_result = scoring.score(match, jf, db, weights_config)
        category_result = scoring.classify(score_result, match, jf)
        exp = explanations.explain(jf, match, score_result)
        bucket = scoring.eligibility_bucket(
            match.skill.score if match.skill.available else None, len(match.missing_skills)
        )
        gov = None
        if jf.is_government:
            relevance = government.assess(job, profile)
            gov = asdict(relevance)

        item = RankedRecommendation(
            job_id=job.id,
            title=job.title,
            organization=job.organization,
            job_type=job.job_type,
            location=job.location,
            salary=job.salary,
            employment_type=job.employment_type,
            work_mode=job.work_mode,
            deadline=job.deadline.isoformat() if job.deadline else None,
            notification_url=job.notification_url,
            apply_url=job.apply_url,
            posted_date=job.created_at.isoformat(),
            overall_score=score_result.overall,
            category=category_result.primary,
            category_tags=category_result.tags,
            eligibility_bucket=bucket,
            score_breakdown=score_result.breakdown,
            unavailable_components=score_result.unavailable_components,
            explanation_summary=exp.summary,
            matched_skills=exp.matched_skills,
            missing_skills=exp.missing_skills,
            missing_skills_in_progress=exp.missing_skills_in_progress,
            experience_fit=exp.experience_fit,
            location_fit=exp.location_fit,
            career_goal_fit=exp.career_goal_fit,
            negative_reasons=exp.negative_reasons,
            already_saved=job.id in candidate.saved_job_ids,
            already_applied=job.id in candidate.applied_job_ids,
            government_relevance=gov,
            personalized_match=exp.personalized_match,
            personalization_reasons=exp.personalization_reasons,
        )
        scored.append((job.id, item))

    scored.sort(key=lambda pair: pair[1].overall_score, reverse=True)
    scored = diversity.dedupe_by_job_id(scored)

    diversity_level = candidate.preferences.diversity_level if candidate.preferences else "balanced"
    keys = {
        job_id: diversity.DiversityKey(
            company=item.organization,
            location=item.location,
            title=item.title,
            opportunity_type=item.job_type,
        )
        for job_id, item in scored
    }
    diversified = diversity.apply_diversity(scored, keys, level=diversity_level, limit=len(scored))
    return [item for _job_id, item in diversified]


def _serialize(result: RecommendationsResult) -> str:
    return json.dumps({
        "items": [asdict(item) for item in result.items],
        "total_before_limit": result.total_before_limit,
        "is_cold_start": result.is_cold_start,
        "generated_at": result.generated_at,
        "personalization_enabled": result.personalization_enabled,
    })


def _deserialize(raw: str) -> RecommendationsResult:
    data = json.loads(raw)
    items = [RankedRecommendation(**row) for row in data["items"]]
    return RecommendationsResult(
        items=items,
        total_before_limit=data["total_before_limit"],
        is_cold_start=data["is_cold_start"],
        from_cache=True,
        generated_at=data["generated_at"],
        personalization_enabled=data.get("personalization_enabled", True),
    )


def get_recommendations(
    db: Session,
    user: User,
    *,
    limit: int = DEFAULT_LIMIT,
    category: str | None = None,
    force_refresh: bool = False,
) -> RecommendationsResult:
    """Stage 0 through Ranking, with the REFRESH/PERFORMANCE cache
    layer in front. ``category`` (optional) filters the already-ranked
    list to one of the RECOMMENDATION CATEGORIES tags — it never
    changes the underlying scoring or triggers a fresh recompute."""
    signature = cache.compute_signature(db, user.id)

    cached_result: RecommendationsResult | None = None
    if not force_refresh:
        snapshot = cache.get_fresh_snapshot(db, user.id, signature)
        if snapshot is not None:
            cached_result = _deserialize(snapshot.results_json)

    if cached_result is None:
        candidate = candidate_features.build(db, user.id)
        pool = retrieval.retrieve_candidate_pool(db, user=user, candidate=candidate)

        if candidate.is_cold_start:
            existing_ids = {job.id for job in pool} | candidate.excluded_job_ids
            pool = pool + cold_start.popular_verified_jobs(db, exclude_job_ids=existing_ids)

        pool = pool[:MAX_RANKING_POOL]

        # USER CONTROLS — Personalized Recommendations ON/OFF. When
        # off, `behavior` stays None, so app.recommendations.matching's
        # "behavior" component reports itself unavailable for every
        # job (redistributed like any other missing signal) — every
        # other component (skill/resume/career-goal/location/etc,
        # which are explicit *stated* preferences, not learned
        # behavior) is unaffected.
        prefs = db.get(RecommendationPreference, user.id)
        personalization_enabled = prefs.personalization_enabled if prefs is not None else True
        behavior = signals_service.build(db, user.id) if personalization_enabled else None

        ranked_items = _rank_pool(db, user, candidate, pool, behavior)

        cached_result = RecommendationsResult(
            items=ranked_items,
            total_before_limit=len(ranked_items),
            is_cold_start=candidate.is_cold_start,
            from_cache=False,
            generated_at=datetime.utcnow().isoformat(),
            personalization_enabled=personalization_enabled,
        )
        cache.save_snapshot(db, user.id, signature, _serialize(cached_result))
    else:
        cached_result.from_cache = True

    items = cached_result.items
    if category:
        items = [item for item in items if category in item.category_tags]

    # A/B TESTING FOUNDATION — tag which variant (if any active
    # experiment applies) this response corresponds to, purely for
    # future metrics grouping. Ranking itself is never branched on this
    # in V21.4 (see app.recommendations.experiments's docstring).
    experiment_variant = None
    active_experiment = experiments.get_active_experiment(db)
    if active_experiment is not None:
        experiment_variant = experiments.assign_variant(user.id, active_experiment)

    return RecommendationsResult(
        items=items[:limit],
        total_before_limit=len(items),
        is_cold_start=cached_result.is_cold_start,
        from_cache=cached_result.from_cache,
        generated_at=cached_result.generated_at,
        personalization_enabled=cached_result.personalization_enabled,
        experiment_variant=experiment_variant,
    )


def get_single_recommendation(db: Session, user: User, job_id: int) -> RankedRecommendation | None:
    """RECOMMENDATION EXPLANATION endpoint support — scores exactly one
    job fresh (never cached), so a candidate can always see a current,
    literal explanation for a specific job even if their cached list
    hasn't refreshed yet."""
    job = db.get(Job, job_id)
    if job is None or job_features.is_closed_or_unavailable(job) or job_features.is_expired(job):
        return None
    candidate = candidate_features.build(db, user.id)
    prefs = db.get(RecommendationPreference, user.id)
    personalization_enabled = prefs.personalization_enabled if prefs is not None else True
    behavior = signals_service.build(db, user.id) if personalization_enabled else None
    results = _rank_pool(db, user, candidate, [job], behavior)
    return results[0] if results else None
