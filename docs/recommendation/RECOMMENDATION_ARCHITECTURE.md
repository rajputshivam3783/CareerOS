# Recommendation Architecture â€” V21.3 AI Job Recommendation Engine

## Pipeline

```
Candidate Data
      |
      v
Candidate Feature Builder   (app/recommendations/candidate_features.py)
      |
      v
Job Feature Builder         (app/recommendations/job_features.py)
      |
      v
Candidate-Job Matching      (app/recommendations/matching.py)
      |
      v
Recommendation Scoring      (app/recommendations/scoring.py)
      |
      v
Ranking + Diversity/Dedupe  (app/recommendations/diversity.py)
      |
      v
Explainable Recommendations (app/recommendations/explanations.py)
```

`app/recommendations/service.py` is the single orchestrator
(`get_recommendations`, `get_single_recommendation`) â€” every API
endpoint and any future consumer goes through it, the same role
`app.search.service.run_search` plays for V21.1. No recommendation
logic lives in a frontend component.

## Two-stage retrieval + ranking

**Stage 1 â€” retrieval** (`app/recommendations/retrieval.py`): narrows
the full job set to a bounded, permission-checked candidate pool
(â‰¤150, widened once if a location filter over-narrows it) by calling
`app.search.service.run_search` with a real `SearchActor` built from
the requesting user and a query built from the candidate's actual
target role/skills â€” never a fabricated query. This is also where
Government/Private/Internship/Apprenticeship inclusion (per
`RecommendationPreference`) is applied, via the search entity-type
filter. `log_analytics=False` is passed so retrieval never pollutes
the candidate's Recent Searches or search analytics â€” this
isn't a query they typed.

**Stage 2 â€” ranking**: every job in the Stage-1 pool gets full
candidate-job matching, scoring, categorization, and an explanation
(Â§ below), then the whole set is sorted by score, deduplicated by
`Job.id`, and diversity-adjusted (`app/recommendations/diversity.py`)
before the requested page size is returned.

## What's reused vs. new

| Layer | Reused from | Not duplicated |
|---|---|---|
| Candidate retrieval | V21.1 `app.search.service.run_search` / V21.2 filters | No second job index or query engine |
| Resume-vs-job scoring component | V20.2 `app.resume_ai.job_match.match` | No second resume-matching engine |
| Skill gap / normalization | V20.5 `app.skill_intelligence.gap.compute` + `normalization.py` | No second skill catalog or normalizer |
| Government eligibility verdict | V5 `app.services.eligibility.eligibility` | No second eligibility ruleset |
| Career goal / preference signals | V20.3 `CareerPreference` (read-only) | `RecommendationPreference` only adds fields CareerPreference doesn't have |
| Saved/applied state | `SavedJob` / `Application` (V1/V6) | No duplicate application storage |

New code is limited to: 4 tables (`RecommendationPreference`,
`RecommendationFeedback`, `RecommendationSnapshot`,
`RecommendationEvent`), the `app/recommendations/` package, and
`app/api/recommendations.py`.

## Candidate Features

Built once per request by `candidate_features.build(db, user_id)` from
`Profile`, `CareerPreference`, `Resume`/`ResumeAnalysis`, the unified
skill-gap engine (which surfaces interview weaknesses too â€” see
below), resume project entries, `LearningPlan`/`LearningPlanModule` progress, `SavedJob`/`Application`, `RecommendationFeedback`
(exclusion list), `RecommendationPreference`, and V21.2 `RecentSearch`
(best-effort). Every optional source is wrapped so its absence
degrades gracefully (`CandidateFeatures.has_resume` /
`has_career_goal` / `is_cold_start`) rather than raising.

- **Interview weaknesses**: the unified skill-gap engine
  (`app.skill_intelligence.gap.compute`) already merges V20.4 mock-
  interview `technical_gaps`/`recommended_topics` into each priority
  skill's `source_signals`. `candidate_features.py` pulls out just the
  ones flagged `weak_interview_performance` /
  `recommended_by_interview_report` into
  `interview_weak_topics` â€” `matching.py` then calls this out
  specifically (not just as a generic missing skill) when it overlaps
  a job's required skills.
- **Learning progress**: a direct query joins
  `LearningPlanModule` â†’ `Skill`, scoped to the candidate's own
  `LearningPlan` rows, into `learning_completed_skills` /
  `learning_in_progress_skills`. A completed module counts that skill
  as matched even if the resume/profile skills list hasn't been
  updated yet (`matching._skill_match`); an in-progress one stays
  "missing" but is called out separately
  (`missing_skills_in_progress`) rather than treated identically to an
  untouched gap.
- **Projects**: resume `project_entries` (V20.2's
  `NormalizedProfile.project_entries`) are read into
  `CandidateFeatures.project_entries` and used by
  `matching._experience_match` as a capped, honestly-labelled partial
  signal when there's no formal work-experience section â€” never
  scored the same as genuine work experience.

`Profile.reservation_category` and `Profile.is_pwd` are **not** read
into `CandidateFeatures` â€” see RECOMMENDATION_FAIRNESS.md.

## Job Features

Built by `job_features.build(job)` from the one `Job` table (JOB /
GOVERNMENT_RECRUITMENT / INTERNSHIP / APPRENTICESHIP are the same
table, distinguished by `job_type`, exactly as V21.1 search already
treats them). Skill detection uses the shared `SKILLS` vocabulary over
`job_text()` â€” the same mechanism `app.services.career` and
`app.resume_ai.job_match` already use â€” optionally layered with
`Job.skills` when a recruiter has entered it (parsed defensively for
both the JSON-list shape the recruiter wizard writes and the
comma-separated shape used elsewhere; see the docstring in
`job_features.py` for why this had to be defensive rather than assumed).

## Excluded jobs

Applied at two points, defensively: Stage-1 retrieval only returns
jobs visible to the actor (RBAC, same as search) and excludes expired
(`deadline < today` â€” confirmed this is **not** automatically reflected
in `Job.status` anywhere in the codebase, so it's checked explicitly)
and closed/archived/unpublished jobs; Stage-2 ranking re-checks the
same conditions plus the candidate's own dismiss/not-relevant list
before scoring, in case a job is looked up directly by id (e.g. the
explanation endpoint).

## Refresh / caching

See `app/recommendations/cache.py`. A `RecommendationSnapshot` is kept
per user, keyed by an `input_signature` hash of exactly the signals
that could change the result (resume upload time, career-preference
update time, recommendation-preferences update time, saved/applied/
feedback counts, and the newest `updated_at` across published jobs).
A request reuses the snapshot when the signature still matches and it
hasn't passed its 6-hour TTL; otherwise, or on an explicit
`POST /job-recommendations/refresh`, the full pipeline reruns and the
snapshot is overwritten. This achieves the REFRESH requirement without
adding a write-path hook into resume upload, career preferences, job
posting, or application endpoints.

## Cold start

A candidate with no resume, no career goal, and no profile skills
(`CandidateFeatures.is_cold_start`) still gets a real response: Stage-1
retrieval's blank-query path sorts by recency instead of a relevance
score with nothing to score against, and `cold_start.py` adds a
popular-verified-jobs pool ranked by real save/application counts
(never a fabricated popularity number). The response is honestly
labelled (`is_cold_start: true`) and the frontend shows a notice
explaining why the list is broad rather than personalized.

