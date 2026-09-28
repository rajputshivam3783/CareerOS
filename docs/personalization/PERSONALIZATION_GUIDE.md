# Personalization â€” Guide (V21.4)

## What personalization adds on top of V21.3

Two new scoring components, `behavior` and `deadline_urgency`,
inserted into the same weighted-redistribution scoring model V21.3
already used â€” nothing about V21.3's scoring architecture changed,
only two more optional components were added to it (see
RANKING_ENGINE_V21_4.md for the full weight table).

## What's tracked

Impression, Open, Save (also recorded via the real `SavedJob` write,
never duplicated), Apply (also recorded via the real `Application`
write, never duplicated), Dismiss, Not Relevant, Interested, Not
Interested, Share, Filter Usage â€” all through one entry point,
`app.recommendations.events.record_event`. Each event updates a
small, bounded set of per-candidate signal keys derived from the job
(company/location/job_type/industry/skill/role-keyword), stored with
exponential time decay in `behavior_signal_aggregates` â€” one row per
candidate per signal key, updated in place (no raw-history rescan
needed to rank).

## What's explicitly never tracked

No protected or sensitive characteristic â€” verified structurally this
release: `CandidateFeatures` (the only object the matching/scoring
code ever reads) has no field for reservation category or PwD status,
confirmed by inspecting its dataclass fields directly in a test. No
free-text a candidate typed is ever stored in an event's filter
payload â€” only short, pre-defined structured keys.

## Personalization controls

- **New user** â€” no behavior history yet; `behavior` component is
  unavailable and its weight redistributes to the others (never scored
  as a phantom zero).
- **Disable personalization** â€” a candidate can turn the behavior
  component off entirely via preferences; verified this release that
  doing so removes it from the score breakdown, not just zeroes it
  silently.
- **Reset / delete history** â€” clears `behavior_signal_aggregates` for
  that candidate; explicit feedback (`RecommendationFeedback` â€”
  dismiss/not-relevant) is a separate, intentional record and is *not*
  cleared by a behavior-history reset (verified this release â€” the two
  are different tables with different purposes and different retention
  expectations).

## Experiments

`app.recommendations.experiments` â€” simple, deterministic variant
assignment (same candidate always gets the same variant for a given
experiment key) for measuring the effect of a ranking-config change.
Metrics tracked are volume-only in this release (impressions/opens/
saves/applies per variant) â€” no outcome-quality difference between
variants exists yet to measure, since both variants currently use the
same underlying scoring logic with different config values.

## Admin controls

Component and event weights are runtime-tunable via
`PUT /job-recommendations/admin/ranking-config/{key}` (admin-only),
stored in `RankingConfiguration`, with a reset-to-defaults endpoint.
Verified this release, as a genuine security/fairness check, not just
a feature check: injecting a bogus weight key (e.g. a fabricated
`reservation_category` entry) via this endpoint has zero effect on any
score, because scoring only ever looks up weights for the fixed set of
components `matching.py` actually computes â€” there is no way for a
config value to introduce a new scoring input.

## Known limitations

- No load/performance testing of the aggregate-update path at
  realistic scale (many events Ã— many signal keys Ã— many candidates).
- A genuine event-dedup race condition under true concurrency is
  documented, not fixed, in RECOMMENDATION_PRODUCTION_GUIDE.md.
- Signal-key vocabulary is small and fixed (company/location/job_type/
  industry/skill/role_keyword) â€” no salary-range or richer
  remote-vs-onsite affinity signal yet.

