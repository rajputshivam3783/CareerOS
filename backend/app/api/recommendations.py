"""V21.3/V21.4 — AI Job Recommendation Engine + Advanced
Personalization & Intelligent Ranking APIs.

Mounted at ``/job-recommendations`` deliberately: ``GET /recommendations``
already exists (V6, app.api.platform) and ``GET /career-copilot/recommendations``
already exists (V20.3). Neither is touched, replaced, or called by this
module. This is the full "Jobs For You" engine described in
RECOMMENDATION_ARCHITECTURE.md/PERSONALIZATION_ARCHITECTURE.md.

AUTHORIZATION: every candidate-facing endpoint here operates on the
calling user's own data only via ``current_user`` — no endpoint accepts
another user's id (PRIVACY & SECURITY requirement). Admin endpoints are
``admin_guard``-gated and return aggregate data only — never per-user
recommendation content or raw behavioral history (RECOMMENDATION_PRIVACY.md,
PERSONALIZATION_PRIVACY.md).

V21.4 additions (all additive — every V21.3 endpoint/response shape
above is unchanged):
    GET/PUT  /job-recommendations/personalization        (USER CONTROLS)
    POST     /job-recommendations/reset                  (reset stated preferences)
    POST     /job-recommendations/clear-history           (clear learned behavior)
    POST     /job-recommendations/events                  (generic event: filter_usage, share, etc.)
    GET/PUT  /job-recommendations/admin/ranking-config     (RANKING CONFIGURATION, admin-only)
    GET/POST/PUT /job-recommendations/admin/experiments    (A/B TESTING FOUNDATION, admin-only)
"""

from __future__ import annotations

import time
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.observability import live_provider_health
from app.api.admin import guard as admin_guard
from app.core.security import current_user
from app.db.session import get_db
from app.models.domain import RankingExperiment, RecommendationEvent, RecommendationPreference, User
from app.recommendations import controls as controls_service
from app.recommendations import events as events_service
from app.recommendations import feedback as feedback_service
from app.recommendations import preferences as preferences_service
from app.recommendations import ranking_config
from app.recommendations import service as recommendation_service

router = APIRouter()

VALID_CATEGORIES = {
    "Best Match", "Strong Match", "Skill-Building Opportunity",
    "Career Growth Opportunity", "Recently Posted Match", "Deadline Approaching", "Potential Match",
}


class FeedbackRequest(BaseModel):
    feedback_type: str = Field(..., description="interested | not_interested | dismiss | not_relevant")


class EventRequest(BaseModel):
    event_type: str = Field(..., description="impression | open | save | apply | dismiss | not_relevant | share")


class GenericEventRequest(BaseModel):
    """V21.4 — for event types not tied to a single job in the URL
    path (filter_usage, feed_view) or where the caller doesn't already
    have a job-scoped endpoint handy (share). ``filters`` is optional,
    short, structured metadata only (e.g. which filter dimension
    changed) — never free-text search queries (see app.recommendations.events)."""

    event_type: str = Field(..., description="filter_usage | share | feed_view | any job-linked type")
    job_id: int | None = None
    filters: dict | None = None


class PreferencesRequest(BaseModel):
    include_government: bool | None = None
    include_private: bool | None = None
    include_internships: bool | None = None
    include_apprenticeships: bool | None = None
    preferred_employment_types: list[str] | None = None
    diversity_level: str | None = Field(default=None, description="low | balanced | high")


class PersonalizationRequest(BaseModel):
    personalization_enabled: bool


class RankingConfigRequest(BaseModel):
    value: object


class ExperimentRequest(BaseModel):
    experiment_key: str
    name: str
    variants: dict[str, float] = Field(description='e.g. {"control": 50, "variant_b": 50}')
    status: str = Field(default="draft", description="draft | active | stopped")


def _preferences_out(pref: RecommendationPreference) -> dict:
    return {
        "include_government": pref.include_government,
        "include_private": pref.include_private,
        "include_internships": pref.include_internships,
        "include_apprenticeships": pref.include_apprenticeships,
        "preferred_employment_types": (pref.preferred_employment_types or "").split(",") if pref.preferred_employment_types else [],
        "diversity_level": pref.diversity_level,
        "personalization_enabled": pref.personalization_enabled,
    }


def _result_out(result) -> dict:
    return {
        "items": [asdict(item) for item in result.items],
        "total_before_limit": result.total_before_limit,
        "is_cold_start": result.is_cold_start,
        "from_cache": result.from_cache,
        "generated_at": result.generated_at,
        "personalization_enabled": result.personalization_enabled,
    }


