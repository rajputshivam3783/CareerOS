"""V25.3 — candidate career intelligence (sections 2, 4, 5).

Everything here is computed from ONE candidate's own authorized data
plus the public published-job corpus. No function takes another
user's id, and no function reads another candidate's profile, resume,
applications or notes.

NO OPAQUE SCORES
----------------
Section 2 forbids arbitrary "career scores" without an explainable
formula. This module produces none. Every ratio it returns carries
its own ``formula`` string stating the numerator, the denominator and
what a match means, so a candidate can verify the number by hand.

Where a genuinely composite readiness figure is wanted, this module
does not invent a second one — it defers to the existing V20.5
``app.skill_intelligence.readiness`` engine, which already publishes
its component breakdown.

PROTECTED CHARACTERISTICS
-------------------------
``Profile`` carries ``date_of_birth``, ``reservation_category`` and
``is_pwd`` because the V5 eligibility engine needs them to answer
"can I legally apply for this government post". Nothing in V25.3
reads any of the three, and no analytic here is segmented by,
correlated with, or derived from them. The test suite asserts their
absence from every candidate-intelligence response.

STATISTICAL HONESTY
-------------------
Interview conversion is the metric most likely to mislead an
individual candidate: with four applications, one interview is
"25% conversion" and also means nothing. Conversion is therefore
reported only when the candidate's own application count clears the
trend threshold, and is otherwise returned as
``insufficient_data`` with the raw counts still shown — the counts
are true; the rate is what would have been misleading.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.intelligence import corpus as corpus_mod
from app.intelligence import roles as roles_mod
from app.intelligence import skills as skills_mod
from app.intelligence import thresholds
from app.models.domain import Applicant, CareerPreference, Profile, Resume, SavedJob

# Pipeline stages that evidence a candidate reached an interview.
INTERVIEW_STAGES = ("interview", "offer", "hired")


def _application_rows(db: Session, user_id: int) -> list[Applicant]:
    """The candidate's own platform applications."""
    return list(
        db.scalars(select(Applicant).where(Applicant.user_id == user_id).order_by(Applicant.id.desc())).all()
    )


def profile_completeness(db: Session, user_id: int) -> dict:
    """Which parts of the candidate's own profile are filled in.

    Deterministic and itemized rather than a single opaque percentage:
    the candidate sees exactly which field is missing and can act on
    it. The percentage is derived from the checklist, not the other
    way round.
    """
    profile = db.get(Profile, user_id)
    resume = db.get(Resume, user_id)
    preference = db.get(CareerPreference, user_id)

    checks = [
        ("location", bool(profile and profile.location)),
        ("highest_qualification", bool(profile and profile.highest_qualification)),
        ("skills", bool(profile and profile.skills)),
        ("preferred_roles", bool(profile and profile.preferred_roles)),
        ("resume_uploaded", resume is not None),
        ("target_role", bool(preference and preference.target_role)),
    ]
    complete = sum(1 for _, ok in checks)
    return {
        "items": [{"field": name, "complete": ok} for name, ok in checks],
        "complete_count": complete,
        "total_count": len(checks),
        "completeness_pct": round(complete / len(checks) * 100, 1),
        "formula": f"{complete} of {len(checks)} profile items present.",
    }


def application_activity(db: Session, user_id: int, *, days: int = 90) -> dict:
    """The candidate's own application volume, pipeline and outcomes."""
    limits = thresholds.load(db)
    rows = _application_rows(db, user_id)
    total = len(rows)

    by_status: Counter = Counter(row.status for row in rows if row.status)
    by_stage: Counter = Counter(row.pipeline_stage or "new" for row in rows)
    reached_interview = sum(1 for row in rows if (row.pipeline_stage or "") in INTERVIEW_STAGES)
    hired = sum(1 for row in rows if row.hired_at is not None)

    window_start = datetime.utcnow() - timedelta(days=corpus_mod.clamp_days(days))
    over_time = corpus_mod.densify(
        db.execute(
            select(func.date(Applicant.created_at), func.count())
            .where(Applicant.user_id == user_id, Applicant.created_at >= window_start)
            .group_by(func.date(Applicant.created_at))
        ).all(),
        window_start.date(),
        datetime.utcnow().date(),
    )

    if total >= limits.min_trend:
        conversion = {
            "status": "ok",
            "applications": total,
            "reached_interview_stage": reached_interview,
            "interview_rate_pct": round(reached_interview / total * 100, 1),
            "formula": (
                f"{reached_interview} of your {total} applications reached the interview, offer "
                f"or hired stage = {round(reached_interview / total * 100, 1)}%."
            ),
        }
    else:
        conversion = {
            "applications": total,
            "reached_interview_stage": reached_interview,
            "interview_rate_pct": None,
            **thresholds.insufficient(total, limits.min_trend, subject="applications of your own"),
        }

    return {
        "total_applications": total,
        "applications_over_time": over_time,
        "by_status": [{"key": key, "count": count} for key, count in by_status.most_common()],
        "pipeline_distribution": [{"key": key, "count": count} for key, count in by_stage.most_common()],
        "hired_count": hired,
        "interview_conversion": conversion,
        "saved_jobs": int(
            db.scalar(select(func.count()).select_from(SavedJob).where(SavedJob.user_id == user_id)) or 0
        ),
    }


