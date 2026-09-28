"""V20.4 — Interview context builder.

Pure, read-only composition of facts already computed elsewhere —
mirrors app.career_copilot.context_engine's own "compose on demand,
don't duplicate" stance. Nothing here calls an AI provider.

Reuses, never reimplements:
  * `app.resume_ai.pipeline.build_profile` — resume extraction/normalization (V20.2)
  * `app.resume_ai.skill_gap.analyze` — skill gap vs. a job (V20.2)
  * `app.resume_ai.job_match.match` — resume-vs-job explainable score (V20.2)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.domain import Job, MockInterviewSession, Resume
from app.resume_ai import job_match as job_match_module
from app.resume_ai import skill_gap as skill_gap_module
from app.resume_ai.normalization import NormalizedProfile
from app.resume_ai.pipeline import build_profile


@dataclass
class InterviewContext:
    job: Job | None = None
    resume_profile: NormalizedProfile | None = None
    skill_gap: skill_gap_module.SkillGapResult | None = None
    job_match: job_match_module.JobMatchResult | None = None
    focus_skills: list[str] = field(default_factory=list)
    known_project_names: list[str] = field(default_factory=list)


def build(db: Session, session: MockInterviewSession) -> InterviewContext:
    ctx = InterviewContext()

    if session.focus_skills:
        ctx.focus_skills = [s.strip() for s in session.focus_skills.split(",") if s.strip()]

    resume = db.get(Resume, session.user_id)
    if resume and resume.extracted_text:
        ctx.resume_profile = build_profile(resume)
        # Project *names* only, taken verbatim from the resume's own
        # extracted project-section lines — never invented. Used to
        # ground resume-based questions ("ask about Project X").
        ctx.known_project_names = list(ctx.resume_profile.project_entries)[:8]

    if session.job_id:
        job = db.get(Job, session.job_id)
        if job and job.status == "published":
            ctx.job = job
            if ctx.resume_profile:
                ctx.skill_gap = skill_gap_module.analyze(ctx.resume_profile, job)
                ctx.job_match = job_match_module.match(resume.extracted_text, ctx.resume_profile, job)

    return ctx


def facts_block(ctx: InterviewContext) -> str:
    """A compact, factual (never inferred-as-fact) summary for the AI
    prompt — the interview-engine equivalent of
    context_engine.to_prompt_text. Only states what is actually known;
    silent about anything not present, rather than guessing."""
    lines: list[str] = []
    if ctx.job:
        lines.append(
            f"Target job: {ctx.job.title} at {ctx.job.organization} "
            f"(qualification: {ctx.job.qualification}; experience required: {ctx.job.experience_required or 'not specified'}; "
            f"skills listed: {ctx.job.skills or 'not specified'})."
        )
    if ctx.resume_profile:
        lines.append(f"Candidate's resume lists these technical skills: {', '.join(ctx.resume_profile.technical_skills) or 'none extracted'}.")
        if ctx.known_project_names:
            lines.append("Candidate's resume project entries (verbatim): " + " | ".join(ctx.known_project_names))
    if ctx.focus_skills:
        lines.append(f"Candidate asked to focus on: {', '.join(ctx.focus_skills)}.")
    if ctx.skill_gap:
        lines.append(f"Skill gap vs. target job — missing: {', '.join(ctx.skill_gap.missing_skills) or 'none'}; weak: {', '.join(ctx.skill_gap.weak_skills) or 'none'}.")
    if not lines:
        lines.append("No job or resume on file for this session — ask generic, role-level questions only.")
    return "\n".join(lines)
