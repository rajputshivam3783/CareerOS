"""CANDIDATE FEATURES — Stage 0 of the recommendation pipeline.

Builds one ``CandidateFeatures`` snapshot from every authorized,
already-existing data source for a candidate. This module never
queries a job — that's app.recommendations.job_features — and never
scores anything — that's app.recommendations.matching/scoring. It
only reads and normalizes.

Sources (all read as-is, none duplicated):

- ``Profile`` (V1) — who the candidate *is*: skills, qualification,
  location, preferred roles/locations.
- ``CareerPreference`` (V20.3) — what the candidate *wants*: target
  role, industry, work mode, salary expectation, career goal.
- ``Resume``/``ResumeAnalysis`` (V8/V20.2) — normalized resume profile,
  when a resume is on file.
- ``app.skill_intelligence.gap.compute`` (V20.5) — the candidate's
  unified skill-gap view (resume + career goal + interview signals,
  already merged and normalized against the Skill catalog).
- ``SavedJob`` / ``Application`` (V1/V6) — job search/engagement
  history, used for "already saved"/"already applied" states and as a
  light behavioral signal, never duplicated into a new table.
- ``RecommendationFeedback`` (V21.3) — jobs the candidate has said
  "not interested"/"dismiss"/"not relevant" about; excluded from
  future recommendations (FEEDBACK LOOP requirement).
- ``RecommendationPreference`` (V21.3) — recommendation-specific
  settings.

FAIRNESS: ``Profile.reservation_category`` and ``Profile.is_pwd`` are
deliberately *not* read into ``CandidateFeatures`` for ranking
purposes. They remain available, unchanged, only through the existing
V5 ``app.services.eligibility`` module for age-relaxation display on
Government recommendations — never as a ranking input. See
RECOMMENDATION_FAIRNESS.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import (
    Application,
    CareerPreference,
    Profile,
    RecommendationFeedback,
    RecommendationPreference,
    Resume,
    SavedJob,
    Skill,
)
from app.resume_ai import pipeline as resume_pipeline
from app.resume_ai.normalization import NormalizedProfile
from app.services.career import tokens as split_tokens
from app.skill_intelligence import gap as skill_gap_engine


@dataclass
class CandidateFeatures:
    user_id: int

    has_profile: bool = False
    profile_skills: set[str] = field(default_factory=set)  # raw, comma-split, lowercased
    profile_location: str | None = None
    profile_preferred_roles: list[str] = field(default_factory=list)
    profile_preferred_locations: list[str] = field(default_factory=list)
    profile_qualification: str | None = None

    has_career_goal: bool = False
    target_role: str | None = None
    preferred_industry: str | None = None
    preferred_location: str | None = None
    preferred_work_mode: str | None = None
    experience_level: str | None = None
    target_companies: list[str] = field(default_factory=list)
    salary_expectation: str | None = None
    preferred_skills: set[str] = field(default_factory=set)
    career_goal_text: str | None = None

    has_resume: bool = False
    resume_text: str = ""
    resume_profile: NormalizedProfile | None = None
    resume_skills: set[str] = field(default_factory=set)

    unrecognized_skill_inputs: list[str] = field(default_factory=list)
    all_skill_tokens: set[str] = field(default_factory=set)  # union of profile+resume+preferred skills, lowercased

    priority_skill_gaps: list[str] = field(default_factory=list)  # canonical names, from unified skill-gap engine
    interview_weak_topics: list[str] = field(default_factory=list)  # canonical names flagged by the latest mock interview

    project_entries: list[str] = field(default_factory=list)  # raw resume project bullets, verbatim

    learning_in_progress_skills: set[str] = field(default_factory=set)  # canonical skill names with an active/in-progress LearningPlanModule
    learning_completed_skills: set[str] = field(default_factory=set)  # canonical skill names with a completed LearningPlanModule

    saved_job_ids: set[int] = field(default_factory=set)
    applied_job_ids: set[int] = field(default_factory=set)
    applied_company_role_pairs: set[tuple[str, str]] = field(default_factory=set)

    excluded_job_ids: set[int] = field(default_factory=set)  # dismissed / not_interested / not_relevant

    preferences: RecommendationPreference | None = None

    recent_search_terms: list[str] = field(default_factory=list)

    @property
    def is_cold_start(self) -> bool:
        """COLD START — true when there's essentially nothing to
        personalize against yet: no resume, no declared career goal,
        and no profile skills. See app.recommendations.cold_start."""
        return not self.has_resume and not self.has_career_goal and not self.profile_skills


def _split_csv(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def build(db: Session, user_id: int) -> CandidateFeatures:
    features = CandidateFeatures(user_id=user_id)

    # --- Profile (V1) ---
    profile = db.get(Profile, user_id)
    if profile is not None:
        features.has_profile = True
        features.profile_skills = {s.lower() for s in split_tokens(profile.skills)}
        features.profile_location = profile.location
        features.profile_preferred_roles = _split_csv(profile.preferred_roles)
        features.profile_preferred_locations = _split_csv(profile.preferred_locations)
        features.profile_qualification = profile.highest_qualification

    # --- Career goal (V20.3) ---
    career = db.get(CareerPreference, user_id)
    if career is not None:
        features.has_career_goal = any(
            [career.target_role, career.career_goal, career.preferred_industry, career.preferred_skills]
        )
        features.target_role = career.target_role
        features.preferred_industry = career.preferred_industry
        features.preferred_location = career.preferred_location
        features.preferred_work_mode = career.preferred_work_mode
        features.experience_level = career.experience_level
        features.target_companies = _split_csv(career.target_companies)
        features.salary_expectation = career.salary_expectation
        features.preferred_skills = {s.lower() for s in _split_csv(career.preferred_skills)}
        features.career_goal_text = career.career_goal

    # --- Resume (V8/V20.2) ---
    resume = db.get(Resume, user_id)
    if resume is not None:
        features.has_resume = True
        features.resume_text = resume.extracted_text
        normalized = resume_pipeline.build_profile(resume)
        features.resume_profile = normalized
        features.resume_skills = {s.lower() for s in normalized.technical_skills}
        features.project_entries = list(normalized.project_entries)

    features.all_skill_tokens = (
        features.profile_skills | features.resume_skills | features.preferred_skills
    )

    # --- Unified skill gap (V20.5, composes resume+career+interview) ---
    try:
        gap_result = skill_gap_engine.compute(db, user_id)
        features.priority_skill_gaps = [item.canonical_name for item in gap_result.priority_skills]
        features.unrecognized_skill_inputs = list(gap_result.unrecognized_inputs)
        # INTERVIEW WEAKNESSES — the unified gap engine already merges
        # V20.4 mock-interview technical_gaps/recommended_topics into
        # each item's source_signals; pull out just the ones flagged
        # that way rather than re-querying MockInterviewReport directly
        # (avoids a second interpretation of the same raw JSON field).
        features.interview_weak_topics = [
            item.canonical_name
            for item in gap_result.priority_skills
            if "weak_interview_performance" in item.source_signals
            or "recommended_by_interview_report" in item.source_signals
        ]
    except Exception:
        # Never let an optional enrichment signal break recommendations —
        # absence of this signal is reported, not fatal. See
        # RECOMMENDATION_ARCHITECTURE.md's edge-case handling.
        pass

    # --- Saved jobs / applications (V1/V6) ---
    features.saved_job_ids = set(
        db.scalars(select(SavedJob.job_id).where(SavedJob.user_id == user_id))
    )
    applications = db.scalars(select(Application).where(Application.user_id == user_id)).all()
    features.applied_job_ids = {a.job_id for a in applications if a.job_id is not None}
    features.applied_company_role_pairs = {
        (a.company.strip().lower(), a.role.strip().lower()) for a in applications if a.company and a.role
    }

    # --- Learning progress (V20.5) — best effort, never fatal. Joins
    # LearningPlanModule -> Skill for this candidate's own plans only,
    # scoped via LearningPlan.user_id, so a skill the candidate is
    # actively working through (or has finished) can be distinguished
    # from a skill they simply don't have yet in matching/explanations. ---
    try:
        from app.models.domain import LearningPlan, LearningPlanModule

        rows = db.execute(
            select(Skill.canonical_name, LearningPlanModule.status)
            .join(Skill, Skill.id == LearningPlanModule.skill_id)
            .join(LearningPlan, LearningPlan.id == LearningPlanModule.plan_id)
            .where(LearningPlan.user_id == user_id)
        ).all()
        for canonical_name, status in rows:
            name = canonical_name.lower()
            if status == "completed":
                features.learning_completed_skills.add(name)
            elif status == "in_progress":
                features.learning_in_progress_skills.add(name)
    except Exception:
        pass

    # --- Recommendation feedback (V21.3) — excluded job ids ---
    feedback_rows = db.scalars(
        select(RecommendationFeedback).where(
            RecommendationFeedback.user_id == user_id,
            RecommendationFeedback.feedback_type.in_(["dismiss", "not_relevant", "not_interested"]),
        )
    ).all()
    features.excluded_job_ids = {row.job_id for row in feedback_rows}

    # --- Recommendation preferences (V21.3) ---
    features.preferences = db.get(RecommendationPreference, user_id)

    # --- Search behaviour (V21.2 recent searches) — best effort, never fatal ---
    try:
        from app.search.models import RecentSearch

        rows = db.scalars(
            select(RecentSearch.query)
            .where(RecentSearch.user_id == user_id, RecentSearch.query != "")
            .order_by(RecentSearch.created_at.desc())
            .limit(10)
        ).all()
        features.recent_search_terms = list(rows)
    except Exception:
        pass

    return features
