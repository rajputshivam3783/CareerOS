"""CANDIDATE-JOB MATCHING — Stage 2 of the recommendation pipeline.

Every component here is deterministic and explainable (MATCHING /
SCORING requirements: "Every score must have a reason", "Do NOT
generate arbitrary scores", "Do NOT use an LLM to calculate basic
numeric relevance"). Components that can't be computed for lack of
data return ``None`` rather than a guessed number — see
``ComponentScore.available`` — and app.recommendations.scoring
redistributes weight across only the components that *are* available
(documented in RECOMMENDATION_SCORING.md), rather than silently
treating a missing signal as zero.

Reuses, never duplicates:

- ``app.resume_ai.job_match.match`` (V20.2) for the resume-vs-job
  dimension when the candidate has a stored resume.
- ``app.services.eligibility.eligibility`` (V5) is deliberately NOT
  called here — eligibility is a pass/fail verdict for a Government
  posting, not a ranking signal, and reservation_category/is_pwd must
  never influence ranking (FAIRNESS). See app.recommendations.government
  for where eligibility is surfaced instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.models.domain import Job
from app.recommendations.candidate_features import CandidateFeatures
from app.recommendations.job_features import JobFeatures
from app.recommendations.signals import BehaviorSignals, job_affinity
from app.resume_ai import job_match as resume_job_match


@dataclass
class ComponentScore:
    available: bool
    score: int | None  # 0-100, None when not available
    reason: str


@dataclass
class MatchResult:
    skill: ComponentScore
    experience: ComponentScore
    education: ComponentScore
    location: ComponentScore
    career_goal: ComponentScore
    work_mode: ComponentScore
    employment_type: ComponentScore
    salary: ComponentScore
    resume: ComponentScore
    recency: ComponentScore
    behavior: ComponentScore
    deadline_urgency: ComponentScore
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    missing_skills_in_progress: list[str] = field(default_factory=list)  # subset of missing_skills already being learned
    behavior_reasons: list[str] = field(default_factory=list)
    negative_reasons: list[str] = field(default_factory=list)


def _skill_match(candidate: CandidateFeatures, job: JobFeatures) -> tuple[ComponentScore, list[str], list[str]]:
    if not job.skills:
        return ComponentScore(True, 50, "Job listing doesn't reference any recognized skill to compare against"), [], []
    # LEARNING PROGRESS: a skill the candidate has *completed* via a
    # LearningPlan (V20.5) counts as matched even if their resume/
    # profile skills list hasn't been updated yet — the gap is
    # genuinely closed. A skill still *in progress* stays in
    # `missing`, but is called out separately in the explanation
    # rather than silently treated the same as an untouched gap.
    known_skills = candidate.all_skill_tokens | candidate.learning_completed_skills
    matched = sorted(known_skills & job.skills)
    missing = sorted(job.skills - known_skills)
    score = round((len(matched) / len(job.skills)) * 100)
    reason = f"{len(matched)} of {len(job.skills)} required/preferred skill(s) matched: {', '.join(matched) or 'none'}"
    return ComponentScore(True, score, reason), matched, missing


def _experience_match(candidate: CandidateFeatures, job: JobFeatures) -> ComponentScore:
    if candidate.resume_profile and candidate.resume_profile.experience_entries:
        # Reuse the same structural signal as app.resume_ai.job_match —
        # count of experience entries + strong action verbs — for
        # consistency with the resume-vs-job view the candidate already sees.
        from app.resume_ai.normalization import action_verb_count

        entries = candidate.resume_profile.experience_entries
        verbs = action_verb_count(entries)
        score = min(100, min(70, len(entries) * 7) + min(30, verbs * 10))
        return ComponentScore(
            True, score,
            f"Resume has {len(entries)} experience entry(ies) with {verbs} strong action verb(s)"
            + (f"; job requires: {job.experience_required}" if job.experience_required else ""),
        )
    if candidate.project_entries:
        # PROJECTS: a candidate with no formal work experience yet
        # (common for freshers/students) but real project entries on
        # their resume gets partial credit here rather than being
        # scored identically to someone with neither — capped lower
        # than genuine work experience, never inflated to look the same.
        score = min(60, 20 + len(candidate.project_entries) * 10)
        return ComponentScore(
            True, score,
            f"No formal work experience on resume, but {len(candidate.project_entries)} project(s) listed"
            + (f"; job requires: {job.experience_required}" if job.experience_required else ""),
        )
    if candidate.experience_level and job.experience_required:
        overlap = candidate.experience_level.lower() in job.experience_required.lower()
        score = 70 if overlap else 30
        reason = (
            f"Career profile experience level '{candidate.experience_level}' "
            f"{'appears to align with' if overlap else 'does not clearly match'} the job's stated "
            f"'{job.experience_required}' requirement"
        )
        return ComponentScore(True, score, reason)
    return ComponentScore(False, None, "No resume or declared experience level on file to compare")


def _education_match(candidate: CandidateFeatures, job: JobFeatures) -> ComponentScore:
    if candidate.resume_profile and candidate.resume_profile.education_entries:
        qualification_text = (job.qualification or "").lower()
        education_text = " ".join(candidate.resume_profile.education_entries).lower()
        tokens = {t.strip(".,") for t in qualification_text.split() if len(t) > 3}
        overlap = sorted(t for t in tokens if t in education_text)
        if tokens:
            score = min(100, 40 + len(overlap) * 15)
            reason = f"{len(overlap)} word(s) from the job's stated qualification appear in resume education section"
        else:
            score = 60
            reason = "Job does not state a specific qualification to compare; education section is present"
        return ComponentScore(True, score, reason)
    if candidate.profile_qualification and job.qualification and "see official" not in job.qualification.lower():
        candidate_q = candidate.profile_qualification.lower()
        job_q = job.qualification.lower()
        overlap_terms = [t for t in ["10th", "12th", "diploma", "graduate", "bachelor", "master", "postgraduate"]
                          if t in candidate_q and t in job_q]
        score = 80 if overlap_terms else 40
        reason = (
            f"Profile qualification '{candidate.profile_qualification}' compared against job qualification text"
            + (f"; overlapping level(s): {', '.join(overlap_terms)}" if overlap_terms else "; no clear level overlap found")
        )
        return ComponentScore(True, score, reason)
    return ComponentScore(False, None, "No resume education section or profile qualification on file to compare")


def _location_match(candidate: CandidateFeatures, job: JobFeatures) -> ComponentScore:
    job_location = (job.location or "").lower()
    candidate_locations = [loc.lower() for loc in candidate.profile_preferred_locations]
    if candidate.preferred_location:
        candidate_locations.append(candidate.preferred_location.lower())
    if candidate.profile_location:
        candidate_locations.append(candidate.profile_location.lower())

    if not candidate_locations:
        if job.work_mode and job.work_mode.lower() == "remote":
            return ComponentScore(True, 70, "Job is remote; no location preference on file to compare further")
        return ComponentScore(False, None, "No preferred or current location on file to compare")

    if any(job_location in loc or loc in job_location for loc in candidate_locations):
        return ComponentScore(True, 100, f"Job location '{job.location}' matches a preferred/current location")
    if job.work_mode and job.work_mode.lower() == "remote":
        return ComponentScore(True, 70, "Job is remote — location mismatch is less significant")
    if "india" in candidate_locations or "anywhere" in candidate_locations:
        return ComponentScore(True, 60, "Candidate's stated location preference is broad (e.g. 'India')")
    return ComponentScore(True, 20, f"Job location '{job.location}' does not match any preferred/current location on file")


def _career_goal_match(candidate: CandidateFeatures, job: JobFeatures) -> ComponentScore:
    if not candidate.has_career_goal:
        return ComponentScore(False, None, "No career goal declared in Career Copilot preferences")
    score = 0
    reasons = []
    if candidate.target_role:
        if candidate.target_role.lower() in job.title.lower():
            score += 60
            reasons.append(f"job title matches target role '{candidate.target_role}'")
        else:
            reasons.append(f"job title doesn't clearly match target role '{candidate.target_role}'")
    if candidate.preferred_industry and job.industry:
        if candidate.preferred_industry.lower() in job.industry.lower() or job.industry.lower() in candidate.preferred_industry.lower():
            score += 40
            reasons.append(f"industry matches preferred industry '{candidate.preferred_industry}'")
    if not reasons:
        return ComponentScore(False, None, "Career goal declared but has no comparable role/industry fields to check")
    return ComponentScore(True, min(100, score), "; ".join(reasons))


def _work_mode_match(candidate: CandidateFeatures, job: JobFeatures) -> ComponentScore:
    if not candidate.preferred_work_mode or not job.work_mode:
        return ComponentScore(False, None, "No preferred work mode declared or job doesn't state one")
    if candidate.preferred_work_mode.lower() == job.work_mode.lower():
        return ComponentScore(True, 100, f"Job work mode '{job.work_mode}' matches preference")
    return ComponentScore(True, 30, f"Job work mode '{job.work_mode}' differs from preference '{candidate.preferred_work_mode}'")


def _employment_type_match(candidate: CandidateFeatures, job: JobFeatures) -> ComponentScore:
    preferred = []
    if candidate.preferences and candidate.preferences.preferred_employment_types:
        preferred = [p.strip().lower() for p in candidate.preferences.preferred_employment_types.split(",") if p.strip()]
    if not preferred or not job.employment_type:
        return ComponentScore(False, None, "No preferred employment type set or job doesn't state one")
    if job.employment_type.lower() in preferred:
        return ComponentScore(True, 100, f"Job employment type '{job.employment_type}' matches preference")
    return ComponentScore(True, 20, f"Job employment type '{job.employment_type}' not in preferred list")


def _parse_salary_lakhs(text: str | None) -> float | None:
    """Best-effort extraction of an annual figure in lakhs from free
    text like '6-9 LPA' or '₹8,00,000 per annum'. Returns None (never a
    guess) when the text doesn't match a recognized shape."""
    import re

    if not text:
        return None
    lpa = re.search(r"(\d+(?:\.\d+)?)\s*-?\s*(?:to)?\s*(\d+(?:\.\d+)?)?\s*lpa", text.lower())
    if lpa:
        low = float(lpa.group(1))
        high = float(lpa.group(2)) if lpa.group(2) else low
        return (low + high) / 2
    rupees = re.search(r"₹?\s*([\d,]{5,})", text)
    if rupees:
        try:
            value = float(rupees.group(1).replace(",", ""))
            return value / 100000
        except ValueError:
            return None
    return None


