# Recommendation Scoring â€” V21.3

## Principle

Every score is deterministic and explainable. No LLM is called to
compute a numeric relevance score, and no component score is ever a
guess â€” a component that can't be computed from real data returns
"unavailable" rather than a fabricated number (see
`app/recommendations/matching.py`'s `ComponentScore.available`).

## Components

| Component | Weight | Computed from |
|---|---|---|
| Skill match | 30% | Overlap of candidate skills (profile + resume + career-preferred) vs. job's detected skill set |
| Resume match | 15% | `app.resume_ai.job_match.match()` overall score (V20.2, reused, not reimplemented) â€” unavailable if no resume |
| Experience match | 15% | Resume experience-entry structure (reused V20.2 signal) if a resume exists; else career-preference experience level vs. job's stated requirement text; else unavailable |
| Education match | 10% | Resume education section overlap with job qualification text; else profile qualification vs. job qualification; else unavailable |
| Location match | 10% | Preferred/current location vs. job location, with a partial credit for remote jobs |
| Career goal match | 10% | Target role/industry (`CareerPreference`) vs. job title/industry |
| Work mode match | 5% | Preferred work mode vs. job's work mode |
| Recency | 5% | Days since posted, banded (â‰¤3 / â‰¤14 / â‰¤45 / older) |

Salary match and employment-type match are computed
(`matching.py`) and shown in the explanation, but are **not** part of
the weighted overall score â€” salary text is too inconsistently
formatted across sources to weight reliably; it's informational only.

## Weight redistribution rule

If a component is unavailable, its weight is not treated as zero.
Every other available component's base weight is scaled up
proportionally so the available weights still sum to 100%, and the
overall score is the weighted average of only the available
components:

```
effective_weight(c) = base_weight(c) / sum(base_weight(c') for c' in available)
overall = round(sum(score(c) * effective_weight(c) for c in available))
```

Example: a candidate with no resume and no declared career goal has
`resume`, `experience` (if also no experience-level signal), and
`career_goal` unavailable. The remaining components (skill, education,
location, work_mode, recency) are rescaled so their weights still sum
to 100%, and `ScoreResult.unavailable_components` reports exactly
which signals were missing â€” this is surfaced in the API response, not
hidden.

## Categories

Computed by `scoring.classify()` from fixed threshold constants (not
learned):

- **Best Match** â€” overall â‰¥ 85 and skill match â‰¥ 75
- **Strong Match** â€” overall â‰¥ 70 (and not Best Match)
- **Skill-Building Opportunity** â€” skill match 35â€“74, 1â€“4 missing
  skills, overall â‰¥ 45
- **Career Growth Opportunity** â€” career-goal match â‰¥ 60 and
  experience match < 55 (a stretch role that still fits the stated goal)
- **Recently Posted Match** â€” posted â‰¤ 3 days ago and overall â‰¥ 50
- **Deadline Approaching** â€” deadline within 5 days and overall â‰¥ 40
- **Potential Match** â€” fallback when none of the above apply

A job can carry multiple tags; `primary` picks the single most useful
one in the priority order listed above.

`scoring.eligibility_bucket()` separately buckets a job as "Qualified
/ Strong Match", "Skill-Building Opportunity", or "Potential Match"
purely from skill match + missing-skill count â€” this is the value
shown to satisfy the SKILL-BUILDING JOBS requirement that a candidate
is never told they're eligible/qualified when that can't be
established.

## What is intentionally not scored

Per the AI USAGE section of the spec, V20 AI infrastructure is not
wired into the scoring path at all in this release â€” explanations
(`explanations.py`) are template-composed from the same match data,
not LLM-generated. This keeps every score reproducible: the same
candidate + job state always produces the same score, verified in
`test_v21_3_ai_job_recommendation_engine.py::test_deterministic_scoring_same_input_same_score`.

