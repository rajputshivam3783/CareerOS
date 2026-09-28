"""V25.3 — platform-derived job market intelligence (sections 6-9).

THE LABEL THAT MATTERS
----------------------
Everything in this module measures **CareerOS activity**. Every
response carries ``scope: "careeros_platform"`` and a human-readable
``scope_label`` of "CareerOS job-market activity", and no function
here returns a figure described as a national or industry market
statistic. CareerOS holds no external representative labour-market
dataset; ``EXTERNAL_MARKET_DATA_AVAILABLE`` is False and is surfaced
in the API so the absence is explicit rather than implied.

That is not a disclaimer bolted onto the response — it is the reason
the module is named for the platform rather than the market.

TRENDS (section 7)
------------------
A trend compares two **equal, adjacent** periods and is reported only
when both periods clear the ``min_trend_observations`` threshold.
Comparing a trailing window against all of history would make every
established skill look like it is collapsing; reporting a direction
from four postings would be noise dressed as insight. Where either
period is too small, the skill is returned with
``status: "insufficient_data"`` and no direction — never omitted
silently, because a skill disappearing from a list reads as "demand
went to zero".

SALARY (section 9)
------------------
``jobs.salary`` is a free-text column ("As per 7th CPC",
"₹8-12 LPA", "Negotiable", "Level 7"). It is not a structured range
and was never validated on entry.

So this module does **not** produce salary distributions, medians, or
salary-by-role/experience/location breakdowns. Doing so would require
parsing arbitrary prose into numbers and presenting the result as
reliable, which is precisely the fabrication section 9 prohibits.

What it does instead is report **salary disclosure** — a fact that is
true and useful: how many jobs state anything about pay at all, and
how many of those state a figure a deterministic parser can read with
confidence. Parsed figures are reported only as a coverage statistic,
never aggregated into a "typical salary", and the distinction between
disclosed and parseable is explicit in the response.
"""

from __future__ import annotations

import re
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.intelligence import corpus as corpus_mod
from app.intelligence import roles as roles_mod
from app.intelligence import skills as skills_mod
from app.intelligence import thresholds
from app.models.domain import Applicant, Job

SCOPE = "careeros_platform"
SCOPE_LABEL = "CareerOS job-market activity"
SCOPE_NOTE = (
    "These figures describe jobs and applications on CareerOS only. They are not a "
    "representative sample of any national or industry-wide job market, and must not "
    "be described as one."
)

# CareerOS integrates no external labour-market dataset. If one is ever
# added, this flag and the scope labels above are the single place the
# claim would legitimately change.
EXTERNAL_MARKET_DATA_AVAILABLE = False


def _envelope(db: Session, spec: corpus_mod.CorpusFilter, **payload) -> dict:
    return {
        "scope": SCOPE,
        "scope_label": SCOPE_LABEL,
        "scope_note": SCOPE_NOTE,
        "external_market_data_available": EXTERNAL_MARKET_DATA_AVAILABLE,
        "filters": spec.describe(),
        "thresholds": thresholds.load(db).as_dict(),
        **payload,
    }


# ---------------------------------------------------------------------------
# 6. Overview
# ---------------------------------------------------------------------------


def overview(db: Session, spec: corpus_mod.CorpusFilter) -> dict:
    """Headline platform job-market activity."""
    total = corpus_mod.count_jobs(db, spec)
    days = corpus_mod.clamp_days(spec.days)

    open_query = select(func.count()).select_from(Job).where(corpus_mod.deadline_active_clause())
    for clause in corpus_mod._clauses(spec):
        open_query = open_query.where(clause)

    return _envelope(
        db,
        spec,
        jobs=total,
        open_jobs=int(db.scalar(open_query) or 0),
        applications=corpus_mod.application_counts(db, spec),
        jobs_over_time=corpus_mod.daily_counts(db, spec, Job.published_at, days=days),
        by_job_type=corpus_mod.aggregate_counts(db, spec, Job.job_type),
        by_category=corpus_mod.aggregate_counts(db, spec, Job.category),
        by_employment_type=corpus_mod.aggregate_counts(db, spec, Job.employment_type),
        work_mode=work_mode_distribution(db, spec),
        top_roles=roles_mod.observed_roles(db, spec, limit=15),
        salary_disclosure=salary_disclosure(db, spec),
    )