def _salary_match(candidate: CandidateFeatures, job: JobFeatures) -> ComponentScore:
    candidate_figure = _parse_salary_lakhs(candidate.salary_expectation)
    job_figure = _parse_salary_lakhs(job.salary)
    if candidate_figure is None or job_figure is None:
        return ComponentScore(False, None, "Salary expectation or job salary isn't stated in a comparable numeric form")
    if job_figure >= candidate_figure * 0.9:
        return ComponentScore(True, 100, f"Job's indicative salary (~₹{job_figure:.1f}L) meets stated expectation (~₹{candidate_figure:.1f}L)")
    ratio = max(0.0, job_figure / candidate_figure)
    return ComponentScore(True, round(ratio * 100), f"Job's indicative salary (~₹{job_figure:.1f}L) is below stated expectation (~₹{candidate_figure:.1f}L)")


def _recency_match(job: JobFeatures) -> ComponentScore:
    age_days = (date.today() - job.posted_date.date()).days
    if age_days <= 3:
        return ComponentScore(True, 100, f"Posted {age_days} day(s) ago")
    if age_days <= 14:
        return ComponentScore(True, 70, f"Posted {age_days} days ago")
    if age_days <= 45:
        return ComponentScore(True, 40, f"Posted {age_days} days ago")
    return ComponentScore(True, 15, f"Posted {age_days} days ago")


