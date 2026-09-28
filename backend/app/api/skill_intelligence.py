"""V20.5 (Phase 1) — Skill Intelligence APIs.

Reuses, never rewrites: ``current_user`` (app.core.security), the
admin ``guard`` (app.api.admin), and every V20.2/V20.3/V20.4 model and
service this touches — see app.skill_intelligence.gap's module
docstring for the exact composition. No second skill-gap or career
engine is created here.

Auth split:
- ``GET /skills*`` (browse/search the catalog, view the graph) is
  read-only and available to any authenticated user — it's reference
  data, not personal data.
- ``GET /skill-intelligence/gap`` operates only on the calling user's
  own resume/preferences/interview history — no user_id parameter.
- ``/admin/skills*`` (create/edit skills, aliases, relationships, and
  triggering a re-seed) is admin-only via ``app.api.admin.guard``,
  exactly like every other admin-only route in this codebase.
"""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.admin import guard as admin_guard
from app.core.security import current_user
from app.db.session import get_db
from app.models.domain import (
    AssessmentAttempt,
    AssessmentQuestion,
    LearningPlan,
    LearningPlanModule,
    LearningResource,
    Skill,
    SkillAlias,
    SkillAssessment,
    SkillRelationship,
    User,
)
from app.search.hooks import sync_learning_resource, sync_skill
from app.skill_intelligence import (
    assessments as assessments_engine,
    catalog,
    gap as gap_engine,
    graph,
    learning_path,
    normalization,
    plans as plans_engine,
    practice as practice_engine,
    readiness as readiness_engine,
    resources,
    roadmap as roadmap_engine,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SkillOut(BaseModel):
    id: int
    canonical_name: str
    display_name: str
    category: str
    subcategory: str
    difficulty: str
    description: str | None = None

    class Config:
        from_attributes = True


class SkillGraphOut(BaseModel):
    skill: SkillOut
    prerequisites: list[SkillOut]
    related: list[SkillOut]
    advanced_versions: list[SkillOut]
    alternatives: list[SkillOut]
    complementary: list[SkillOut]
    learning_order: list[SkillOut]


class SkillGapItemOut(BaseModel):
    canonical_name: str
    display_name: str
    category: str
    subcategory: str
    source_signals: list[str]
    priority_score: int
    reason: str
    prerequisites: list[str]


class ExamResourceOut(BaseModel):
    title: str
    resource_type: str
    url: str
    organization: str
    exam_name: str


class SkillGapOut(BaseModel):
    matched_skills: list[str]
    priority_skills: list[SkillGapItemOut]
    recommended_skills: list[SkillGapItemOut]
    unrecognized_inputs: list[str]
    signals_used: list[str]
    signals_unavailable: list[str]
    is_government_target: bool = False
    verified_exam_resources: list[ExamResourceOut] = []


class SkillCreateIn(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=120)
    category: str = Field(pattern="^(technical|soft)$")
    subcategory: str = Field(min_length=1, max_length=40)
    difficulty: str = Field(default="beginner", pattern="^(beginner|intermediate|advanced|expert)$")
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)


class AliasCreateIn(BaseModel):
    alias: str = Field(min_length=1, max_length=120)


class RelationshipCreateIn(BaseModel):
    to_canonical_name: str
    relationship_type: str = Field(pattern="^(prerequisite|related|advanced_version|alternative|complementary)$")


class ResourceOut(BaseModel):
    id: int
    skill_id: int
    title: str
    provider: str | None = None
    url: str | None = None
    resource_type: str
    difficulty: str
    duration_minutes: int | None = None
    language: str
    is_free: bool
    rating: float | None = None
    status: str
    is_verified: bool
    objective: str | None = None
    requirements: str | None = None
    expected_output: str | None = None
    evaluation_criteria: str | None = None

    class Config:
        from_attributes = True