def work_mode_distribution(db: Session, spec: corpus_mod.CorpusFilter) -> dict:
    """Remote / hybrid / on-site split, reported with its coverage.

    ``jobs.work_mode`` is optional and frequently unset, especially on
    ingested government listings. A percentage split computed over
    only the jobs that filled it in would describe a self-selected
    minority while looking like it described everything, so the
    response reports how many jobs in the corpus actually carry the
    field and bases percentages on that subset explicitly.
    """
    total = corpus_mod.count_jobs(db, spec)
    rows = corpus_mod.aggregate_counts(db, spec, Job.work_mode, limit=10)
    with_data = sum(row["count"] for row in rows)
    return {
        "jobs_in_corpus": total,
        "jobs_with_work_mode": with_data,
        "coverage_pct": round(with_data / total * 100, 1) if total else 0.0,
        "distribution": [
            {**row, "pct_of_jobs_with_work_mode": round(row["count"] / with_data * 100, 1) if with_data else 0.0}
            for row in rows
        ],
        "note": "Percentages are of jobs that specify a work mode, not of all jobs in the corpus.",
    }


# ---------------------------------------------------------------------------
# 6/7. Skill demand and trends
# ---------------------------------------------------------------------------


def skill_demand(db: Session, spec: corpus_mod.CorpusFilter, *, limit: int = 25) -> dict:
    loaded = corpus_mod.load_jobs(db, spec)
    blocked = skills_mod.guard_corpus(db, loaded.total)
    if blocked:
        return _envelope(db, spec, **blocked)
    return _envelope(
        db,
        spec,
        corpus_truncated=loaded.truncated,
        corpus_sampled=loaded.size,
        **skills_mod.skill_summary(db, loaded.jobs, limit=limit),
    )


def role_demand(db: Session, spec: corpus_mod.CorpusFilter, *, limit: int = 25) -> dict:
    total = corpus_mod.count_jobs(db, spec)
    blocked = skills_mod.guard_corpus(db, total)
    if blocked:
        return _envelope(db, spec, **blocked)
    limits = thresholds.load(db)
    rows = roles_mod.observed_roles(db, spec, limit=limit)
    kept, suppressed = thresholds.suppress_small_groups(rows, count_key="job_count", minimum=1)
    return _envelope(
        db,
        spec,
        jobs=total,
        roles=kept,
        suppressed_rows=suppressed,
        note=(
            "Job titles are reported as entered. CareerOS has no role taxonomy, so titles "
            "are not clustered into role families."
        ),
        min_group_size=limits.min_group,
    )


def _period_skill_counts(db: Session, spec: corpus_mod.CorpusFilter, start, end) -> tuple[Counter, int]:
    jobs = corpus_mod.jobs_between(db, spec, start, end)
    corpus = skills_mod.build(db, jobs)
    counter: Counter = Counter()
    for job_skills in corpus.per_job:
        counter.update(job_skills)
    return counter, corpus.jobs_with_skill_data


def skill_trends(db: Session, spec: corpus_mod.CorpusFilter, *, limit: int = 20) -> dict:
    """Rising/falling skill demand across two equal adjacent periods."""
    limits = thresholds.load(db)
    days = corpus_mod.clamp_days(spec.days, default=30)
    previous_start, midpoint, now = corpus_mod.split_window(days)

    current, current_jobs = _period_skill_counts(db, spec, midpoint, now)
    previous, previous_jobs = _period_skill_counts(db, spec, previous_start, midpoint)

    if current_jobs < limits.min_trend or previous_jobs < limits.min_trend:
        return _envelope(
            db,
            spec,
            period_days=days,
            current_period_jobs=current_jobs,
            previous_period_jobs=previous_jobs,
            **thresholds.insufficient(
                min(current_jobs, previous_jobs),
                limits.min_trend,
                subject="CareerOS jobs with skill data in each compared period",
            ),
        )

    rows = []
    for skill in set(current) | set(previous):
        now_count = current.get(skill, 0)
        then_count = previous.get(skill, 0)
        if now_count + then_count < limits.min_trend:
            # Reported, but with no direction — see module docstring on
            # why these are not silently dropped.
            rows.append(
                {
                    "skill": skill,
                    "current_period_jobs": now_count,
                    "previous_period_jobs": then_count,
                    "direction": None,
                    "change_pct": None,
                    "status": thresholds.INSUFFICIENT,
                }
            )
            continue
        if then_count == 0:
            change = None
            direction = "new"
        else:
            change = round((now_count - then_count) / then_count * 100, 1)
            direction = "rising" if change > 0 else ("falling" if change < 0 else "steady")
        rows.append(
            {
                "skill": skill,
                "current_period_jobs": now_count,
                "previous_period_jobs": then_count,
                "direction": direction,
                "change_pct": change,
                "status": "ok",
            }
        )

    rows.sort(key=lambda r: (r["status"] != "ok", -(r["current_period_jobs"] + r["previous_period_jobs"])))
    return _envelope(
        db,
        spec,
        period_days=days,
        current_period_jobs=current_jobs,
        previous_period_jobs=previous_jobs,
        comparison=(
            f"The {days} days ending now, compared against the {days} days before that. "
            "Periods are equal length and adjacent."
        ),
        skills=rows[:limit],
    )


