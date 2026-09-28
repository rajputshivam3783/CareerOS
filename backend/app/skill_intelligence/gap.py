"""Unified, explainable skill-gap view for one candidate.

This composes three existing, unmodified sources — it does not
re-implement any of them:

- **Resume vs. target job** — ``app.resume_ai.skill_gap.analyze``
  (V20.2), given the candidate's stored ``Resume`` (via
  ``app.resume_ai.pipeline.build_profile``) and a target ``Job``.
- **Career goal** — ``CareerPreference.preferred_skills`` /
  ``target_role`` (V20.3), read as-is via ``db.get``.
- **Interview performance** — the latest completed
  ``MockInterviewReport.technical_gaps_json`` /
  ``recommended_topics_json`` per session (V20.4), read as-is.

Every skill mentioned by any source is normalized against the
canonical catalog (app.skill_intelligence.normalization) so the same
skill named differently in a resume, a job listing, and an interview
report collapses to one row instead of three. A name with no catalog
match is kept as "unrecognized" (see AI_SAFETY.md) rather than
silently dropped or invented into a new canonical skill.

Priority scoring here is a fixed, inspectable formula over these
signals (job requirement, interview weakness, prerequisite depth) —
never a black-box or AI-generated ranking. If a signal is unavailable
(no target job selected, no completed interview yet), its contribution
is simply omitted rather than fabricated, and the result says so.

Government exam integration: when the target job is a Government-type
listing (``Job.job_type == "Government"``), the result also carries
``verified_exam_resources`` — admin-curated ``ExamPrepResource`` rows
(syllabus/previous-papers/mock-test/cutoff links, V8) attached to that
job. Eligibility, syllabus content, and exam requirements are never
inferred or generated here — only these existing verified links are
surfaced, exactly per AI_SAFETY.md's "never fabricate eligibility or
syllabus" rule. Skill matching for a government job uses the same
``Job.skills``/``Job.qualification`` fields every other job already
provides — there is no separate government skill-matching path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import CareerPreference, ExamPrepResource, Job, MockInterviewReport, MockInterviewSession, Resume, Skill
from app.resume_ai import pipeline, skill_gap as resume_skill_gap
from app.skill_intelligence import graph, normalization


@dataclass
class SkillGapItem:
    canonical_name: str
    display_name: str
    category: str
    subcategory: str
    source_signals: list[str]  # e.g. ["missing_from_target_job", "weak_interview_performance"]
    priority_score: int  # 0-100, explainable via `reason`
    reason: str
    prerequisites: list[str] = field(default_factory=list)


@dataclass
class ExamResourceRef:
    title: str
    resource_type: str
    url: str
    organization: str
    exam_name: str


@dataclass
class UnifiedSkillGapResult:
    matched_skills: list[str]
    priority_skills: list[SkillGapItem]
    recommended_skills: list[SkillGapItem]
    unrecognized_inputs: list[str]  # free-text skills that didn't resolve to the catalog
    signals_used: list[str]  # which of resume/job/career-goal/interview data were actually available
    signals_unavailable: list[str]  # explicitly named, never silently omitted
    is_government_target: bool = False
    verified_exam_resources: list[ExamResourceRef] = field(default_factory=list)


def _latest_interview_gaps(db: Session, user_id: int) -> tuple[list[str], list[str]]:
    """Technical gaps + recommended topics from the candidate's most
    recently generated MockInterviewReport, if any."""

    row = db.execute(
        select(MockInterviewReport)
        .join(MockInterviewSession, MockInterviewSession.id == MockInterviewReport.session_id)
        .where(MockInterviewSession.user_id == user_id)
        .order_by(MockInterviewReport.generated_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if row is None:
        return [], []

    import json

    def _parse(text: str) -> list[str]:
        try:
            value = json.loads(text or "[]")
            return [str(v) for v in value] if isinstance(value, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    return _parse(row.technical_gaps_json), _parse(row.recommended_topics_json)


def compute(db: Session, user_id: int, target_job_id: int | None = None) -> UnifiedSkillGapResult:
    signals_used: list[str] = []
    signals_unavailable: list[str] = []

    job_missing: list[str] = []
    job_matched: list[str] = []
    prioritized_from_job: dict[str, dict] = {}

    resume = db.get(Resume, user_id)
    job = db.get(Job, target_job_id) if target_job_id else None

    if resume and job:
        profile = pipeline.build_profile(resume)
        result = resume_skill_gap.analyze(profile, job)
        job_missing = result.missing_skills
        job_matched = result.matched_skills
        for gap in result.prioritized_gaps:
            prioritized_from_job[gap["skill"]] = gap
        signals_used.append("resume_vs_target_job")
    elif not resume:
        signals_unavailable.append("resume (no resume uploaded)")
    elif not job:
        signals_unavailable.append("target_job (none selected)")

    is_government = bool(job and job.job_type == "Government")
    exam_resources: list[ExamResourceRef] = []
    if is_government and job:
        rows = list(db.scalars(select(ExamPrepResource).where(ExamPrepResource.job_id == job.id)))
        exam_resources = [
            ExamResourceRef(
                title=r.title, resource_type=r.resource_type, url=r.url,
                organization=r.organization, exam_name=r.exam_name,
            )
            for r in rows
        ]
        signals_used.append("government_exam_target")

    prefs = db.get(CareerPreference, user_id)
    goal_skills: list[str] = []
    if prefs and prefs.preferred_skills:
        goal_skills = [s.strip() for s in prefs.preferred_skills.split(",") if s.strip()]
        signals_used.append("career_goal_preferred_skills")
    else:
        signals_unavailable.append("career_goal (no preferred skills set)")

    interview_gaps, interview_topics = _latest_interview_gaps(db, user_id)
    if interview_gaps or interview_topics:
        signals_used.append("latest_interview_report")
    else:
        signals_unavailable.append("interview_performance (no completed mock interview yet)")

    # Normalize everything against the canonical catalog in one pass.
    all_names = job_missing + goal_skills + interview_gaps + interview_topics
    resolved, unrecognized = normalization.resolve_many(db, all_names)
    matched_resolved, _ = normalization.resolve_many(db, job_matched)
    matched_names = sorted({r.skill.canonical_name for r in matched_resolved})

    resolved_by_name: dict[str, Skill] = {r.input_text.strip().lower(): r.skill for r in resolved}

    def _find(name: str) -> Skill | None:
        return resolved_by_name.get(name.strip().lower())

    items: dict[int, SkillGapItem] = {}

    def _add(skill: Skill, signal: str, base_score: int, reason: str) -> None:
        existing = items.get(skill.id)
        if existing:
            if signal not in existing.source_signals:
                existing.source_signals.append(signal)
                existing.priority_score = min(100, existing.priority_score + base_score // 2)
                existing.reason += f"; {reason}"
            return
        prereqs = [p.canonical_name for p in graph.prerequisites_for(db, skill)]
        items[skill.id] = SkillGapItem(
            canonical_name=skill.canonical_name,
            display_name=skill.display_name,
            category=skill.category,
            subcategory=skill.subcategory,
            source_signals=[signal],
            priority_score=min(100, base_score),
            reason=reason,
            prerequisites=prereqs,
        )

    for name in job_missing:
        skill = _find(name)
        if not skill:
            continue
        gap_meta = prioritized_from_job.get(name, {})
        mentions = gap_meta.get("mentions_in_job", 0)
        score = 60 + min(20, mentions * 5)
        default_reason = "Required by this government exam listing" if is_government else "Required by the target job"
        signal = "government_exam_requirement" if is_government else "missing_from_target_job"
        _add(skill, signal, score, gap_meta.get("reason", default_reason))

    for name in interview_gaps:
        skill = _find(name)
        if not skill:
            continue
        _add(skill, "weak_interview_performance", 70, "Flagged as a technical gap in the most recent mock interview")

    for name in interview_topics:
        skill = _find(name)
        if not skill:
            continue
        _add(skill, "recommended_by_interview_report", 40, "Recommended follow-up topic from the most recent mock interview")

    for name in goal_skills:
        skill = _find(name)
        if not skill:
            continue
        _add(skill, "career_goal", 30, "Listed among the candidate's stated preferred/goal skills")

    ranked = sorted(items.values(), key=lambda i: i.priority_score, reverse=True)
    priority = [i for i in ranked if len(i.source_signals) > 1 or i.priority_score >= 60]
    recommended = [i for i in ranked if i not in priority]

    return UnifiedSkillGapResult(
        matched_skills=matched_names,
        priority_skills=priority,
        recommended_skills=recommended,
        unrecognized_inputs=sorted(set(unrecognized)),
        signals_used=signals_used,
        signals_unavailable=signals_unavailable,
        is_government_target=is_government,
        verified_exam_resources=exam_resources,
    )