def _resume_match(candidate: CandidateFeatures, job: Job) -> ComponentScore:
    if not candidate.has_resume or candidate.resume_profile is None:
        return ComponentScore(False, None, "No resume on file")
    result = resume_job_match.match(candidate.resume_text, candidate.resume_profile, job)
    return ComponentScore(True, result.overall, f"Resume-vs-job match engine score: {result.overall}%")


def _behavior_match(behavior: BehaviorSignals | None, job: JobFeatures) -> tuple[ComponentScore, list[str]]:
    """V21.4 PERSONALIZED RANKING — BEHAVIORAL SIGNALS component.
    ``behavior`` is None whenever personalization is off or the
    candidate has no meaningful learned signal yet (both are honest
    "unavailable" states, redistributed like any other missing
    component — never a phantom zero)."""
    if behavior is None:
        return ComponentScore(False, None, "Personalization is off, or no behavioral signal yet"), []
    affinity, reasons = job_affinity(behavior, job)
    if not reasons:
        return ComponentScore(False, None, "No behavioral signal for this company/location/skill/role yet"), []
    return ComponentScore(True, round(affinity), "; ".join(reasons)), reasons


def _deadline_urgency_match(job: JobFeatures) -> ComponentScore:
    """DEADLINE-AWARE RANKING: increase visibility as a verified
    deadline approaches. Never fabricated — a job with no deadline on
    file (common for rolling/private postings) is simply
    'unavailable' for this component, not penalized or boosted."""
    if job.deadline is None:
        return ComponentScore(False, None, "No deadline on file (rolling application)")
    days_left = (job.deadline - date.today()).days
    if days_left < 0:
        # Retrieval/Stage-1 already excludes expired jobs, but this
        # component is defensive against being called directly (e.g. a
        # future direct explanation lookup) — never claim urgency for
        # something that's actually already closed.
        return ComponentScore(False, None, "Deadline has passed")
    if days_left <= 2:
        return ComponentScore(True, 100, f"Deadline in {days_left} day(s) — apply soon")
    if days_left <= 5:
        return ComponentScore(True, 85, f"Deadline in {days_left} days")
    if days_left <= 14:
        return ComponentScore(True, 50, f"Deadline in {days_left} days")
    return ComponentScore(True, 20, f"Deadline in {days_left} days — no rush yet")