def skill_profile(db: Session, user_id: int) -> dict:
    """The candidate's own canonical skill set."""
    resolved = skills_mod.candidate_skills(db, user_id)
    return {
        "skills": sorted(set(resolved.canonical)),
        "skill_count": len(set(resolved.canonical)),
        "unrecognized_skill_names": sorted(set(resolved.unrecognized)),
        "sources": ["your profile skills", "skills detected from your uploaded resume"],
        "note": (
            "Skills come only from what you entered and what was detected in the resume you "
            "uploaded. CareerOS does not infer skills from anything else about you."
        ),
    }


def target_role_analysis(
    db: Session,
    user_id: int,
    *,
    explicit_role: str | None = None,
    spec: corpus_mod.CorpusFilter | None = None,
) -> dict:
    """Full analysis for the candidate's target role (sections 4 and 5).

    The role's "requirements" are the skills that appear on at least
    two of the real published jobs matching that role. That is the
    whole definition, it is stated in the response, and the matched
    job titles are returned so the candidate can see which listings
    produced it.
    """
    base = spec or corpus_mod.CorpusFilter(days=None)
    target = roles_mod.resolve_target_role(db, user_id, explicit_role)

    if target.role is None:
        return {
            "target_role": target.as_dict(),
            "status": "no_target_role",
            "message": (
                "You have not set a target role, and CareerOS does not choose one for you. "
                "Set a target role in your career preferences, or pick one from the roles "
                "currently active on CareerOS."
            ),
            "suggested_roles_from_careeros": roles_mod.observed_roles(db, base, limit=10),
        }

    role_spec = roles_mod.role_filter(target.role, base)
    loaded = corpus_mod.load_jobs(db, role_spec)
    blocked = skills_mod.guard_corpus(db, loaded.total)
    if blocked:
        return {
            "target_role": target.as_dict(),
            "matching_jobs": loaded.total,
            **blocked,
            "message": (
                f"Only {loaded.total} published CareerOS job(s) match '{target.role}', which is "
                "too few to describe the role's skill requirements reliably."
            ),
            "suggested_roles_from_careeros": roles_mod.observed_roles(db, base, limit=10),
        }

    skill_corpus = skills_mod.build(db, loaded.jobs)
    reference = skills_mod.reference_skills_from_corpus(skill_corpus, top_n=15, min_job_count=2)
    candidate = set(skills_mod.candidate_skills(db, user_id).canonical)
    result = skills_mod.coverage(candidate, reference)

    # The candidate's own activity against this specific role.
    role_job_ids = [job.id for job in loaded.jobs]
    applications_to_role = int(
        db.scalar(
            select(func.count())
            .select_from(Applicant)
            .where(Applicant.user_id == user_id, Applicant.job_id.in_(role_job_ids))
        )
        or 0
    ) if role_job_ids else 0

    return {
        "target_role": target.as_dict(),
        "status": "ok",
        "matching_jobs": loaded.total,
        "matched_job_titles": roles_mod.role_titles_matching(db, target.role, base, limit=10),
        "corpus_truncated": loaded.truncated,
        "requirement_definition": (
            f"A skill counts as a requirement for '{target.role}' when it is listed on at least "
            f"2 of the {skill_corpus.jobs_with_skill_data} matching CareerOS jobs that specify "
            "skills. Job description text is never scanned for skill names."
        ),
        "reference_skills": [
            {"skill": name, "display_name": skill_corpus.display_names.get(name, name)} for name in reference
        ],
        "coverage": result.as_dict(skill_corpus),
        "frequently_requested_skills": skills_mod.frequency(skill_corpus, limit=12),
        "skill_data_coverage": skill_corpus.coverage_note(),
        "your_applications_to_this_role": applications_to_role,
        "scope_note": (
            "Skill requirements are derived from CareerOS listings only, not from an external "
            "labour-market dataset."
        ),
        "outcome_disclaimer": (
            "Skill coverage describes how your listed skills compare with what these listings "
            "ask for. It does not predict or guarantee any hiring outcome."
        ),
    }