class ResourceCreateIn(BaseModel):
    skill_canonical_name: str
    title: str = Field(min_length=1, max_length=220)
    provider: str | None = None
    url: str | None = None
    resource_type: str = Field(pattern="^(course|book|documentation|article|video|tutorial|practice_platform|project|certification)$")
    difficulty: str = Field(default="beginner", pattern="^(beginner|intermediate|advanced|expert)$")
    duration_minutes: int | None = None
    language: str = "English"
    is_free: bool = True
    rating: float | None = None
    status: str = Field(default="draft", pattern="^(draft|published|archived)$")
    is_verified: bool = False
    # Structured project-brief fields — only meaningful when
    # resource_type == "project" (spec: Objective/Requirements/
    # Expected Output/Evaluation Criteria; Skills/Difficulty already
    # covered by skill_canonical_name/difficulty above).
    objective: str | None = None
    requirements: str | None = None
    expected_output: str | None = None
    evaluation_criteria: str | None = None


class ResourceUpdateIn(BaseModel):
    title: str | None = None
    provider: str | None = None
    url: str | None = None
    difficulty: str | None = Field(default=None, pattern="^(beginner|intermediate|advanced|expert)$")
    duration_minutes: int | None = None
    language: str | None = None
    is_free: bool | None = None
    rating: float | None = None
    status: str | None = Field(default=None, pattern="^(draft|published|archived)$")
    is_verified: bool | None = None
    objective: str | None = None
    requirements: str | None = None
    expected_output: str | None = None
    evaluation_criteria: str | None = None


class PathStepOut(BaseModel):
    skill: SkillOut
    reason: str
    resource: ResourceOut | None = None


class PathPreviewOut(BaseModel):
    steps: list[PathStepOut]
    unresourced_skill_names: list[str]
    signals_used: list[str]
    signals_unavailable: list[str]


class PlanCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=220)
    target_job_id: int | None = None
    target_date: str | None = None  # ISO date, optional
    weekly_goal_hours: float | None = None
    max_priority_skills: int = Field(default=6, ge=1, le=20)


class ModuleOut(BaseModel):
    id: int
    plan_id: int
    skill_id: int
    resource_id: int | None
    order_index: int
    status: str
    time_spent_minutes: int

    class Config:
        from_attributes = True


class PlanOut(BaseModel):
    id: int
    title: str
    target_skill_id: int | None
    target_job_id: int | None
    status: str
    target_date: str | None = None
    weekly_goal_hours: float | None
    modules: list[ModuleOut]
    current_streak_days: int = 0
    longest_streak_days: int = 0


class StatusUpdateIn(BaseModel):
    status: str = Field(pattern="^(active|paused|completed|cancelled)$")


class TargetDateIn(BaseModel):
    target_date: str | None = None  # ISO date or null to clear


class WeeklyGoalIn(BaseModel):
    weekly_goal_hours: float | None = None


class TimeLogIn(BaseModel):
    minutes: int = Field(ge=1, le=1440)


class ReorderIn(BaseModel):
    ordered_module_ids: list[int]


class ProgressOut(BaseModel):
    plan_id: int
    total_modules: int
    completed: int
    in_progress: int
    skipped: int
    not_started: int
    completion_percentage: float
    total_time_spent_minutes: int
    current_streak_days: int
    longest_streak_days: int


class AssessmentOut(BaseModel):
    id: int
    skill_id: int
    title: str
    assessment_type: str
    difficulty: str
    status: str

    class Config:
        from_attributes = True


class QuestionCreateIn(BaseModel):
    prompt: str = Field(min_length=1)
    options: list[str] = Field(min_length=2, max_length=8)
    correct_option: int = Field(ge=0)
    topic: str = Field(min_length=1, max_length=80)
    difficulty: str = Field(default="beginner", pattern="^(beginner|intermediate|advanced|expert)$")
    explanation: str | None = None


class AssessmentCreateIn(BaseModel):
    skill_canonical_name: str
    title: str = Field(min_length=1, max_length=220)
    assessment_type: str = Field(default="mcq", pattern="^(mcq|coding|scenario|technical|behavioral)$")
    difficulty: str = Field(default="beginner", pattern="^(beginner|intermediate|advanced|expert)$")
    status: str = Field(default="draft", pattern="^(draft|published|archived)$")


class QuestionOut(BaseModel):
    id: int
    prompt: str
    options: list[str]
    topic: str
    difficulty: str
    # correct_option / explanation deliberately withheld from the
    # candidate-facing question list — see /assessments/{id}/questions


class AttemptOut(BaseModel):
    id: int
    assessment_id: int
    status: str
    total_questions: int
    correct_count: int
    score_percentage: float | None
    weak_topics: list[str]


