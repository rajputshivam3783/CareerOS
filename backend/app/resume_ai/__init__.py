"""V20.2 — AI Resume Intelligence.

Builds on the V20.1 AI Infrastructure layer (``app.ai``) and the V8
resume module (``app.services.resume_parser`` /
``app.services.resume_match``, both untouched and still used directly
by the existing ``POST /resume`` upload flow). Nothing in this package
calls a vendor SDK or vendor URL directly — every generative step goes
through ``app.ai.completion_service``, never a provider adapter.

Hard boundary, mirrored from ``app.services.career_ai`` (V6): **the AI
narrates, it never decides.** Every score in this package (resume
quality, ATS compatibility, skills, experience, education, projects,
keyword coverage, achievement strength, and every job-match dimension)
is computed by deterministic, rule-based code in ``scoring.py`` /
``ats_analysis.py`` / ``job_match.py`` — never by asking a model "what
score should this get". The only genuinely generative pieces are
wording — bullet rewrites, a summary paragraph, project-description
suggestions, and a plain-language narration of already-computed
job-specific advice — and every one of those prompts is built to only
reference facts already extracted from the candidate's own resume
text, with an explicit "never invent X" instruction and a
deterministic, no-provider-required fallback. See
AI_RESUME_PRIVACY.md for what "never invent" means in practice and how
it's enforced, not just requested.

Layout:
    extraction.py       Deterministic structured-field extraction from
                         resume text (name/email/phone/links/sections).
    normalization.py    Candidate profile normalization: skill aliases,
                         dedup, missing-section handling.
    scoring.py           Resume Quality / ATS / Content / Skills /
                         Experience / Education / Project / Keyword /
                         Achievement scores — all rule-based, all explained.
    ats_analysis.py      ATS readability, structure, keyword placement,
                         formatting risk, action verbs, achievement statements.
    job_match.py          Explainable, multi-dimension resume-vs-job score.
    skill_gap.py          Matched / missing / weak / transferable /
                         recommended / prioritized skill breakdown.
    recommendations.py   Deterministic, explainable improvement suggestions
                         (reason / impact / priority / suggested action).
    bullet_improver.py    Generative bullet rewrite (AI Gateway + fallback).
    summary_generator.py  Generative professional summary (AI Gateway + fallback).
    project_improver.py   Generative project-description suggestions
                         (AI Gateway + fallback).
    job_advice.py          Job-specific resume advice, narrated (AI Gateway
                         + fallback) on top of job_match/skill_gap output.
    cache.py              Content-hash cache for generative outputs — the
                         "avoid unnecessary LLM calls" cost control.
    pipeline.py            Orchestrates Upload -> Extract -> Normalize ->
                         Validate -> Analyze -> Score, and persists
                         ResumeAnalysis.

Out of scope for this pass (V20.3+, per ROADMAP.md): Career Copilot, AI
Interviewer, AI Learning System, AI Career Roadmap.
"""
