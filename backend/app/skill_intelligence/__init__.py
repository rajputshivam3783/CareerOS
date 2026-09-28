"""V20.5 (Phase 1) — Skill Intelligence core.

    catalog.py        Curated seed data (canonical skills, aliases,
                       relationship graph) + idempotent DB seeding.
                       Deliberately overlaps with app.services.career.SKILLS
                       (V6/V8) rather than forking a second vocabulary.
    normalization.py   Alias -> canonical Skill resolution. Never invents
                       a Skill for unrecognized input — see AI_SAFETY.md.
    graph.py           Skill graph traversal: prerequisites, related,
                       advanced_version, alternative, complementary.
    gap.py             Unified skill-gap view. Composes — never
                       duplicates — app.resume_ai.skill_gap (V20.2),
                       CareerPreference (V20.3), and
                       MockInterviewReport.technical_gaps_json (V20.4).
    resources.py       Read-only lookups over admin-curated
                       LearningResource rows — never generates or
                       invents a resource.
    learning_path.py   Builds an ordered, resourced skill sequence from
                       gap.py + graph.py (Phase 2).
    plans.py           LearningPlan/LearningPlanModule lifecycle:
                       create from a draft path, pause/resume,
                       complete/skip/reorder modules, progress summary
                       (Phase 2).
    assessments.py     Admin-authored MCQ assessments; server-side
                       scoring; weak-topic aggregation (Phase 3).
    practice.py        Practice/project/certification-category
                       recommendations derived from weak areas — never
                       fabricated (Phase 3).
    readiness.py       Explainable Role/Technical/Interview/Skill-
                       Coverage/Learning-Progress readiness scores,
                       computed on demand, never a black box (Phase 3).
    roadmap.py         Full spec-structure career roadmap (Goal →
                       Required Skills → ... → Target Role) — a
                       presentation composition over the modules
                       above, not a new engine (Phase 4).

Nothing in this package calls an AI provider directly; skill matching
and gap composition here are deterministic (string/graph lookups), same
posture as app.resume_ai.skill_gap and app.services.career before it.
"""