class AnswerSubmitIn(BaseModel):
    question_id: int
    selected_option: int


class SubmitAttemptIn(BaseModel):
    answers: list[AnswerSubmitIn]


class PracticeSuggestionOut(BaseModel):
    skill: SkillOut
    recommendation_type: str
    reason: str
    priority_score: int
    project: ResourceOut | None = None


class ReadinessComponentOut(BaseModel):
    name: str
    score: float | None
    inputs: list[str]
    reason: str
    weak_areas: list[str]
    recommended_action: str


class ReadinessOut(BaseModel):
    role_readiness: float
    components: list[ReadinessComponentOut]
    explanation: str


class RoadmapStageOut(BaseModel):
    stage: str
    summary: str
    items: list[str]


class RoadmapOut(BaseModel):
    goal: str
    stages: list[RoadmapStageOut]


# ---------------------------------------------------------------------------
# Candidate-facing: browse catalog + graph
# ---------------------------------------------------------------------------


@router.get("/skills", response_model=list[SkillOut], tags=["V20.5 Skill Intelligence"])
def list_skills(
    q: str | None = Query(default=None, description="Filter by canonical/display name substring"),
    category: str | None = Query(default=None),
    subcategory: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _u: User = Depends(current_user),
) -> list[Skill]:
    # V20.6 performance fix: previously loaded every row and filtered
    # `q` in Python — pushed into SQL (ILIKE, cross-dialect via
    # SQLAlchemy) plus a bounded `limit` so this stays cheap as the
    # catalog grows past its current ~46-skill seed size.
    stmt = select(Skill)
    if category:
        stmt = stmt.where(Skill.category == category)
    if subcategory:
        stmt = stmt.where(Skill.subcategory == subcategory)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(Skill.canonical_name.ilike(needle) | Skill.display_name.ilike(needle))
    stmt = stmt.order_by(Skill.display_name).limit(limit)
    return list(db.scalars(stmt))


@router.get("/skills/{canonical_name}/graph", response_model=SkillGraphOut, tags=["V20.5 Skill Intelligence"])
def skill_graph(canonical_name: str, db: Session = Depends(get_db), _u: User = Depends(current_user)) -> dict:
    skill = normalization.resolve(db, canonical_name)
    if not skill:
        raise HTTPException(404, "Skill not found in catalog")
    n = graph.neighbors(db, skill)
    order = graph.learning_order(db, skill)
    return {
        "skill": skill,
        "prerequisites": n.prerequisites,
        "related": n.related,
        "advanced_versions": n.advanced_versions,
        "alternatives": n.alternatives,
        "complementary": n.complementary,
        "learning_order": order,
    }


# ---------------------------------------------------------------------------
# Candidate-facing: unified skill gap
# ---------------------------------------------------------------------------


@router.get("/skill-intelligence/gap", response_model=SkillGapOut, tags=["V20.5 Skill Intelligence"])
def unified_skill_gap(
    target_job_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    u: User = Depends(current_user),
) -> gap_engine.UnifiedSkillGapResult:
    return gap_engine.compute(db, u.id, target_job_id)


# ---------------------------------------------------------------------------
# Admin: catalog management
# ---------------------------------------------------------------------------


@router.post("/admin/skills/seed", tags=["V20.5 Skill Intelligence Admin"], dependencies=[Depends(admin_guard)])
def seed_catalog(db: Session = Depends(get_db)) -> dict:
    """Idempotent — safe to call repeatedly (e.g. after deploying a
    catalog.py update); never overwrites rows an admin has since
    edited by hand."""
    return catalog.seed_skills(db)


@router.get("/admin/skills", response_model=list[SkillOut], tags=["V20.5 Skill Intelligence Admin"], dependencies=[Depends(admin_guard)])
def admin_list_skills(limit: int = Query(default=200, ge=1, le=1000), db: Session = Depends(get_db)) -> list[Skill]:
    return list(db.scalars(select(Skill).order_by(Skill.display_name).limit(limit)))


