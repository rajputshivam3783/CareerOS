# Recommendation Fairness â€” V21.3

## What is never used for ranking

`Profile.reservation_category` and `Profile.is_pwd` â€” the two
protected-characteristic-adjacent fields that exist in this codebase
(added in V5 solely for Government age-relaxation eligibility
calculations) â€” are **deliberately never read** into
`CandidateFeatures` (`app/recommendations/candidate_features.py`).
They are not part of the candidate feature set the matching/scoring
engine sees at all, so they cannot influence a score, a category tag,
or ranking order, structurally rather than by convention.

This codebase does not collect religion, race, political affiliation,
health information, or sexual orientation anywhere, so there was
nothing further to exclude for those attributes.

## Where reservation_category / is_pwd *are* legitimately used

Only in `app/recommendations/government.py::assess`, which calls the
existing, unmodified V5 `app.services.eligibility.eligibility()` to
produce an **eligibility verdict for display** on a Government
posting (e.g. an age-relaxation calculation this candidate is entitled
to under the recruitment's own published rules). This is shown to the
candidate as information about *that job's* rules, not used to boost
or suppress the job's rank, and not used for any other job's score.
Government job ranking uses the exact same skill/experience/education/
location/career-goal/recency components as every other job type.

## Wording discipline

`government.py` enforces one rule in one place: never say "You are
eligible" unless `eligibility()` returns `eligible is True` with a
real profile on file. Everything else (no profile, `eligible is None`,
a partial match) is worded "Potentially relevant" or "Not clearly
eligible" â€” see RECOMMENDATION_ARCHITECTURE.md and the GOVERNMENT
RECOMMENDATIONS section of the spec. This prevents a fairness failure
mode where an under-specified profile silently defaults to an
optimistic claim.

## Diversity vs. fairness

`app/recommendations/diversity.py`'s company/location/title spreading
(RECOMMENDATION_RANKING.md) is a *relevance* diversity mechanism, not
a fairness mechanism â€” it has no knowledge of or interaction with any
candidate or employer protected characteristic. It exists purely so
one company posting 20 similar roles doesn't crowd out every other
result.

## Testing performed

`test_government_job_without_profile_says_potentially_relevant_not_eligible`
confirms the wording rule holds when eligibility can't be established.
No dedicated statistical fairness audit (e.g. disparate-impact testing
across candidate demographic groups) was run â€” this codebase has no
demographic data on candidates beyond the two Government-eligibility
fields addressed above, so there is no protected-attribute data
available to audit against in the first place. NOT VERIFIED beyond
what's listed above.