@router.get("/job-recommendations")
def list_recommendations(
    limit: int = Query(default=20, ge=1, le=50),
    category: str | None = Query(default=None),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
    u: User = Depends(current_user),
):
    """"Jobs For You" — the main recommendation feed."""
    if category and category not in VALID_CATEGORIES:
        raise HTTPException(400, f"Unknown category. Expected one of {sorted(VALID_CATEGORIES)}")

    started = time.perf_counter()
    result = recommendation_service.get_recommendations(db, u, limit=limit, category=category, force_refresh=refresh)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    experiment_variant = result.experiment_variant

    # PERFORMANCE: batch every impression from this one feed response
    # into a single commit rather than one round-trip per item (see
    # app.recommendations.events's commit=False docstring).
    for item in result.items:
        events_service.record_event(
            db, user_id=u.id, job_id=item.job_id, event_type="impression",
            experiment_variant=experiment_variant, commit=False,
        )
    # ADMIN metrics: one synthetic "feed_view" event per request,
    # carrying result count + latency for no-result-rate/latency
    # reporting — never a per-job row, never candidate-authored text.
    events_service.record_event(
        db, user_id=u.id, event_type="feed_view",
        filters={"result_count": len(result.items), "latency_ms": latency_ms},
        experiment_variant=experiment_variant, commit=False,
    )
    db.commit()

    return _result_out(result)


@router.post("/job-recommendations/refresh")
def refresh_recommendations(
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    u: User = Depends(current_user),
):
    """REFRESH — force a recompute, bypassing the cached snapshot."""
    result = recommendation_service.get_recommendations(db, u, limit=limit, force_refresh=True)
    return _result_out(result)


@router.get("/job-recommendations/{job_id}/explanation")
def get_explanation(job_id: int, db: Session = Depends(get_db), u: User = Depends(current_user)):
    """RECOMMENDATION EXPLANATION — always scored fresh for this one
    job. Response includes V21.4's ``personalized_match``/
    ``personalization_reasons`` ("Why This Job" / "Personalized Match" /
    "Recommended Because" in the frontend)."""
    item = recommendation_service.get_single_recommendation(db, u, job_id)
    if item is None:
        raise HTTPException(404, "Job not found, expired, closed, or you don't have access to it")
    feedback_service.record_event(db, user_id=u.id, job_id=job_id, event_type="open")
    return asdict(item)


@router.post("/job-recommendations/{job_id}/feedback")
def submit_feedback(job_id: int, body: FeedbackRequest, db: Session = Depends(get_db), u: User = Depends(current_user)):
    """FEEDBACK LOOP — Interested / Not Interested / Dismiss / Not
    Relevant. Save/Apply are recorded via the existing SavedJob/
    Application endpoints and only logged here as an analytics+
    personalization event (see POST /job-recommendations/events) —
    this endpoint does not create a saved-job or application row."""
    try:
        row = feedback_service.record_feedback(db, user_id=u.id, job_id=job_id, feedback_type=body.feedback_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"job_id": row.job_id, "feedback_type": row.feedback_type, "updated_at": row.updated_at.isoformat()}


@router.post("/job-recommendations/{job_id}/event")
def submit_event(job_id: int, body: EventRequest, db: Session = Depends(get_db), u: User = Depends(current_user)):
    """ANALYTICS + BEHAVIORAL SIGNALS — impression/open/save/apply/
    share signal for CTR/conversion reporting and (for everything but
    impression) the learned personalization profile. Does not touch
    SavedJob/Application/RecommendationFeedback."""
    try:
        events_service.record_event(db, user_id=u.id, job_id=job_id, event_type=body.event_type)
    except events_service.EventValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@router.post("/job-recommendations/events")
def submit_generic_event(body: GenericEventRequest, db: Session = Depends(get_db), u: User = Depends(current_user)):
    """V21.4 — BEHAVIORAL SIGNALS for events not scoped to a single job
    in the URL: ``filter_usage`` (``filters`` should be a short dict
    like ``{"dimension": "location"}``), ``share``, or any job-linked
    type where the caller prefers a body-only request."""
    try:
        events_service.record_event(
            db, user_id=u.id, job_id=body.job_id, event_type=body.event_type, filters=body.filters,
        )
    except events_service.EventValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@router.get("/job-recommendations/preferences")