@router.post("/admin/skills", response_model=SkillOut, tags=["V20.5 Skill Intelligence Admin"], dependencies=[Depends(admin_guard)])
def admin_create_skill(body: SkillCreateIn, db: Session = Depends(get_db)) -> Skill:
    canonical = body.canonical_name.strip().lower()
    existing = db.scalar(select(Skill).where(Skill.canonical_name == canonical))
    if existing:
        raise HTTPException(409, "A skill with this canonical_name already exists — add an alias instead")

    skill = Skill(
        canonical_name=canonical,
        display_name=body.display_name.strip(),
        category=body.category,
        subcategory=body.subcategory.strip().lower(),
        difficulty=body.difficulty,
        description=body.description,
        is_admin_added=True,
    )
    db.add(skill)
    db.flush()
    for alias in body.aliases:
        clean = alias.strip().lower()
        if clean and clean != canonical and not db.scalar(select(SkillAlias).where(SkillAlias.alias == clean)):
            db.add(SkillAlias(skill_id=skill.id, alias=clean))
    db.commit()
    sync_skill(db, skill.id)  # V21.1 Phase 3
    db.refresh(skill)
    return skill


@router.post("/admin/skills/{skill_id}/aliases", response_model=SkillOut, tags=["V20.5 Skill Intelligence Admin"], dependencies=[Depends(admin_guard)])
def admin_add_alias(skill_id: int, body: AliasCreateIn, db: Session = Depends(get_db)) -> Skill:
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(404, "Skill not found")
    clean = body.alias.strip().lower()
    conflict = db.scalar(select(SkillAlias).where(SkillAlias.alias == clean))
    if conflict or clean == skill.canonical_name:
        raise HTTPException(409, "Alias already in use — skills must stay deduplicated")
    db.add(SkillAlias(skill_id=skill.id, alias=clean))
    db.commit()
    sync_skill(db, skill.id)  # V21.1 Phase 3 — an alias doesn't change SearchIndexDocument's own columns today, but re-syncing keeps it correct if that ever changes
    db.refresh(skill)
    return skill


@router.post("/admin/skills/{skill_id}/relationships", tags=["V20.5 Skill Intelligence Admin"], dependencies=[Depends(admin_guard)])
def admin_add_relationship(skill_id: int, body: RelationshipCreateIn, db: Session = Depends(get_db)) -> dict:
    from_skill = db.get(Skill, skill_id)
    if not from_skill:
        raise HTTPException(404, "Skill not found")
    to_skill = normalization.resolve(db, body.to_canonical_name)
    if not to_skill:
        raise HTTPException(404, "Target skill not found in catalog — create it first")

    existing = db.scalar(
        select(SkillRelationship).where(
            SkillRelationship.from_skill_id == from_skill.id,
            SkillRelationship.to_skill_id == to_skill.id,
            SkillRelationship.relationship_type == body.relationship_type,
        )
    )
    if existing:
        raise HTTPException(409, "This relationship already exists")

    db.add(
        SkillRelationship(
            from_skill_id=from_skill.id, to_skill_id=to_skill.id, relationship_type=body.relationship_type
        )
    )
    db.commit()
    return {"from": from_skill.canonical_name, "to": to_skill.canonical_name, "type": body.relationship_type}


# ---------------------------------------------------------------------------
# Candidate-facing: resources (verified/published only)
# ---------------------------------------------------------------------------


@router.get("/resources", response_model=list[ResourceOut], tags=["V20.5 Learning & Resources"])
def list_resources(
    skill: str = Query(..., description="Canonical or alias skill name"),
    db: Session = Depends(get_db),
    _u: User = Depends(current_user),
) -> list[LearningResource]:
    s = normalization.resolve(db, skill)
    if not s:
        raise HTTPException(404, "Skill not found in catalog")
    return resources.published_for_skill(db, s.id)


# ---------------------------------------------------------------------------
# Candidate-facing: learning path preview + plans
# ---------------------------------------------------------------------------


def _plan_out(plan: LearningPlan, modules: list[LearningPlanModule]) -> dict:
    return {
        "id": plan.id,
        "title": plan.title,
        "target_skill_id": plan.target_skill_id,
        "target_job_id": plan.target_job_id,
        "status": plan.status,
        "target_date": plan.target_date.isoformat() if plan.target_date else None,
        "weekly_goal_hours": plan.weekly_goal_hours,
        "modules": sorted(modules, key=lambda m: m.order_index),
        "current_streak_days": plan.current_streak_days,
        "longest_streak_days": plan.longest_streak_days,
    }


