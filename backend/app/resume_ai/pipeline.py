"""Orchestrates Extract -> Normalize -> Validate -> Analyze -> Score
for a candidate's stored resume, and persists the result.

Deliberately starts from an already-uploaded ``Resume`` row — Upload
itself is untouched, existing V8 functionality (``POST /resume`` in
app.api.platform). "Validate" here means computing
``confidence``/``missing_sections`` flags, not rejecting anything: a
sparse resume still produces a full, honest analysis with more fields
flagged "Not found in resume" rather than an error.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from sqlalchemy.orm import Session

from app.models.domain import Resume, ResumeAnalysis
from app.resume_ai import ats_analysis, extraction, normalization, scoring
from app.resume_ai.normalization import NormalizedProfile


def build_profile(resume: Resume) -> NormalizedProfile:
    """Extract + Normalize. Pure function of the stored resume text —
    safe to call as often as needed with no cost (no AI call here)."""
    extracted = extraction.extract(resume.extracted_text)
    return normalization.normalize(extracted, resume.extracted_text)


def analyze_and_score(profile: NormalizedProfile, has_tables_or_columns: bool | None) -> dict:
    """Analyze -> Score. Returns every component score plus the ATS
    analysis, all deterministic — see scoring.py/ats_analysis.py.
    Takes the layout signal directly (rather than a ``Resume`` row) so
    it works identically for the candidate's own stored resume and for
    a recruiter analyzing an ``Applicant.resume_snapshot``, which has
    no ``Resume`` row of its own — see app.api.resume_ai.
    """
    components = {
        "content_quality": scoring.content_quality_score(profile),
        "ats_compatibility": scoring.ats_compatibility_score(profile, has_tables_or_columns),
        "skills": scoring.skills_score(profile),
        "experience": scoring.experience_score(profile),
        "education": scoring.education_score(profile),
        "project": scoring.project_score(profile),
        "keyword_coverage": scoring.keyword_coverage_score(profile),
        "achievement_strength": scoring.achievement_strength_score(profile),
        "contact_info": scoring.contact_info_score(profile),
    }
    overall = scoring.resume_quality_score(components)

    ats = ats_analysis.analyze(profile, has_tables_or_columns=has_tables_or_columns)

    return {
        "overall": {"score": overall.score, "reasons": overall.reasons},
        "components": {name: {"score": r.score, "reasons": r.reasons} for name, r in components.items()},
        "ats": asdict(ats),
    }


def run_and_persist(db: Session, resume: Resume) -> ResumeAnalysis:
    """Full pipeline for the candidate's own stored resume, persisting
    the latest result (replaces any previous analysis for this user,
    same "working document, not an archive" posture as Resume itself).
    """
    profile = build_profile(resume)
    scores = analyze_and_score(profile, resume.has_tables_or_columns)

    record = db.get(ResumeAnalysis, resume.user_id) or ResumeAnalysis(user_id=resume.user_id)
    record.profile_json = json.dumps(asdict(profile))
    record.scores_json = json.dumps(scores)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def profile_from_text(resume_text: str) -> NormalizedProfile:
    """Same Extract -> Normalize path, for text that isn't backed by a
    stored ``Resume`` row (e.g. a recruiter analyzing an
    ``Applicant.resume_snapshot`` — see app.api.resume_ai)."""
    extracted = extraction.extract(resume_text)
    return normalization.normalize(extracted, resume_text)
