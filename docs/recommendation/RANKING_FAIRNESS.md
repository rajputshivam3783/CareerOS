# RANKING_FAIRNESS.md

## Structural guarantee (unchanged approach from V21.3)

As documented in V21.3's own RECOMMENDATION_FAIRNESS.md, no protected
or sensitive attribute is representable in the models
`matching.compute()`/`scoring.score()` read from
(`Profile`/`CareerPreference`/`Job`) â€” there's no column for race,
religion, political affiliation, health information, sexual
orientation, or gender identity anywhere in that path. V21.4's two new
components (`behavior`, `deadline_urgency`) read from
`BehaviorSignalAggregate`/`Job.deadline` only â€” neither of which has,
or could derive, such an attribute either.

## Verification performed in this pass

```
$ grep -rn "reservation_category\|is_pwd" app/recommendations/events.py app/recommendations/signals.py app/recommendations/matching.py
(no matches)
```
(Run in this sandbox â€” genuinely executed, not inferred.)

## No proxy features

"Do not use proxy features that intentionally recreate
protected-attribute ranking" â€” the behavioral signal keys are
deliberately coarse and job-descriptive (company, location, job type,
industry, skill, a handful of title keywords), not candidate-
descriptive. None of them are a stand-in for, or correlate by
construction with, a protected characteristic; they describe the
*job*, derived identically for every candidate who interacts with it,
never anything about the candidate's identity.

Location deserves a specific note: `location` here is the **job's**
posted location (e.g. "Noida", "Remote"), the same field already used
by V21.3's `location` matching component and by V21.1/V21.2 search
filters â€” never a candidate's home address, demographic region, or any
inferred category. Using it is standard job-search personalization
("you've shown interest in Bangalore roles"), not a fairness concern.

## Diversity vs. fairness

`diversity.py`'s reordering (company/location/title/opportunity_type
caps) operates purely on *job* attributes already visible to every
candidate equally â€” it never looks at who the candidate is. It cannot
introduce a fairness issue because it has no candidate-side input at
all.

## Government recommendations

`government.py` (V21.3, untouched by V21.4) still only reads
qualification/age/category/location matches against verified
government eligibility rules â€” `reservation_category`/`is_pwd` are
read there (and only there) strictly for India's constitutionally
mandated age-relaxation estimate, never for ranking order. V21.4 adds
no new government-specific logic; `behavior`/`deadline_urgency`
components apply identically to government and private jobs.

## Known limitation

As in V21.3, no automated statistical-parity test (e.g., verifying
identical scores for two synthetic profiles differing only in a
sensitive field) exists yet. The mitigation is structural (the
attribute isn't in the scored models to begin with) rather than
measured. A natural follow-up: a regression test asserting
`matching.compute()`'s output is byte-identical for two profiles that
differ only in `reservation_category`/`is_pwd`, to catch a future
change that accidentally wires one in.