@router.get("/learning-path/preview", response_model=PathPreviewOut, tags=["V20.5 Learning & Resources"])
def preview_learning_path(
    target_job_id: int | None = Query(default=None),
    max_priority_skills: int = Query(default=6, ge=1, le=20),
    db: Session = Depends(get_db),
    u: User = Depends(current_user),
) -> dict:
    draft = learning_path.build(db, u.id, target_job_id, max_priority_skills)
    return {
        "steps": [{"skill": s.skill, "reason": s.reason, "resource": s.resource} for s in draft.steps],
        "unresourced_skill_names": draft.unresourced_skill_names,
        "signals_used": draft.based_on.signals_used,
        "signals_unavailable": draft.based_on.signals_unavailable,
    }


@router.post("/learning-plans", response_model=PlanOut, tags=["V20.5 Learning & Resources"])
def create_learning_plan(body: PlanCreateIn, db: Session = Depends(get_db), u: User = Depends(current_user)) -> dict:
    draft = learning_path.build(db, u.id, body.target_job_id, body.max_priority_skills)
    target_date = date.fromisoformat(body.target_date) if body.target_date else None
    plan = plans_engine.create_from_draft(
        db, u.id, draft, body.title, body.target_job_id, target_date, body.weekly_goal_hours
    )
    modules = list(db.scalars(select(LearningPlanModule).where(LearningPlanModule.plan_id == plan.id)))
    return _plan_out(plan, modules)


@router.get("/learning-plans", response_model=list[PlanOut], tags=["V20.5 Learning & Resources"])
def list_learning_plans(db: Session = Depends(get_db), u: User = Depends(current_user)) -> list[dict]:
    plan_rows = list(db.scalars(select(LearningPlan).where(LearningPlan.user_id == u.id).order_by(LearningPlan.id.desc())))
    out = []
    for plan in plan_rows:
        modules = list(db.scalars(select(LearningPlanModule).where(LearningPlanModule.plan_id == plan.id)))
        out.append(_plan_out(plan, modules))
    return out


@router.get("/learning-plans/{plan_id}", response_model=PlanOut, tags=["V20.5 Learning & Resources"])
def get_learning_plan(plan_id: int, db: Session = Depends(get_db), u: User = Depends(current_user)) -> dict:
    plan = db.get(LearningPlan, plan_id)
    if not plan or plan.user_id != u.id:
        raise HTTPException(404, "Learning plan not found")
    modules = list(db.scalars(select(LearningPlanModule).where(LearningPlanModule.plan_id == plan.id)))
    return _plan_out(plan, modules)


@router.put("/learning-plans/{plan_id}/status", response_model=PlanOut, tags=["V20.5 Learning & Resources"])
def update_plan_status(plan_id: int, body: StatusUpdateIn, db: Session = Depends(get_db), u: User = Depends(current_user)) -> dict:
    plan = plans_engine.set_status(db, plan_id, u.id, body.status)
    modules = list(db.scalars(select(LearningPlanModule).where(LearningPlanModule.plan_id == plan.id)))
    return _plan_out(plan, modules)


@router.put("/learning-plans/{plan_id}/target-date", response_model=PlanOut, tags=["V20.5 Learning & Resources"])
def update_plan_target_date(plan_id: int, body: TargetDateIn, db: Session = Depends(get_db), u: User = Depends(current_user)) -> dict:
    target_date = date.fromisoformat(body.target_date) if body.target_date else None
    plan = plans_engine.set_target_date(db, plan_id, u.id, target_date)
    modules = list(db.scalars(select(LearningPlanModule).where(LearningPlanModule.plan_id == plan.id)))
    return _plan_out(plan, modules)


@router.put("/learning-plans/{plan_id}/weekly-goal", response_model=PlanOut, tags=["V20.5 Learning & Resources"])
def update_plan_weekly_goal(plan_id: int, body: WeeklyGoalIn, db: Session = Depends(get_db), u: User = Depends(current_user)) -> dict:
    plan = plans_engine.set_weekly_goal(db, plan_id, u.id, body.weekly_goal_hours)
    modules = list(db.scalars(select(LearningPlanModule).where(LearningPlanModule.plan_id == plan.id)))
    return _plan_out(plan, modules)