def volume_trends(db: Session, spec: corpus_mod.CorpusFilter) -> dict:
    """Job and application volume change across two equal periods."""
    limits = thresholds.load(db)
    days = corpus_mod.clamp_days(spec.days, default=30)
    previous_start, midpoint, now = corpus_mod.split_window(days)

    def _job_count(start, end) -> int:
        query = select(func.count()).select_from(Job).where(
            Job.published_at.isnot(None), Job.published_at >= start, Job.published_at < end
        )
        for clause in corpus_mod._clauses(
            corpus_mod.CorpusFilter(
                role_query=spec.role_query, location=spec.location, category=spec.category,
                job_type=spec.job_type, work_mode=spec.work_mode,
                employment_type=spec.employment_type, owner_user_ids=spec.owner_user_ids,
                statuses=spec.statuses,
            )
        ):
            query = query.where(clause)
        return int(db.scalar(query) or 0)

    def _application_count(start, end) -> int:
        query = (
            select(func.count())
            .select_from(Applicant)
            .join(Job, Job.id == Applicant.job_id)
            .where(Applicant.created_at >= start, Applicant.created_at < end)
        )
        for clause in corpus_mod._clauses(spec):
            query = query.where(clause)
        return int(db.scalar(query) or 0)

    def _compare(label: str, now_value: int, then_value: int) -> dict:
        if now_value < limits.min_trend or then_value < limits.min_trend:
            return {
                "metric": label,
                "current_period": now_value,
                "previous_period": then_value,
                "direction": None,
                "change_pct": None,
                **thresholds.insufficient(min(now_value, then_value), limits.min_trend),
            }
        change = round((now_value - then_value) / then_value * 100, 1)
        return {
            "metric": label,
            "current_period": now_value,
            "previous_period": then_value,
            "direction": "rising" if change > 0 else ("falling" if change < 0 else "steady"),
            "change_pct": change,
            "status": "ok",
        }

    return _envelope(
        db,
        spec,
        period_days=days,
        trends=[
            _compare("jobs_published", _job_count(midpoint, now), _job_count(previous_start, midpoint)),
            _compare(
                "applications_submitted",
                _application_count(midpoint, now),
                _application_count(previous_start, midpoint),
            ),
        ],
    )


# ---------------------------------------------------------------------------
# 8. Location intelligence
# ---------------------------------------------------------------------------


