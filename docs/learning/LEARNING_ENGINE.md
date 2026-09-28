# Learning Engine â€” V20.5 (Phase 2)

## Structure implemented

Per the spec: **Goal â†’ Required Skills â†’ Current Level â†’ Skill Gaps â†’
Prerequisites â†’ Learning Modules**. (Practice / Assessment / Project /
Interview-Prep stages are Phase 3 â€” see the "Not yet built" note in
the repo root `CHANGELOG_V20_5.md`; they plug into the module sequence
this phase produces without changing it.)

## Path generation

`app.skill_intelligence.learning_path.build(db, user_id, target_job_id, max_priority_skills)`:

1. Calls `app.skill_intelligence.gap.compute()` (Phase 1) â€” the
   candidate's unified, ranked skill gap.
2. Takes the top `max_priority_skills` priority-gap skills (falls back
   to recommended-tier skills if there's no priority gap yet).
3. For each, walks `graph.learning_order()` â€” its full prerequisite
   chain, nearest-prerequisite-first, target skill last.
4. Deduplicates across chains: a skill that's a prerequisite for two
   different gap skills only appears once, at its first (highest
   priority) position.
5. Attaches the best verified `LearningResource` for each skill, if
   one exists (`resources.best_for_skill` â€” published + verified
   only). Skills with no verified resource yet are listed honestly in
   `unresourced_skill_names` rather than given a fabricated resource.

`GET /api/v1/learning-path/preview?target_job_id=` returns this draft
without persisting anything â€” lets a candidate see the path before
committing to a plan.

## Learning plans

`LearningPlan` + `LearningPlanModule` persist a generated path so
progress survives across sessions.

`POST /api/v1/learning-plans` builds a fresh draft via the same
`learning_path.build()` and persists it as an ordered set of modules.

### Candidate actions (all under `/api/v1`, all ownership-scoped â€”
a candidate can only see/modify their own plans)

| Action | Endpoint |
|---|---|
| Create plan | `POST /learning-plans` |
| List / get plan | `GET /learning-plans`, `GET /learning-plans/{id}` |
| Pause / resume / complete / cancel | `PUT /learning-plans/{id}/status` |
| Set target date | `PUT /learning-plans/{id}/target-date` |
| Set weekly goal | `PUT /learning-plans/{id}/weekly-goal` |
| Reorder modules | `PUT /learning-plans/{id}/modules/reorder` |
| Start / complete / skip a module | `POST /learning-plans/{id}/modules/{mid}/{start,complete,skip}` |
| Log time on a module | `POST /learning-plans/{id}/modules/{mid}/log-time` |
| Progress summary | `GET /learning-plans/{id}/progress` |

### Status machine

`active â‡„ paused`, `active â†’ completed`, `active/paused â†’ cancelled`.
Invalid transitions (e.g. `active â†’ active`) return `400`. Same
validated-transition convention as `MockInterviewSession`.

### Progress tracking

Per module: `not_started / in_progress / completed / skipped`,
`time_spent_minutes`, `started_at`, `completed_at`. Plan-level
`GET .../progress` aggregates: counts per status, completion
percentage, total time spent.

## What's intentionally not here yet (Phase 3)

- Assessments (MCQ/coding/scenario) and assessment attempts
- Practice recommendations generated from weak assessment topics
- Project recommendations
- Certification guidance
- Career readiness scoring
- Career Copilot / Interview integration surfacing this plan back
  through the copilot's own explanations
- Frontend pages

See `CHANGELOG_V20_5.md` for the phase breakdown and current status.

## Testing

`backend/tests/test_v20_5b_learning_paths.py` â€” 10 tests covering
resource visibility gating, honest unresourced-skill reporting, full
module lifecycle (start/log-time/complete/skip), plan status
transitions, reordering, ownership scoping, and regression checks on
Phase 1 + V20.3 endpoints.