@router.put("/learning-plans/{plan_id}/modules/reorder", response_model=PlanOut, tags=["V20.5 Learning & Resources"])
def reorder_modules(plan_id: int, body: ReorderIn, db: Session = Depends(get_db), u: User = Depends(current_user)) -> dict:
    plans_engine.reorder(db, plan_id, u.id, body.ordered_module_ids)
    plan = db.get(LearningPlan, plan_id)
    modules = list(db.scalars(select(LearningPlanModule).where(LearningPlanModule.plan_id == plan.id)))
    return _plan_out(plan, modules)


@router.post("/learning-plans/{plan_id}/modules/{module_id}/start", response_model=ModuleOut, tags=["V20.5 Learning & Resources"])
def start_module(plan_id: int, module_id: int, db: Session = Depends(get_db), u: User = Depends(current_user)) -> LearningPlanModule:
    return plans_engine.start_module(db, plan_id, module_id, u.id)


@router.post("/learning-plans/{plan_id}/modules/{module_id}/complete", response_model=ModuleOut, tags=["V20.5 Learning & Resources"])
def complete_module(plan_id: int, module_id: int, body: TimeLogIn | None = None, db: Session = Depends(get_db), u: User = Depends(current_user)) -> LearningPlanModule:
    minutes = body.minutes if body else 0
    return plans_engine.complete_module(db, plan_id, module_id, u.id, minutes)


@router.post("/learning-plans/{plan_id}/modules/{module_id}/skip", response_model=ModuleOut, tags=["V20.5 Learning & Resources"])
def skip_module(plan_id: int, module_id: int, db: Session = Depends(get_db), u: User = Depends(current_user)) -> LearningPlanModule:
    return plans_engine.skip_module(db, plan_id, module_id, u.id)


@router.post("/learning-plans/{plan_id}/modules/{module_id}/log-time", response_model=ModuleOut, tags=["V20.5 Learning & Resources"])
def log_module_time(plan_id: int, module_id: int, body: TimeLogIn, db: Session = Depends(get_db), u: User = Depends(current_user)) -> LearningPlanModule:
    return plans_engine.log_time(db, plan_id, module_id, u.id, body.minutes)


@router.get("/learning-plans/{plan_id}/progress", response_model=ProgressOut, tags=["V20.5 Learning & Resources"])
def plan_progress(plan_id: int, db: Session = Depends(get_db), u: User = Depends(current_user)) -> plans_engine.PlanProgress:
    return plans_engine.progress(db, plan_id, u.id)


# ---------------------------------------------------------------------------
# Admin: resource management
# ---------------------------------------------------------------------------


@router.get("/admin/resources", response_model=list[ResourceOut], tags=["V20.5 Learning & Resources Admin"], dependencies=[Depends(admin_guard)])
def admin_list_resources(skill_id: int | None = Query(default=None), limit: int = Query(default=200, ge=1, le=1000), db: Session = Depends(get_db)) -> list[LearningResource]:
    stmt = select(LearningResource)
    if skill_id:
        stmt = stmt.where(LearningResource.skill_id == skill_id)
    return list(db.scalars(stmt.order_by(LearningResource.id.desc()).limit(limit)))


@router.post("/admin/resources", response_model=ResourceOut, tags=["V20.5 Learning & Resources Admin"], dependencies=[Depends(admin_guard)])
def admin_create_resource(body: ResourceCreateIn, db: Session = Depends(get_db)) -> LearningResource:
    skill = normalization.resolve(db, body.skill_canonical_name)
    if not skill:
        raise HTTPException(404, "Skill not found in catalog — create the skill first")
    resource = LearningResource(
        skill_id=skill.id,
        title=body.title.strip(),
        provider=body.provider,
        url=body.url,
        resource_type=body.resource_type,
        difficulty=body.difficulty,
        duration_minutes=body.duration_minutes,
        language=body.language,
        is_free=body.is_free,
        rating=body.rating,
        status=body.status,
        is_verified=body.is_verified,
        objective=body.objective,
        requirements=body.requirements,
        expected_output=body.expected_output,
        evaluation_criteria=body.evaluation_criteria,
    )
    db.add(resource)
    db.commit()
    sync_learning_resource(db, resource.id)  # V21.1 Phase 3
    db.refresh(resource)
    return resource


