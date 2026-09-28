# Skill Intelligence â€” V20.5

## What this is

A single canonical Skill model shared by the entire CareerOS platform.
Every skill a candidate's resume, a job listing, a career goal, or an
interview report ever mentions is normalized against one catalog
instead of being matched ad hoc in each feature area.

This is **additive** on top of V20.4. It does not replace:
- `app.resume_ai.skill_gap` â€” resume-vs-job matching keeps
  working exactly as before.
- `CareerPreference` â€” career goals are unchanged.
- `MockInterviewReport.technical_gaps_json` â€” interview
  scoring is unchanged.

`app.skill_intelligence.gap` **composes** these three, it doesn't fork
a second gap engine.

## Data model

| Table | Purpose |
|---|---|
| `skills` | Canonical skill: name, category, subcategory, difficulty |
| `skill_aliases` | Alternate spellings â†’ one canonical skill (`js` â†’ `javascript`) |
| `skill_relationships` | Directed graph edges: prerequisite / related / advanced_version / alternative / complementary |

Migration: `backend/migrations/v20_5_ai_learning_skill_intelligence.sql`
(additive-only, safe against an existing Postgres database; SQLite
picks these up automatically via `Base.metadata.create_all()`).

## Normalization

`app.skill_intelligence.normalization.resolve()` / `resolve_many()` â€”
exact, case-insensitive match against `canonical_name` and `alias`.
No fuzzy matching, no AI call. A name with no catalog match is
returned as **unrecognized**, never silently created as a new skill.
Only an admin (or the seed catalog) adds new canonical skills â€” see
`AI_SAFETY.md`.

## Seeding

`app.skill_intelligence.catalog.seed_skills()` is idempotent and runs
automatically on every app startup (`app/main.py` lifespan, same
pattern as the notification-template and prompt seeders). It never
overwrites a row an admin has since edited by hand â€” it only inserts
what's missing.

The seed catalog covers every category/subcategory the spec requires
(programming languages, frameworks, databases, cloud, DevOps, data
science, ML, AI, cybersecurity, tools; communication, leadership,
problem-solving) and includes the exact worked example from the spec:
Python â†’ NumPy â†’ Pandas â†’ Machine Learning â†’ Deep Learning.

## API (all under `/api/v1`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/skills` | any user | browse/search the catalog |
| GET | `/skills/{name}/graph` | any user | prerequisites/related/etc. for one skill |
| GET | `/skill-intelligence/gap` | any user (own data only) | unified skill gap |
| GET | `/admin/skills` | admin | list all skills |
| POST | `/admin/skills` | admin | add a canonical skill (+ optional aliases) |
| POST | `/admin/skills/{id}/aliases` | admin | add an alias |
| POST | `/admin/skills/{id}/relationships` | admin | add a graph edge |
| POST | `/admin/skills/seed` | admin | re-run the idempotent seeder |

## Unified skill gap

`app.skill_intelligence.gap.compute(db, user_id, target_job_id)`
returns:

- `matched_skills` â€” resume skills the target job also wants
- `priority_skills` / `recommended_skills` â€” normalized, deduplicated,
  ranked by a fixed, inspectable formula (never an AI-generated
  ranking) over: missing-from-target-job, interview weakness, and
  stated career goal
- `unrecognized_inputs` â€” free-text skills that didn't resolve to the
  catalog (surfaced, not dropped or invented)
- `signals_used` / `signals_unavailable` â€” which of resume, target
  job, career goal, and interview history actually contributed;
  explicitly named rather than silently omitted when unavailable
  (e.g. no resume uploaded yet, no target job selected)

Every `SkillGapItem` carries a plain-English `reason` and the list of
`source_signals` that produced it â€” no black-box scoring.

## Testing

`backend/tests/test_v20_5_skill_intelligence.py` â€” 13 tests: idempotent
seeding, alias dedup, graph traversal against the spec's own worked
example, unified gap composition across all three source signals,
admin-gating, and regression checks on the V20.2/V20.3 endpoints this
touches.

