# RANKING_EXPLAINABILITY.md

## Every recommendation stays explainable

`app.recommendations.explanations.explain()` remains pure template
composition over already-computed `MatchResult`/`ScoreResult` data â€”
no LLM call, no opaque model output. V21.4 adds one more input to the
same deterministic function: `match.behavior_reasons` (a list of
plain-English clauses already produced by
`app.recommendations.signals.job_affinity`, e.g. "you've engaged with
roles at Acme Corp before").

## Frontend-facing fields (Why This Job / Personalized Match / Recommended Because)

`Explanation` now carries:
- `personalized_match: bool` â€” did a learned behavior signal
  contribute to this recommendation at all?
- `personalization_reasons: list[str]` â€” up to 3 of the strongest
  behavioral clauses, already in plain English, safe to render
  directly under a "Why This Job" / "Personalized Match" heading.
- `summary` â€” the full "Recommended because ..." sentence, leading
  with behavioral reasons when present (matches the spec's own
  example: "Recommended because you frequently viewed backend roles,
  have Java/Spring Boot skills, and this job matches your preferred
  location.").

## What's never exposed (PRIVACY: "Do not expose internal sensitive signals")

- Raw event rows, timestamps, or counts.
- The numeric `BehaviorSignalAggregate.score` itself â€” only the
  resulting plain-English reason and (in `score_breakdown`) the
  already-normalized 0-100 `behavior` component score, exactly like
  every other component (skill, resume, etc).
- `personalization_reasons` is capped at 3 entries specifically so it
  can never turn into a raw signal dump.

## Negative reasons

Unchanged from V21.3's `negative_reasons` mechanism â€” missing
required skills, location mismatch, missing career-goal alignment.
V21.4 doesn't add a "why this job scored low on behavior" negative
reason, since a negative/unavailable behavior component is already
self-explanatory ("no behavioral signal for this company/location/
skill/role yet" or "personalization is off") and doesn't need its own
negative-reasons entry â€” it simply doesn't contribute positively,
exactly like a candidate with no resume gets no boost from the resume
component, without that being framed as a "negative."

## Determinism

Given a *settled* input state (no new interaction since the last
computation), scoring remains a pure function â€” same profile, same
job, same behavioral signals in, same score out, every time. Recording
a new interaction (an "open", a "dismiss", etc.) is itself new input,
and can legitimately shift a score once â€” that's the point of
personalization, not a violation of determinism. See
`test_deterministic_scoring_same_input_same_score`'s V21.4 update in
`test_v21_3_ai_job_recommendation_engine.py` for exactly this
distinction made explicit in a test.