def compute(candidate: CandidateFeatures, job_row: Job, job: JobFeatures, behavior: BehaviorSignals | None = None) -> MatchResult:
    skill_score, matched, missing = _skill_match(candidate, job)

    negative_reasons: list[str] = []
    if skill_score.available and missing:
        negative_reasons.append(f"Missing required/preferred skill(s): {', '.join(missing[:5])}")

    missing_in_progress = sorted(set(missing) & candidate.learning_in_progress_skills)
    if missing_in_progress:
        negative_reasons.append(f"Already learning: {', '.join(missing_in_progress)} (in progress, not yet complete)")

    # INTERVIEW WEAKNESSES: call out when a missing skill was also
    # flagged as a weak area in the candidate's latest mock interview —
    # a stronger, more specific signal than a plain missing-skill note.
    interview_flagged_missing = sorted(set(missing) & set(candidate.interview_weak_topics))
    if interview_flagged_missing:
        negative_reasons.append(
            f"Flagged as a weak area in your last mock interview: {', '.join(interview_flagged_missing)}"
        )

    experience = _experience_match(candidate, job)
    if experience.available and experience.score is not None and experience.score < 40:
        negative_reasons.append("Experience signal is weaker than typically expected for this role")

    education = _education_match(candidate, job)
    if education.available and education.score is not None and education.score < 40:
        negative_reasons.append("Education section doesn't clearly overlap with the stated qualification")

    location = _location_match(candidate, job)
    if location.available and location.score is not None and location.score < 40:
        negative_reasons.append(f"Location '{job.location}' doesn't match your preferred locations")

    behavior_score, behavior_reasons = _behavior_match(behavior, job)
    deadline_urgency = _deadline_urgency_match(job)

    return MatchResult(
        skill=skill_score,
        experience=experience,
        education=education,
        location=location,
        career_goal=_career_goal_match(candidate, job),
        work_mode=_work_mode_match(candidate, job),
        employment_type=_employment_type_match(candidate, job),
        salary=_salary_match(candidate, job),
        resume=_resume_match(candidate, job_row),
        recency=_recency_match(job),
        behavior=behavior_score,
        deadline_urgency=deadline_urgency,
        matched_skills=matched,
        missing_skills_in_progress=missing_in_progress,
        missing_skills=missing,
        behavior_reasons=behavior_reasons,
        negative_reasons=negative_reasons,
    )