def skill_gaps(
    db: Session,
    user_id: int,
    *,
    explicit_role: str | None = None,
    spec: corpus_mod.CorpusFilter | None = None,
) -> dict:
    """Deterministic career-gap analysis (section 5).

    Returns the matched/missing split plus the experience and
    education requirements the matching jobs actually stated. Those
    two are reported as *observed text frequencies*, not as a computed
    "you are N years short" — CareerOS stores experience as free text
    (``jobs.experience_required``) and holds no structured record of a
    candidate's years of experience, so a numeric gap would be
    invented.
    """
    analysis = target_role_analysis(db, user_id, explicit_role=explicit_role, spec=spec)
    if analysis.get("status") != "ok":
        return analysis

    base = spec or corpus_mod.CorpusFilter(days=None)
    role_spec = roles_mod.role_filter(analysis["target_role"]["role"], base)
    loaded = corpus_mod.load_jobs(db, role_spec)

    experience_counter: Counter = Counter(
        job.experience_required.strip() for job in loaded.jobs if job.experience_required
    )
    qualification_counter: Counter = Counter(
        job.qualification.strip()[:160] for job in loaded.jobs if job.qualification
    )

    return {
        **analysis,
        "gap": {
            "matched_skills": analysis["coverage"]["matched_skills"],
            "missing_skills": analysis["coverage"]["missing_skills"],
            "how_this_was_calculated": (
                "Your normalized skill set (profile skills plus skills detected in your resume) "
                "was compared against the reference skill list above. A skill is 'missing' when "
                "it is in the reference list and not in your skill set. Nothing is inferred "
                "about you beyond the skills you provided."
            ),
        },
        "experience_requirements_stated": [
            {"requirement": text, "job_count": count} for text, count in experience_counter.most_common(8)
        ],
        "education_requirements_stated": [
            {"requirement": text, "job_count": count} for text, count in qualification_counter.most_common(8)
        ],
        "experience_gap_note": (
            "Experience and education requirements are shown as the text these listings actually "
            "state, with how often each appears. CareerOS does not store your years of experience "
            "in a comparable structured form, so no numeric experience gap is calculated."
        ),
    }


def overview(db: Session, user_id: int, *, explicit_role: str | None = None) -> dict:
    """The candidate's career intelligence landing payload."""
    spec = corpus_mod.CorpusFilter(days=None)
    return {
        "scope": "your_careeros_data",
        "scope_note": (
            "This view combines your own CareerOS data with aggregate figures from published "
            "CareerOS job listings. It contains no information about any other candidate."
        ),
        "generated_at": datetime.utcnow(),
        "profile_completeness": profile_completeness(db, user_id),
        "skills": skill_profile(db, user_id),
        "application_activity": application_activity(db, user_id),
        "target_role": target_role_analysis(db, user_id, explicit_role=explicit_role, spec=spec),
        "thresholds": thresholds.load(db).as_dict(),
    }


def relevant_market_skills(db: Session, user_id: int, *, explicit_role: str | None = None, limit: int = 20) -> dict:
    """Skills appearing most often in jobs relevant to this candidate.

    "Relevant" means: jobs matching their target role if they have set
    one, otherwise all published jobs. It deliberately does NOT mean
    "jobs similar to ones you applied to" — building a behavioural
    profile to define relevance would be the invasive tracking section
    16 warns against, for a marginal gain.
    """
    target = roles_mod.resolve_target_role(db, user_id, explicit_role)
    base = corpus_mod.CorpusFilter(days=None)
    spec = roles_mod.role_filter(target.role, base) if target.role else base

    loaded = corpus_mod.load_jobs(db, spec)
    blocked = skills_mod.guard_corpus(db, loaded.total)
    if blocked:
        return {"target_role": target.as_dict(), "jobs_considered": loaded.total, **blocked}

    skill_corpus = skills_mod.build(db, loaded.jobs)
    candidate = set(skills_mod.candidate_skills(db, user_id).canonical)
    rows = skills_mod.frequency(skill_corpus, limit=limit)
    return {
        "target_role": target.as_dict(),
        "jobs_considered": loaded.total,
        "scope": "careeros_platform",
        "scope_label": "CareerOS job-market activity",
        "skills": [{**row, "you_have_this_skill": row["skill"] in candidate} for row in rows],
        "skill_data_coverage": skill_corpus.coverage_note(),
    }