def location_intelligence(db: Session, spec: corpus_mod.CorpusFilter, *, limit: int = 20) -> dict:
    """Job, role and skill distribution by location.

    Every figure here is about **jobs**, never about candidates. No
    function in this module reads a candidate's location, and no
    breakdown of where candidates live is produced anywhere in V25.3
    (spec section 8). Location is also never used to infer anything
    about a person.

    Per-location skill breakdowns are gated twice: the location needs
    enough jobs to clear the corpus threshold, and the row needs to
    clear the privacy group floor.
    """
    total = corpus_mod.count_jobs(db, spec)
    blocked = skills_mod.guard_corpus(db, total)
    if blocked:
        return _envelope(db, spec, **blocked)

    limits = thresholds.load(db)
    rows = corpus_mod.aggregate_counts(db, spec, Job.location, limit=limit)
    kept, suppressed = thresholds.suppress_small_groups(rows, count_key="count", minimum=limits.min_group)

    detailed = []
    for row in kept[:10]:
        location_spec = corpus_mod.CorpusFilter(
            days=spec.days, role_query=spec.role_query, location=row["key"],
            category=spec.category, job_type=spec.job_type, work_mode=spec.work_mode,
            employment_type=spec.employment_type, owner_user_ids=spec.owner_user_ids,
            statuses=spec.statuses,
        )
        if row["count"] < limits.min_corpus:
            detailed.append(
                {
                    "location": row["key"],
                    "job_count": row["count"],
                    **thresholds.insufficient(row["count"], limits.min_corpus),
                }
            )
            continue
        loaded = corpus_mod.load_jobs(db, location_spec, limit=400)
        skill_corpus = skills_mod.build(db, loaded.jobs)
        detailed.append(
            {
                "location": row["key"],
                "job_count": row["count"],
                "status": "ok",
                "top_roles": roles_mod.observed_roles(db, location_spec, limit=5),
                "top_skills": skills_mod.frequency(skill_corpus, limit=8),
                "jobs_with_skill_data": skill_corpus.jobs_with_skill_data,
            }
        )

    return _envelope(
        db,
        spec,
        jobs=total,
        jobs_by_location=kept,
        suppressed_locations=suppressed,
        suppression_note=(
            f"Locations with fewer than {limits.min_group} jobs are withheld so a single "
            "employer's activity in a small location cannot be singled out."
        ),
        location_detail=detailed,
        candidate_locations_note=(
            "CareerOS does not report where candidates are located. Every figure here "
            "describes job listings."
        ),
    )


# ---------------------------------------------------------------------------
# 9. Salary disclosure (deliberately NOT salary analytics)
# ---------------------------------------------------------------------------

# Matches a currency-ish figure with an explicit unit. Deliberately
# strict: it must see a number AND a recognizable scale/currency
# marker. "Level 7", "As per rules" and "Negotiable" do not parse, and
# are counted as disclosed-but-unparseable rather than coerced.
_SALARY_FIGURE_RE = re.compile(
    r"(?:₹|rs\.?|inr|\$)\s?\d[\d,]*(?:\.\d+)?\s?(?:lpa|lakh|lakhs|k|cr|crore|per month|pm|p\.m\.|per annum|pa)?"
    r"|\d[\d,]*(?:\.\d+)?\s?(?:lpa|lakh|lakhs|crore)\b",
    re.IGNORECASE,
)


def salary_disclosure(db: Session, spec: corpus_mod.CorpusFilter) -> dict:
    """How much pay information CareerOS listings actually carry.

    This is a *data coverage* report, not salary analytics. See the
    module docstring: ``jobs.salary`` is unvalidated free text, so no
    median, range, or salary-by-anything breakdown is produced. The
    response states that outright so a consumer does not go looking
    for a distribution that was deliberately not built.
    """
    loaded = corpus_mod.load_jobs(db, spec, limit=1000)
    total = loaded.total
    disclosed = 0
    parseable = 0
    for job in loaded.jobs:
        text = " ".join(filter(None, [job.salary, job.pay_level, job.stipend])).strip()
        if not text:
            continue
        disclosed += 1
        if _SALARY_FIGURE_RE.search(text):
            parseable += 1

    sampled = loaded.size
    return {
        "jobs_in_corpus": total,
        "jobs_sampled": sampled,
        "jobs_disclosing_any_pay_information": disclosed,
        "jobs_with_a_machine_readable_figure": parseable,
        "disclosure_rate_pct": round(disclosed / sampled * 100, 1) if sampled else 0.0,
        "machine_readable_rate_pct": round(parseable / sampled * 100, 1) if sampled else 0.0,
        "salary_analytics_available": False,
        "note": (
            "CareerOS stores pay as unvalidated free text (for example 'As per 7th CPC', "
            "'Negotiable', '₹8-12 LPA'), so no salary range, median, or salary-by-role "
            "breakdown is produced. Parsing that text into numbers and presenting the "
            "result as reliable would be fabrication. The figures above describe how "
            "many listings disclose pay at all — they are not an estimate of pay."
        ),
    }
