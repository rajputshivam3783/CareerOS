"""Explainable, multi-dimension resume-vs-job match score.

Builds on top of ``app.services.resume_match.match_resume_to_job``
(V8, untouched) for the skills+text-similarity signal, and adds the
Experience/Education/Keywords breakdown the V20.2 spec asks for — all
still deterministic, still explained. Location and job type are
reported as informational notes (see ``location_note``/``job_type_note``)
rather than scored dimensions: a resume rarely states a *desired*
location or job type explicitly, so scoring them would mean inferring
intent the candidate never stated — exactly the kind of invention this
system is built to avoid. See AI_RESUME_ARCHITECTURE.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.domain import Job, Profile
from app.resume_ai.normalization import NormalizedProfile, action_verb_count
from app.services.career import SKILLS, job_text
from app.services.resume_match import match_resume_to_job


@dataclass
class DimensionScore:
    score: int
    explanation: str


@dataclass
class JobMatchResult:
    overall: int
    skills: DimensionScore
    experience: DimensionScore
    education: DimensionScore
    keywords: DimensionScore
    matched_skills: list[str]
    missing_skills: list[str]
    location_note: str
    job_type_note: str
    engine: str = "CareerOS resume-vs-job match v2 (skills + experience signal + education signal + keyword coverage)"


def _experience_dimension(profile: NormalizedProfile, job: Job) -> DimensionScore:
    if not profile.experience_entries:
        return DimensionScore(0, "No experience section found in the resume")

    required = (job.experience_required or "").lower()
    verbs = action_verb_count(profile.experience_entries)
    base = min(70, len(profile.experience_entries) * 7)
    verb_bonus = min(30, verbs * 10)
    score = min(100, base + verb_bonus)

    if required:
        explanation = (
            f"Job lists required experience '{job.experience_required}'; resume has "
            f"{len(profile.experience_entries)} experience line(s) with {verbs} strong action verb(s). "
            "This is a structural read of the resume, not a verified years-of-experience match."
        )
    else:
        explanation = (
            f"Job doesn't specify a required experience level; resume has "
            f"{len(profile.experience_entries)} experience line(s) with {verbs} strong action verb(s)."
        )
    return DimensionScore(score, explanation)


def _education_dimension(profile: NormalizedProfile, job: Job) -> DimensionScore:
    if not profile.education_entries:
        return DimensionScore(0, "No education section found in the resume")

    qualification_text = (job.qualification or "").lower()
    education_text = " ".join(profile.education_entries).lower()

    # Deliberately simple, explainable token overlap — not a degree
    # equivalency judgment this system has no authority to make.
    qualification_tokens = {t.strip(".,") for t in qualification_text.split() if len(t) > 3}
    overlap = sorted(t for t in qualification_tokens if t in education_text)

    if qualification_tokens:
        score = min(100, 40 + len(overlap) * 15)
        explanation = (
            f"{len(overlap)} word(s) from the job's stated qualification also appear in the resume's education "
            f"section: {', '.join(overlap) or 'none'}. This is a text-overlap check, not a degree-equivalency verdict."
        )
    else:
        score = 60
        explanation = "Job does not state a specific qualification requirement to compare against; education section is present."

    return DimensionScore(score, explanation)


def _keywords_dimension(profile: NormalizedProfile, job: Job) -> DimensionScore:
    job_skills = sorted(s for s in SKILLS if s in job_text(job))
    if not job_skills:
        return DimensionScore(50, "Job listing doesn't reference any recognized keyword from the shared skills vocabulary")

    found = [s for s in job_skills if s in profile.technical_skills]
    pct = round((len(found) / len(job_skills)) * 100)
    return DimensionScore(
        pct, f"{len(found)} of {len(job_skills)} job keyword(s) found on the resume: {', '.join(found) or 'none'}"
    )


def match(resume_text: str, profile: NormalizedProfile, job: Job, candidate_profile: Profile | None = None) -> JobMatchResult:
    base = match_resume_to_job(resume_text, profile.technical_skills, job)

    skills_dim = DimensionScore(
        score=round(min(100, (len(base["matched_skills"]) / max(1, len(base["matched_skills"]) + len(base["missing_skills"]))) * 100)),
        explanation=(
            f"{len(base['matched_skills'])} matched, {len(base['missing_skills'])} missing skill(s) against the job's "
            f"recognized vocabulary: matched {base['matched_skills'] or 'none'}."
        ),
    )
    experience_dim = _experience_dimension(profile, job)
    education_dim = _education_dimension(profile, job)
    keywords_dim = _keywords_dimension(profile, job)

    overall = round(
        skills_dim.score * 0.40 + experience_dim.score * 0.25 + education_dim.score * 0.15 + keywords_dim.score * 0.20
    )

    location_note = "Job location not specified" if not job.location else f"Job location: {job.location}."
    if candidate_profile and candidate_profile.location:
        location_note += f" Candidate's stated location: {candidate_profile.location}. (Informational only — not scored.)"
    else:
        location_note += " Candidate location not on file — not scored."

    job_type_note = f"Job type: {job.job_type or 'not specified'}. (Informational only — not scored; resumes rarely state a desired job type explicitly.)"

    return JobMatchResult(
        overall=overall,
        skills=skills_dim,
        experience=experience_dim,
        education=education_dim,
        keywords=keywords_dim,
        matched_skills=base["matched_skills"],
        missing_skills=base["missing_skills"],
        location_note=location_note,
        job_type_note=job_type_note,
    )
