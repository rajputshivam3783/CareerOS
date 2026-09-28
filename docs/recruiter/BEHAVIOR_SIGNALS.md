# BEHAVIOR_SIGNALS.md

## What's tracked

Job Impression, Job Open, Job Save (via `SavedJob`, logged as an event
too), Job Apply (via `Application`, logged as an event too), Job
Dismiss, Not Relevant, Interested, Not Interested, Share, Filter
Usage, and a synthetic Feed View (result-count + latency, for admin
metrics only). Search itself is **not** re-logged here â€” V21.2's
`RecentSearch` already owns that, user-scoped and separately
deletable; `app.recommendations.events` never duplicates it.

## What's explicitly NOT tracked

No protected/sensitive characteristic ever enters this system â€”
`Profile`/`CareerPreference`/`Job` (the only models
`_derive_signal_keys` reads from) have no such column to begin with
(see RANKING_FAIRNESS.md). No free-text a candidate typed is ever
stored in `RecommendationEvent.filters_json` â€” only short, structured,
pre-defined keys (e.g. `{"dimension": "location"}`,
`{"result_count": 0, "latency_ms": 42}`).

## Event â†’ signal-key mapping

One event on job J updates a bounded, small set of signal keys derived
from J: `company:<organization>`, `location:<location>`,
`job_type:<job_type>`, `industry:<industry>` (if set), `skill:<skill>`
for each of J's detected skills, and up to 3 `role_keyword:<word>`
values from J's title (stopword-filtered). All keys are stored
normalized (stripped + lowercased) so a later lookup can never
silently miss on a case/whitespace difference.

## Aggregation + time decay (PERFORMANCE + DATA RETENTION)

Each signal key has exactly one row in `behavior_signal_aggregates`
per candidate, updated **in place** on every qualifying event:
`new_score = clamp(old_score * decay(elapsed) + event_weight)`. Ranking
reads this table directly â€” it never re-scans raw event history to
compute a signal, so signal lookup cost is O(number of signal keys on
the job being scored), not O(candidate's lifetime event count).

Impressions are recorded in `RecommendationEvent` (for CTR) but
deliberately **excluded** from aggregate updates â€” the highest-volume,
lowest-value event (weight 0.05) would otherwise multiply per-feed-load
writes by ~5-8x (one aggregate row per signal key, per item shown) for
the weakest signal in the system. Every deliberate, lower-volume,
higher-signal action still updates aggregates normally.

## Deduplication (EVENT PROCESSING)

- `impression`: at most once per (user, job) per rolling 24 hours
  (`impression_dedupe_hours`).
- everything else job-linked: at most once per (user, job, event_type)
  per rolling 30 seconds (`generic_event_dedupe_seconds`) â€” a
  double-click/double-submit guard, not a business rule (a real
  "dismiss twice a week apart" is two legitimate signals, correctly
  recorded as two).

Both windows are configurable via `ranking_config`.

## Data retention

Raw `RecommendationEvent` rows are eligible for deletion after
`raw_event_retention_days` (default 180) â€”
`app.recommendations.retention.purge_old_events` implements this;
**not wired into `app/scheduler.py` in this pass** (see
TEST_REPORT_V21_4.md). `BehaviorSignalAggregate` rows are never subject
to this policy â€” they're already a small, bounded summary, not raw
history, and an untouched signal already decays toward zero on its own.

Account/user deletion cascades to every table in this system via
existing `ON DELETE CASCADE` foreign keys (no separate erasure code
was needed).

## User controls over this data

- `GET/PUT /job-recommendations/personalization` â€” ON/OFF toggle, plus
  a categorized (never raw) view of current top signals.
- `POST /job-recommendations/clear-history` â€” deletes this candidate's
  `BehaviorSignalAggregate` and `RecommendationEvent` rows. Leaves
  explicit per-job `RecommendationFeedback` verdicts untouched (see
  `app.recommendations.controls`'s own docstring for why).

