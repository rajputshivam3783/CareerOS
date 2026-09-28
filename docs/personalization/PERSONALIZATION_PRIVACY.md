# PERSONALIZATION_PRIVACY.md

## Users can understand what's being used

`GET /job-recommendations/personalization` tells a candidate, in plain
categorized language, what's currently influencing their feed â€” e.g.
"Companies you've engaged with: acme corp" â€” and whether
personalization is on at all. This satisfies "Users must be able to
understand that recommendations use their CareerOS activity" directly,
without ever dumping a raw event log at them (see next section).

## What's never exposed

- **Raw behavioral history.** No endpoint returns individual
  `RecommendationEvent` rows, timestamps, or per-event weights to a
  candidate. The personalization summary endpoint returns only
  categorized top signal *keys* (already capped to the top 3 per
  category via `BehaviorSignals.top_positive`), never counts, scores,
  or event-level detail.
- **Another candidate's data, ever.** Every candidate-facing endpoint
  in `app/api/recommendations.py` resolves its subject exclusively from
  `current_user` (the JWT) â€” none accepts a user id parameter. Traced
  endpoint-by-endpoint:

| Endpoint | Scoping |
|---|---|
| `GET/PUT /job-recommendations/personalization` | `signals.build(db, u.id)` / `preferences.update(db, u.id, ...)` |
| `POST /job-recommendations/reset` | `preferences.reset_to_defaults(db, u.id)` |
| `POST /job-recommendations/clear-history` | `controls.clear_behavior_history(db, u.id)` |
| `POST /job-recommendations/events`, `.../\{job_id\}/event`, `.../\{job_id\}/feedback` | `events_service.record_event(..., user_id=u.id, ...)` |
| `GET /job-recommendations`, `.../\{job_id\}/explanation` | `candidate_features.build(db, user.id)` |

- **Individual behavioral profiles to admins.** `GET
  /job-recommendations/analytics` and `GET
  /job-recommendations/admin/ranking-config` return only aggregate
  counts/rates and global configuration â€” never a per-candidate
  breakdown, never raw event rows tied to a name/email. The
  experiment-variant breakdown is grouped by variant, not by user.

## No selling or sharing behavioral profiles

Nothing in this codebase exports, syncs, or exposes
`BehaviorSignalAggregate`/`RecommendationEvent` data to any external
system, third party, or unrelated internal feature â€” these tables are
read only by `app.recommendations.*` and by the candidate's own
personalization-summary endpoint. There is no data-export, webhook, or
integration hook touching these tables anywhere in this change.

## Data minimization

- `filters_json` never stores free text â€” only a fixed, small set of
  structured keys the code itself controls (`dimension`,
  `result_count`, `latency_ms`). A candidate's search query text is
  never duplicated here â€” it already lives in V21.2's own
  `RecentSearch`, which has its own, separate deletion path.
- Signal keys are a small, fixed taxonomy (company/location/job_type/
  industry/skill/role_keyword) â€” never an arbitrary free-form key a
  candidate could inject content into.

## Retention and deletion

See BEHAVIOR_SIGNALS.md's own Retention section. Summary: raw events
are retention-bounded (`raw_event_retention_days`, default 180) and
purgeable; account deletion cascades through every table here via
existing foreign-key `ON DELETE CASCADE`; a candidate can self-service
delete their own learned profile via `POST
/job-recommendations/clear-history` at any time, without waiting on
support or admin action.

## IDOR / authorization testing performed in this pass

See `test_v21_4_advanced_personalization.py`'s privacy-tagged tests:
`test_personalization_and_history_are_scoped_to_own_user`,
`test_ranking_config_requires_admin`,
`test_experiments_are_admin_only_and_dormant_by_default`. **Written
and manually traced, execution NOT VERIFIED in this sandbox** â€” see
TEST_REPORT_V21_4.md.