def get_preferences(db: Session = Depends(get_db), u: User = Depends(current_user)):
    return _preferences_out(preferences_service.get_or_default(db, u.id))


@router.put("/job-recommendations/preferences")
def update_preferences(body: PreferencesRequest, db: Session = Depends(get_db), u: User = Depends(current_user)):
    try:
        row = preferences_service.update(
            db, u.id,
            include_government=body.include_government,
            include_private=body.include_private,
            include_internships=body.include_internships,
            include_apprenticeships=body.include_apprenticeships,
            preferred_employment_types=body.preferred_employment_types,
            diversity_level=body.diversity_level,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _preferences_out(row)


@router.get("/job-recommendations/personalization")
def get_personalization(db: Session = Depends(get_db), u: User = Depends(current_user)):
    """V21.4 USER CONTROLS — "Personalized Recommendations ON/OFF",
    plus an honest, non-raw summary of what's currently influencing
    the candidate's feed (PRIVACY: "Do not expose raw behavioral
    history unnecessarily" — categorized top signals only, never raw
    event rows or scores)."""
    pref = preferences_service.get_or_default(db, u.id)
    top_signals: dict[str, list[str]] = {}
    if pref.personalization_enabled:
        from app.recommendations import signals as signals_service
        behavior = signals_service.build(db, u.id)
        for signal_type in ("skill", "company", "location", "job_type", "role_keyword"):
            top = behavior.top_positive(signal_type)
            if top:
                top_signals[signal_type] = top
    return {
        "personalization_enabled": pref.personalization_enabled,
        "top_signals": top_signals,
    }


@router.put("/job-recommendations/personalization")
def update_personalization(body: PersonalizationRequest, db: Session = Depends(get_db), u: User = Depends(current_user)):
    row = preferences_service.update(db, u.id, personalization_enabled=body.personalization_enabled)
    return _preferences_out(row)


@router.post("/job-recommendations/reset")
def reset_preferences(db: Session = Depends(get_db), u: User = Depends(current_user)):
    """USER CONTROLS — "Reset Recommendation Preferences": reverts
    stated settings (opportunity-type filters, diversity level,
    personalization toggle) to defaults. Learned behavior and per-job
    feedback are untouched — see POST /job-recommendations/clear-history."""
    row = preferences_service.reset_to_defaults(db, u.id)
    return _preferences_out(row)


@router.post("/job-recommendations/clear-history")
def clear_history(db: Session = Depends(get_db), u: User = Depends(current_user)):
    """USER CONTROLS — "Clear Recommendation History": deletes this
    candidate's learned behavioral signals and raw event history.
    Explicit per-job dismiss/not-relevant verdicts are untouched (those
    are intentional, not inferred — see app.recommendations.controls)."""
    return controls_service.clear_behavior_history(db, u.id)


@router.get("/job-recommendations/analytics", dependencies=[Depends(admin_guard)])
def recommendation_analytics(db: Session = Depends(get_db)):
    """ANALYTICS — admin-only, aggregate counts/rates only. No
    per-user content or individual behavioral profile is ever
    returned (PERSONALIZATION_PRIVACY.md)."""
    rows = db.execute(
        select(RecommendationEvent.event_type, func.count()).group_by(RecommendationEvent.event_type)
    ).all()
    counts = {event_type: count for event_type, count in rows}
    impressions = counts.get("impression", 0)
    opens = counts.get("open", 0)
    applies = counts.get("apply", 0)
    saves = counts.get("save", 0)
    dismisses = counts.get("dismiss", 0) + counts.get("not_relevant", 0)

    feed_views = db.scalars(
        select(RecommendationEvent.filters_json).where(RecommendationEvent.event_type == "feed_view").limit(5000)
    ).all()
    result_counts: list[int] = []
    latencies: list[float] = []
    import json as _json
    for raw in feed_views:
        if not raw:
            continue
        try:
            payload = _json.loads(raw)
        except (ValueError, TypeError):
            continue
        if "result_count" in payload:
            result_counts.append(payload["result_count"])
        if "latency_ms" in payload:
            latencies.append(payload["latency_ms"])
    no_result_rate = (
        round(sum(1 for c in result_counts if c == 0) / len(result_counts), 4) if result_counts else None
    )
    avg_latency_ms = round(sum(latencies) / len(latencies), 1) if latencies else None

    variant_rows = db.execute(
        select(RecommendationEvent.experiment_variant, RecommendationEvent.event_type, func.count())
        .where(RecommendationEvent.experiment_variant.is_not(None))
        .group_by(RecommendationEvent.experiment_variant, RecommendationEvent.event_type)
    ).all()
    by_variant: dict[str, dict[str, int]] = {}
    for variant, event_type, count in variant_rows:
        by_variant.setdefault(variant, {})[event_type] = count

    return {
        "counts_by_event_type": counts,
        "click_through_rate": round(opens / impressions, 4) if impressions else None,
        "save_rate": round(saves / impressions, 4) if impressions else None,
        "apply_rate": round(applies / impressions, 4) if impressions else None,
        "dismiss_rate": round(dismisses / impressions, 4) if impressions else None,
        "application_conversion_rate": round(applies / impressions, 4) if impressions else None,
        "no_result_rate": no_result_rate,
        "no_result_rate_sample_size": len(result_counts),
        "avg_ranking_latency_ms": avg_latency_ms,
        "ranking_latency_sample_size": len(latencies),
        "experiment_breakdown": by_variant,
        "llm_dependency": "none — core ranking is fully deterministic (see RANKING_ENGINE_V21_4.md)",
        "ai_provider_health": live_provider_health(),
    }


@router.get("/job-recommendations/admin/ranking-config", dependencies=[Depends(admin_guard)])
def get_ranking_config(db: Session = Depends(get_db)):
    """RANKING CONFIGURATION — admin-only. Never exposed to normal
    candidates (spec: "Do NOT expose dangerous internal configuration
    directly to normal users")."""
    return ranking_config.get_all_effective(db)


@router.put("/job-recommendations/admin/ranking-config/{config_key}", dependencies=[Depends(admin_guard)])
def set_ranking_config(config_key: str, body: RankingConfigRequest, db: Session = Depends(get_db)):
    try:
        row = ranking_config.set_value(db, config_key, body.value)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"config_key": row.config_key, "value": ranking_config.get(db, row.config_key), "updated_at": row.updated_at.isoformat()}


