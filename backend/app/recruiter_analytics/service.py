"""V24.4 — deterministic recruiter analytics. No LLM calls anywhere in
this module — every number here is a real aggregate over
``applicants``/``recruiter_pipeline_history``/``interviews``/
``offer_letters``, or explicitly ``None`` when the underlying event
isn't tracked at all (see ``UNTRACKED_METRICS`` below). This is the
source of truth ``app.recruiter_analytics.ai`` explains — it never
recomputes or overrides anything decided here.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import PIPELINE_STAGES, PIPELINE_TERMINAL_STAGES
from app.models.domain import Applicant, Interview, Job, OfferLetter, RecruiterPipelineHistory
from app.recruiter_pipeline import service as pipeline_service

# Spec section 3: "job views / apply clicks / source" are only
# reportable if actually tracked. None of the three is tracked
# anywhere in this schema (confirmed: no PageView/ClickEvent/
# ApplicationSource table or column exists) — so every endpoint below
# reports these under this exact key set with a value of ``None``
# rather than a fabricated number, and the frontend renders that as
# "Not tracked", never as "0".
UNTRACKED_METRICS = {"job_views": None, "apply_clicks": None, "application_conversion_pct": None, "source_breakdown": None}


def _my_jobs(db: Session, owner_ids: list[int]) -> list[Job]:
    return db.scalars(select(Job).where(Job.owner_user_id.in_(owner_ids))).all()


def _applicants_for_jobs(db: Session, job_ids: list[int]) -> list[Applicant]:
    if not job_ids:
        return []
    return db.scalars(select(Applicant).where(Applicant.job_id.in_(job_ids))).all()


def overview(db: Session, owner_ids: list[int], *, stale_threshold_days: int = pipeline_service.DEFAULT_STALE_THRESHOLD_DAYS, now: datetime | None = None) -> dict:
    """Spec section 1.A. Every count is `PIPELINE_STAGES`-keyed except
    `stale`, which is computed once per job via the same
    ``recruiter_pipeline.service.stale_candidates`` the per-job
    endpoints use (never a second staleness definition)."""
    now = now or datetime.utcnow()
    jobs = _my_jobs(db, owner_ids)
    job_ids = [j.id for j in jobs]
    applicants = _applicants_for_jobs(db, job_ids)

    stage_counts = {stage: 0 for stage in PIPELINE_STAGES}
    for a in applicants:
        stage_counts[a.pipeline_stage or "new"] = stage_counts.get(a.pipeline_stage or "new", 0) + 1

    stale_total = 0
    by_job_applicants: dict[int, list[Applicant]] = defaultdict(list)
    for a in applicants:
        by_job_applicants[a.job_id].append(a)
    for job in jobs:
        stale_total += len(
            pipeline_service.stale_candidates(db, job.id, by_job_applicants.get(job.id, []), threshold_days=stale_threshold_days, now=now)
        )

    return {
        "total_jobs": len(jobs),
        "active_jobs": sum(1 for j in jobs if j.status == "published"),
        "published_jobs": sum(1 for j in jobs if j.status == "published"),
        "total_applications": len(applicants),
        "new_applications": stage_counts.get("new", 0),
        "candidates_reviewing": stage_counts.get("reviewing", 0),
        "candidates_shortlisted": stage_counts.get("shortlisted", 0),
        "candidates_assessment": stage_counts.get("assessment", 0),
        "candidates_interview": stage_counts.get("interview", 0),
        "offers": stage_counts.get("offer", 0),
        "hired": stage_counts.get("hired", 0),
        "rejected": stage_counts.get("rejected", 0),
        "withdrawn": stage_counts.get("withdrawn", 0),
        "stale_candidates": stale_total,
        "stale_threshold_days": stale_threshold_days,
    }


def applications_over_time(db: Session, owner_ids: list[int], *, days: int = 30, job_id: int | None = None, now: datetime | None = None) -> dict:
    """Spec section 1.B. Real daily counts of `Applicant.created_at`,
    zero-filled for days with no applications (a real "0 that day" is
    not the same thing as "fake data" — the spec's actual concern,
    per section 20's framing, is inventing history that never
    happened; a day with genuinely no applications reporting 0 is
    exactly what happened)."""
    now = now or datetime.utcnow()
    jobs = _my_jobs(db, owner_ids)
    job_ids = [job_id] if job_id is not None else [j.id for j in jobs]
    applicants = _applicants_for_jobs(db, job_ids)

    start = (now - timedelta(days=days - 1)).date()
    counts: dict[str, int] = {}
    d = start
    while d <= now.date():
        counts[d.isoformat()] = 0
        d += timedelta(days=1)
    for a in applicants:
        if a.created_at and a.created_at.date() >= start:
            key = a.created_at.date().isoformat()
            if key in counts:
                counts[key] += 1

    return {"days": days, "job_id": job_id, "series": [{"date": k, "count": v} for k, v in sorted(counts.items())]}


# Stages this version reports first-arrival timestamps for, drawn
# directly from RecruiterPipelineHistory.new_stage (spec section 2).
_DURATION_STAGES = ["new", "reviewing", "interview", "offer", "hired"]


def _first_reached_at(db: Session, applicant_ids: list[int]) -> dict[int, dict[str, datetime]]:
    """For each applicant, the FIRST time they ever entered each of
    `_DURATION_STAGES` (their earliest matching RecruiterPipelineHistory
    row) — used for point-to-point durations below. A stage never
    reached is simply absent from that applicant's dict; callers must
    treat that as "unknown", never as zero (spec section 2: "Do not
    treat incomplete data as zero")."""
    result: dict[int, dict[str, datetime]] = defaultdict(dict)
    if not applicant_ids:
        return result
    rows = db.scalars(
        select(RecruiterPipelineHistory)
        .where(RecruiterPipelineHistory.applicant_id.in_(applicant_ids), RecruiterPipelineHistory.new_stage.in_(_DURATION_STAGES))
        .order_by(RecruiterPipelineHistory.applicant_id, RecruiterPipelineHistory.changed_at)
    )
    for row in rows:
        if row.new_stage not in result[row.applicant_id]:
            result[row.applicant_id][row.new_stage] = row.changed_at
    return result


def _avg_days(deltas: list[float]) -> float | None:
    return round(sum(deltas) / len(deltas), 1) if deltas else None


def time_and_bottleneck_analytics(db: Session, owner_ids: list[int], *, job_id: int | None = None, now: datetime | None = None) -> dict:
    """Spec section 2. Point-to-point durations (application→interview,
    interview→offer, offer→hired, overall time-to-hire) are computed
    only over applicants who actually reached *both* endpoints — an
    applicant still short of interview contributes nothing to
    "time to interview", not a zero and not an estimate. Average
    time-in-*current*-stage (a different, complementary number — "how
    long is the average candidate sitting in INTERVIEW right now")
    reuses ``recruiter_pipeline.service.pipeline_stats`` directly
    rather than a second implementation of the same idea."""
    now = now or datetime.utcnow()
    jobs = _my_jobs(db, owner_ids)
    job_ids = [job_id] if job_id is not None else [j.id for j in jobs]
    applicants = _applicants_for_jobs(db, job_ids)
    applicant_ids = [a.id for a in applicants]

    reached = _first_reached_at(db, applicant_ids)

    def _deltas(from_stage: str, to_stage: str) -> list[float]:
        out = []
        for aid in applicant_ids:
            times = reached.get(aid, {})
            if from_stage in times and to_stage in times:
                delta = (times[to_stage] - times[from_stage]).total_seconds() / 86400
                if delta >= 0:
                    out.append(delta)
        return out

    time_to_first_review = _deltas("new", "reviewing")
    time_app_to_interview = _deltas("new", "interview")
    time_interview_to_offer = _deltas("interview", "offer")
    time_offer_to_hired = _deltas("offer", "hired")
    overall_time_to_hire = _deltas("new", "hired")

    stats = pipeline_service.pipeline_stats(db, job_id or 0, applicants, now=now)
    avg_time_in_stage = stats["average_days_in_stage"]

    # Bottleneck (spec section 2 example): the stage with the highest
    # average time-in-*current*-stage among stages that actually have
    # at least one candidate sitting in them right now — a stage no
    # one is currently in can't be "the bottleneck" today, even if its
    # historical average happens to be non-null from past occupants.
    stage_counts = stats["stage_counts"]
    candidate_stages = {s: d for s, d in avg_time_in_stage.items() if d is not None and stage_counts.get(s, 0) > 0 and s not in PIPELINE_TERMINAL_STAGES}
    bottleneck = max(candidate_stages, key=candidate_stages.get) if candidate_stages else None
    bottleneck_observation = (
        f"{bottleneck.upper()} has the highest average time in stage ({candidate_stages[bottleneck]} days, across {stage_counts[bottleneck]} candidate(s) currently there)."
        if bottleneck
        else "Not enough active candidates in any stage yet to identify a bottleneck."
    )

    return {
        "job_id": job_id,
        "average_time_to_first_review_days": _avg_days(time_to_first_review),
        "average_time_in_stage_days": avg_time_in_stage,
        "average_time_application_to_interview_days": _avg_days(time_app_to_interview),
        "average_time_interview_to_offer_days": _avg_days(time_interview_to_offer),
        "average_time_offer_to_hired_days": _avg_days(time_offer_to_hired),
        "overall_time_to_hire_days": _avg_days(overall_time_to_hire),
        "sample_sizes": {
            "time_to_first_review": len(time_to_first_review),
            "application_to_interview": len(time_app_to_interview),
            "interview_to_offer": len(time_interview_to_offer),
            "offer_to_hired": len(time_offer_to_hired),
            "overall_time_to_hire": len(overall_time_to_hire),
        },
        "bottleneck_stage": bottleneck,
        "bottleneck_observation": bottleneck_observation,
    }


def funnel(db: Session, owner_ids: list[int], *, job_id: int | None = None) -> dict:
    """Spec section 1.C — reuses
    ``recruiter_pipeline.service.conversion_metrics`` unmodified
    (that function doesn't actually filter by ``job_id``; it only
    echoes it back in the response, so passing the recruiter's full
    cross-job applicant list gives the exact same zero-denominator-safe
    funnel math at recruiter scope with no new code)."""
    jobs = _my_jobs(db, owner_ids)
    job_ids = [job_id] if job_id is not None else [j.id for j in jobs]
    applicants = _applicants_for_jobs(db, job_ids)
    return pipeline_service.conversion_metrics(db, job_id or 0, applicants)


def candidate_match_analytics(db: Session, recruiter, job: Job) -> dict:
    """Spec section 4. Reuses V24.2's own deterministic matching
    (``app.api.recruiter_candidates``) unchanged — no second matching
    algorithm. Scored population is this job's actual applicants
    (not the wider "find candidates for this job" discovery pool),
    since match *analytics for a job* is naturally about who applied,
    not who else could be found."""
    from collections import Counter

    from app.api import recruiter_candidates as rc
    from app.recommendations import candidate_features as cf
    from app.recommendations import job_features as jf
    from app.recommendations import matching as rec_matching

    applicants = db.scalars(select(Applicant).where(Applicant.job_id == job.id)).all()
    candidate_ids = {a.user_id for a in applicants}
    rows = rc._load_candidate_rows(db, recruiter, candidate_ids)
    job_feat = jf.build(job)

    scored = []
    all_missing: list[str] = []
    coverage_pcts: list[float] = []
    for row in rows:
        candidate_feat = cf.build(db, row.user.id)
        match = rec_matching.compute(candidate_feat, job, job_feat, behavior=None)
        title = rc._title_match(row, job)
        score, reasons = rc._recruiter_match_score(match, title)
        card = rc._candidate_card(row)
        card["match_score"] = score
        card["match_reasons"] = reasons
        scored.append(card)
        if match.skill.available:
            total_req = len(match.matched_skills) + len(match.missing_skills)
            if total_req:
                coverage_pcts.append(round(100 * len(match.matched_skills) / total_req, 1))
            all_missing.extend(match.missing_skills)

    high = [c for c in scored if c["match_score"] >= 75]
    medium = [c for c in scored if 45 <= c["match_score"] < 75]
    low = [c for c in scored if c["match_score"] < 45]
    scored.sort(key=lambda c: c["match_score"], reverse=True)

    missing_counter = Counter(all_missing)
    return {
        "job_id": job.id,
        "candidates_scored": len(scored),
        "distribution": {"high": len(high), "medium": len(medium), "low": len(low)},
        "candidates": scored,
        "average_skill_coverage_pct": _avg_days(coverage_pcts),  # same round-and-average helper; unit is % not days
        "most_commonly_missing_skills": [{"skill": s, "candidates_missing": n} for s, n in missing_counter.most_common(10)],
    }


def stale_candidates_all(db: Session, owner_ids: list[int], *, threshold_days: int = pipeline_service.DEFAULT_STALE_THRESHOLD_DAYS, now: datetime | None = None) -> list[dict]:
    """Spec section 6. Configurable threshold (query param at the API
    layer, defaulting to ``recruiter_pipeline.service.
    DEFAULT_STALE_THRESHOLD_DAYS`` — the same single constant the
    per-job stale endpoint already uses, so there is exactly one
    "what counts as stale" default in this codebase, not one per
    endpoint). Merges the per-job staleness detection
    (``recruiter_pipeline.service.stale_candidates``, unchanged) across
    every job this recruiter owns, attaching job id/title so the
    result is directly usable cross-job."""
    now = now or datetime.utcnow()
    jobs = _my_jobs(db, owner_ids)
    job_ids = [j.id for j in jobs]
    applicants = _applicants_for_jobs(db, job_ids)
    by_job: dict[int, list[Applicant]] = defaultdict(list)
    for a in applicants:
        by_job[a.job_id].append(a)

    results = []
    for job in jobs:
        for entry in pipeline_service.stale_candidates(db, job.id, by_job.get(job.id, []), threshold_days=threshold_days, now=now):
            results.append({**entry, "job_id": job.id, "job_title": job.title})
    results.sort(key=lambda r: r["days_inactive"], reverse=True)
    return results


def compare_candidates(db: Session, recruiter, job: Job, candidate_ids: list[int]) -> list[dict]:
    """Spec section 8's deterministic substrate — the same per-candidate
    match computation as ``candidate_match_analytics`` above, scoped to
    just the requested candidate ids (so comparing 2-3 named candidates
    doesn't score the whole job's applicant pool). Every candidate id
    must already be one of this job's applicants OR in the recruiter's
    authorized discovery pool — enforced by the caller
    (``app.api.recruiter_analytics``) via
    ``recruiter_candidates._authorized_candidate_ids`` before this is
    ever called; this function does no authorization of its own."""
    from app.api import recruiter_candidates as rc
    from app.recommendations import candidate_features as cf
    from app.recommendations import job_features as jf
    from app.recommendations import matching as rec_matching

    rows = rc._load_candidate_rows(db, recruiter, set(candidate_ids))
    job_feat = jf.build(job)

    out = []
    for row in rows:
        candidate_feat = cf.build(db, row.user.id)
        match = rec_matching.compute(candidate_feat, job, job_feat, behavior=None)
        title = rc._title_match(row, job)
        score, reasons = rc._recruiter_match_score(match, title)
        out.append(
            {
                "candidate_id": row.user.id,
                "match_score": score,
                "match_reasons": reasons,
                "required_skills_matched": len(match.matched_skills),
                "required_skills_total": len(match.matched_skills) + len(match.missing_skills),
                "missing_skills": match.missing_skills,
                "experience_level": row.career.experience_level if row.career else None,
                "education": row.profile.highest_qualification if row.profile else None,
                "location": row.profile.location if row.profile else None,
                "top_skills": sorted(row.skills)[:12],
            }
        )
    out.sort(key=lambda c: c["match_score"], reverse=True)
    return out


def job_performance(db: Session, job: Job, *, now: datetime | None = None) -> dict:
    """Spec section 3. Every field is a real aggregate over this one
    job's applicants/interviews/offers, or one of the
    ``UNTRACKED_METRICS`` explicitly marked unavailable."""
    now = now or datetime.utcnow()
    applicants = db.scalars(select(Applicant).where(Applicant.job_id == job.id)).all()
    applicant_ids = [a.id for a in applicants]

    stats = pipeline_service.pipeline_stats(db, job.id, applicants, now=now)
    conversion = pipeline_service.conversion_metrics(db, job.id, applicants)
    trend = applications_over_time(db, [job.owner_user_id], days=30, job_id=job.id, now=now)

    interviews = 0
    offers = 0
    if applicant_ids:
        interviews = len(db.scalars(select(Interview).where(Interview.applicant_id.in_(applicant_ids))).all())
        offers = len(db.scalars(select(OfferLetter).where(OfferLetter.applicant_id.in_(applicant_ids))).all())

    hires = sum(1 for a in applicants if a.pipeline_stage == "hired")
    rejections = sum(1 for a in applicants if a.pipeline_stage == "rejected")
    withdrawals = sum(1 for a in applicants if a.pipeline_stage == "withdrawn")
    avg_days_active = _avg_days(
        [max(0, (now - a.created_at).days) for a in applicants if (a.pipeline_stage or "new") not in PIPELINE_TERMINAL_STAGES and a.created_at]
    )

    return {
        "job_id": job.id,
        "job_title": job.title,
        "applications": len(applicants),
        "applications_over_time": trend["series"],
        "pipeline_distribution": stats["stage_counts"],
        "interview_count": interviews,
        "offer_count": offers,
        "hire_count": hires,
        "rejection_count": rejections,
        "withdrawal_count": withdrawals,
        "average_days_in_pipeline_active_candidates": avg_days_active,
        **UNTRACKED_METRICS,
        "funnel": conversion,
    }
