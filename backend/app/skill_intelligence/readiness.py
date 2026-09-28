"""Explainable career readiness scores.

Every score is computed on demand (never persisted, never stale) from
data that already exists elsewhere:

- **Skill Coverage** — matched vs. total skills required by the target
  job (Phase 1 gap engine).
- **Technical Readiness** — Skill Coverage blended with completed
  priority-gap learning modules.
- **Interview Readiness** — latest ``MockInterviewReport.overall_score``
  (V20.4) as-is; unavailable if no completed interview yet.
- **Learning Progress** — aggregate completion percentage across the
  candidate's active/completed learning plans (Phase 2).
- **Role Readiness** — a fixed, documented weighted average of the
  above four; not a black-box or AI-generated score.

Each score always ships an ``explanation`` naming its inputs, a plain
reason, current weak areas, and a recommended next action — never a
bare number. A component that has no data yet contributes 0 and is
named explicitly in ``weak_areas``/``inputs_missing`` rather than
silently boosting or omitting the overall score.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import LearningPlan, LearningPlanModule, MockInterviewReport, MockInterviewSession
from app.skill_intelligence import gap as gap_engine

_WEIGHTS = {"skill_coverage": 0.35, "technical_readiness": 0.25, "interview_readiness": 0.25, "learning_progress": 0.15}


@dataclass
class ScoreComponent:
    name: str
    score: float | None  # 0-100, or None if there's no data to compute it
    inputs: list[str]
    reason: str
    weak_areas: list[str] = field(default_factory=list)
    recommended_action: str = ""


@dataclass
class ReadinessResult:
    role_readiness: float
    components: list[ScoreComponent]
    explanation: str


def _skill_coverage(gap_result: gap_engine.UnifiedSkillGapResult) -> ScoreComponent:
    total_priority = len(gap_result.priority_skills) + len(gap_result.recommended_skills) + len(gap_result.matched_skills)
    matched = len(gap_result.matched_skills)
    if total_priority == 0:
        return ScoreComponent(
            "skill_coverage", None, ["resume", "target job"],
            "No target job selected and no skills detected — cannot compute coverage yet.",
            weak_areas=["No target job or resume skills on file"],
            recommended_action="Upload a resume and select a target job.",
        )
    score = round(100 * matched / total_priority, 1)
    weak = [i.display_name for i in gap_result.priority_skills[:5]]
    return ScoreComponent(
        "skill_coverage", score, ["resume skills", "target job required skills"],
        f"{matched} of {total_priority} skills relevant to the target job are already matched.",
        weak_areas=weak,
        recommended_action="Close the highest-priority skill gaps first." if weak else "Keep skills up to date.",
    )


def _interview_readiness(db: Session, user_id: int) -> ScoreComponent:
    row = db.execute(
        select(MockInterviewReport)
        .join(MockInterviewSession, MockInterviewSession.id == MockInterviewReport.session_id)
        .where(MockInterviewSession.user_id == user_id)
        .order_by(MockInterviewReport.generated_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not row:
        return ScoreComponent(
            "interview_readiness", None, ["mock interview reports"],
            "No completed mock interview yet.",
            weak_areas=["No interview history"],
            recommended_action="Take a mock interview to establish a baseline.",
        )
    import json

    weaknesses = json.loads(row.weaknesses_json or "[]")
    return ScoreComponent(
        "interview_readiness", float(row.overall_score), ["latest mock interview report (overall_score)"],
        f"Latest mock interview overall score was {row.overall_score}/100.",
        weak_areas=weaknesses[:5],
        recommended_action="Review flagged weaknesses, then retake the interview." if weaknesses else "Keep practicing to maintain this level.",
    )


def _learning_progress(db: Session, user_id: int) -> ScoreComponent:
    plans = list(db.scalars(select(LearningPlan).where(LearningPlan.user_id == user_id, LearningPlan.status.in_(["active", "completed"]))))
    if not plans:
        return ScoreComponent(
            "learning_progress", None, ["learning plans"],
            "No active or completed learning plan yet.",
            weak_areas=["No learning plan in progress"],
            recommended_action="Generate a learning path from your current skill gap and start a plan.",
        )
    total = 0
    completed = 0
    for plan in plans:
        modules = list(db.scalars(select(LearningPlanModule).where(LearningPlanModule.plan_id == plan.id)))
        total += len(modules)
        completed += sum(1 for m in modules if m.status == "completed")
    score = round(100 * completed / total, 1) if total else 0.0
    return ScoreComponent(
        "learning_progress", score, [f"{len(plans)} learning plan(s)", f"{total} module(s)"],
        f"{completed} of {total} learning modules completed across {len(plans)} plan(s).",
        recommended_action="Continue working through your current plan's remaining modules." if score < 100 else "Plan complete — generate a fresh path for the next gap.",
    )


def compute(db: Session, user_id: int, target_job_id: int | None = None) -> ReadinessResult:
    gap_result = gap_engine.compute(db, user_id, target_job_id)
    coverage = _skill_coverage(gap_result)
    interview = _interview_readiness(db, user_id)
    progress = _learning_progress(db, user_id)

    # Technical readiness blends coverage with how much of the current
    # gap has already been worked through via learning modules.
    tech_inputs = ["skill_coverage", "learning_progress"]
    if coverage.score is not None and progress.score is not None:
        tech_score = round(0.6 * coverage.score + 0.4 * progress.score, 1)
        tech_reason = "Blend of current skill coverage and progress on the active learning plan."
    elif coverage.score is not None:
        tech_score = coverage.score
        tech_reason = "Based on skill coverage only — no learning plan in progress yet."
    else:
        tech_score = None
        tech_reason = "Not enough data yet — need a target job/resume and/or a learning plan."
    technical = ScoreComponent(
        "technical_readiness", tech_score, tech_inputs, tech_reason,
        weak_areas=coverage.weak_areas,
        recommended_action=coverage.recommended_action,
    )

    components = [coverage, technical, interview, progress]

    available = [(c, _WEIGHTS[c.name]) for c in components if c.name in _WEIGHTS and c.score is not None]
    if available:
        weight_sum = sum(w for _, w in available)
        role_readiness = round(sum(c.score * w for c, w in available) / weight_sum, 1)
        explanation = (
            f"Weighted average of {', '.join(c.name for c, _ in available)} "
            f"(weights renormalized because {len([c for c in components if c.score is None])} component(s) had no data yet)."
        )
    else:
        role_readiness = 0.0
        explanation = "No data available yet for any readiness component — upload a resume, select a target job, take a mock interview, or start a learning plan."

    return ReadinessResult(role_readiness=role_readiness, components=components, explanation=explanation)