@router.put("/admin/resources/{resource_id}", response_model=ResourceOut, tags=["V20.5 Learning & Resources Admin"], dependencies=[Depends(admin_guard)])
def admin_update_resource(resource_id: int, body: ResourceUpdateIn, db: Session = Depends(get_db)) -> LearningResource:
    resource = db.get(LearningResource, resource_id)
    if not resource:
        raise HTTPException(404, "Resource not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(resource, field, value)
    db.commit()
    sync_learning_resource(db, resource.id)  # V21.1 Phase 3
    db.refresh(resource)
    return resource


# ---------------------------------------------------------------------------
# Candidate-facing: assessments
# ---------------------------------------------------------------------------


def _question_out(q: AssessmentQuestion) -> dict:
    return {"id": q.id, "prompt": q.prompt, "options": json.loads(q.options_json), "topic": q.topic, "difficulty": q.difficulty}


@router.get("/assessments", response_model=list[AssessmentOut], tags=["V20.5 Assessments & Practice"])
def list_assessments(
    skill: str | None = Query(default=None), db: Session = Depends(get_db), _u: User = Depends(current_user)
) -> list[SkillAssessment]:
    stmt = select(SkillAssessment).where(SkillAssessment.status == "published")
    if skill:
        s = normalization.resolve(db, skill)
        if not s:
            raise HTTPException(404, "Skill not found in catalog")
        stmt = stmt.where(SkillAssessment.skill_id == s.id)
    return list(db.scalars(stmt))


@router.get("/assessments/{assessment_id}/questions", response_model=list[QuestionOut], tags=["V20.5 Assessments & Practice"])
def get_assessment_questions(assessment_id: int, db: Session = Depends(get_db), _u: User = Depends(current_user)) -> list[dict]:
    assessment = db.get(SkillAssessment, assessment_id)
    if not assessment or assessment.status != "published":
        raise HTTPException(404, "Assessment not found")
    questions = list(
        db.scalars(
            select(AssessmentQuestion)
            .where(AssessmentQuestion.assessment_id == assessment_id)
            .order_by(AssessmentQuestion.order_index)
        )
    )
    return [_question_out(q) for q in questions]


@router.post("/assessments/{assessment_id}/attempts", response_model=AttemptOut, tags=["V20.5 Assessments & Practice"])
def start_assessment_attempt(assessment_id: int, db: Session = Depends(get_db), u: User = Depends(current_user)) -> dict:
    attempt = assessments_engine.start_attempt(db, assessment_id, u.id)
    return {
        "id": attempt.id, "assessment_id": attempt.assessment_id, "status": attempt.status,
        "total_questions": attempt.total_questions, "correct_count": attempt.correct_count,
        "score_percentage": attempt.score_percentage, "weak_topics": json.loads(attempt.weak_topics_json or "[]"),
    }


@router.post("/attempts/{attempt_id}/submit", response_model=AttemptOut, tags=["V20.5 Assessments & Practice"])
def submit_assessment_attempt(attempt_id: int, body: SubmitAttemptIn, db: Session = Depends(get_db), u: User = Depends(current_user)) -> dict:
    answers = [assessments_engine.AnswerIn(question_id=a.question_id, selected_option=a.selected_option) for a in body.answers]
    attempt = assessments_engine.submit(db, attempt_id, u.id, answers)
    return {
        "id": attempt.id, "assessment_id": attempt.assessment_id, "status": attempt.status,
        "total_questions": attempt.total_questions, "correct_count": attempt.correct_count,
        "score_percentage": attempt.score_percentage, "weak_topics": json.loads(attempt.weak_topics_json or "[]"),
    }


@router.get("/attempts/{attempt_id}", response_model=AttemptOut, tags=["V20.5 Assessments & Practice"])
def get_attempt(attempt_id: int, db: Session = Depends(get_db), u: User = Depends(current_user)) -> dict:
    attempt = db.get(AssessmentAttempt, attempt_id)
    if not attempt or attempt.user_id != u.id:
        raise HTTPException(404, "Attempt not found")
    return {
        "id": attempt.id, "assessment_id": attempt.assessment_id, "status": attempt.status,
        "total_questions": attempt.total_questions, "correct_count": attempt.correct_count,
        "score_percentage": attempt.score_percentage, "weak_topics": json.loads(attempt.weak_topics_json or "[]"),
    }


# ---------------------------------------------------------------------------
# Candidate-facing: practice, projects, certifications, readiness
# ---------------------------------------------------------------------------


@router.get("/practice-recommendations", response_model=list[PracticeSuggestionOut], tags=["V20.5 Assessments & Practice"])
def get_practice_recommendations(
    target_job_id: int | None = Query(default=None), db: Session = Depends(get_db), u: User = Depends(current_user)
) -> list[dict]:
    suggestions = practice_engine.generate(db, u.id, target_job_id)
    return [
        {
            "skill": s.skill, "recommendation_type": s.recommendation_type, "reason": s.reason,
            "priority_score": s.priority_score, "project": s.project,
        }
        for s in suggestions
    ]


@router.get("/certification-guidance", tags=["V20.5 Assessments & Practice"])
def get_certification_guidance(
    target_job_id: int | None = Query(default=None), db: Session = Depends(get_db), u: User = Depends(current_user)
) -> dict:
    gap_result = gap_engine.compute(db, u.id, target_job_id)
    skill_ids = []
    for item in gap_result.priority_skills + gap_result.recommended_skills:
        s = db.scalar(select(Skill).where(Skill.canonical_name == item.canonical_name))
        if s:
            skill_ids.append(s.id)
    grouped = practice_engine.certification_guidance(db, skill_ids)
    return {
        name: [ResourceOut.model_validate(r).model_dump() for r in certs] for name, certs in grouped.items()
    }


@router.get("/career-readiness", response_model=ReadinessOut, tags=["V20.5 Career Readiness"])
def get_career_readiness(
    target_job_id: int | None = Query(default=None), db: Session = Depends(get_db), u: User = Depends(current_user)
) -> readiness_engine.ReadinessResult:
    return readiness_engine.compute(db, u.id, target_job_id)


@router.get("/career-roadmap", response_model=RoadmapOut, tags=["V20.5 Career Readiness"])
def get_career_roadmap(
    target_job_id: int | None = Query(default=None), db: Session = Depends(get_db), u: User = Depends(current_user)
) -> roadmap_engine.Roadmap:
    return roadmap_engine.build(db, u.id, target_job_id)


# ---------------------------------------------------------------------------
# Admin: assessment authoring
# ---------------------------------------------------------------------------


@router.post("/admin/assessments", response_model=AssessmentOut, tags=["V20.5 Assessments Admin"], dependencies=[Depends(admin_guard)])
def admin_create_assessment(body: AssessmentCreateIn, db: Session = Depends(get_db)) -> SkillAssessment:
    skill = normalization.resolve(db, body.skill_canonical_name)
    if not skill:
        raise HTTPException(404, "Skill not found in catalog — create the skill first")
    assessment = SkillAssessment(
        skill_id=skill.id, title=body.title.strip(), assessment_type=body.assessment_type,
        difficulty=body.difficulty, status=body.status,
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)
    return assessment


@router.post("/admin/assessments/{assessment_id}/questions", tags=["V20.5 Assessments Admin"], dependencies=[Depends(admin_guard)])
def admin_add_question(assessment_id: int, body: QuestionCreateIn, db: Session = Depends(get_db)) -> dict:
    assessment = db.get(SkillAssessment, assessment_id)
    if not assessment:
        raise HTTPException(404, "Assessment not found")
    if body.correct_option >= len(body.options):
        raise HTTPException(422, "correct_option index out of range for the given options")
    existing_count = len(list(db.scalars(select(AssessmentQuestion).where(AssessmentQuestion.assessment_id == assessment_id))))
    question = AssessmentQuestion(
        assessment_id=assessment_id, prompt=body.prompt, options_json=json.dumps(body.options),
        correct_option=body.correct_option, topic=body.topic, difficulty=body.difficulty,
        explanation=body.explanation, order_index=existing_count,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return {"id": question.id, "assessment_id": assessment_id, "topic": question.topic}