@router.post("/job-recommendations/admin/ranking-config/reset", dependencies=[Depends(admin_guard)])
def reset_ranking_config(db: Session = Depends(get_db)):
    ranking_config.reset_to_defaults(db)
    return ranking_config.get_all_effective(db)


@router.get("/job-recommendations/admin/experiments", dependencies=[Depends(admin_guard)])
def list_experiments(db: Session = Depends(get_db)):
    """A/B TESTING FOUNDATION — admin-only. See
    app.recommendations.experiments for why this is safe-by-default
    (dormant unless explicitly activated, deterministic assignment)."""
    import json as _json
    rows = db.scalars(select(RankingExperiment)).all()
    return [
        {
            "id": r.id, "experiment_key": r.experiment_key, "name": r.name, "status": r.status,
            "variants": _json.loads(r.variants_json), "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/job-recommendations/admin/experiments", dependencies=[Depends(admin_guard)])
def create_experiment(body: ExperimentRequest, db: Session = Depends(get_db)):
    import json as _json
    if body.status not in {"draft", "active", "stopped"}:
        raise HTTPException(400, "status must be one of draft/active/stopped")
    existing = db.scalar(select(RankingExperiment).where(RankingExperiment.experiment_key == body.experiment_key))
    if existing is not None:
        raise HTTPException(409, f"Experiment '{body.experiment_key}' already exists")
    row = RankingExperiment(
        experiment_key=body.experiment_key, name=body.name, status=body.status,
        variants_json=_json.dumps(body.variants),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "experiment_key": row.experiment_key, "status": row.status}


@router.put("/job-recommendations/admin/experiments/{experiment_key}/status", dependencies=[Depends(admin_guard)])
def set_experiment_status(experiment_key: str, status: str = Query(...), db: Session = Depends(get_db)):
    if status not in {"draft", "active", "stopped"}:
        raise HTTPException(400, "status must be one of draft/active/stopped")
    row = db.scalar(select(RankingExperiment).where(RankingExperiment.experiment_key == experiment_key))
    if row is None:
        raise HTTPException(404, "Experiment not found")
    if status == "active":
        # "At most one experiment active at a time" — deactivate any
        # other active experiment first so ranking-event tagging never
        # has to choose between two simultaneously "active" rows.
        others = db.scalars(select(RankingExperiment).where(RankingExperiment.status == "active")).all()
        for other in others:
            other.status = "stopped"
    row.status = status
    db.commit()
    return {"experiment_key": row.experiment_key, "status": row.status}
