# Recommendation Privacy & Security â€” V21.3

## Authorization

Every `/job-recommendations/*` endpoint (`app/api/recommendations.py`)
operates on the calling user's own data only, via FastAPI's
`current_user` dependency â€” no endpoint accepts another user's id as a
parameter. There is no "view another candidate's recommendations"
capability anywhere in this release.

- `GET /job-recommendations` â€” the caller's own feed only.
- `GET /job-recommendations/{job_id}/explanation` â€” scores fresh
  against the caller's own candidate features; a job the caller isn't
  authorized to see (unpublished/closed/expired/private) returns 404,
  not the underlying job data.
- `POST /job-recommendations/{job_id}/feedback` and `.../event` â€”
  write to a row keyed by `(current_user.id, job_id)`; one user's
  feedback/dismiss list never affects another user's results
  (verified in `test_feedback_is_scoped_to_own_user_not_shared`).
- `PUT /job-recommendations/preferences` â€” updates only the caller's
  own `RecommendationPreference` row.
- `GET /job-recommendations/analytics` â€” **admin-only**
  (`Depends(admin_guard)`, the same guard used by `app.api.admin`) and
  returns aggregate counts by event type + CTR/conversion rate only â€”
  never a per-user breakdown, never any recommendation content.

## Data used vs. data never used

Only data the codebase already treats as this candidate's authorized
data is read: their own `Profile`, `CareerPreference`, `Resume`,
`SavedJob`/`Application` rows, and their own `RecommendationFeedback`/
`RecommendationPreference`. Retrieval (Stage 1) goes through
`app.search.service.run_search` with a real `SearchActor` built from
the requesting user, so the same visibility rules V21.1 search already
enforces apply here too â€” a candidate's recommendations can never
include a private/draft/review job or one owned by a different
recruiter than the one who published it.

**Recruiter/other-candidate data is never read.** Nothing in
`app/recommendations/` queries another user's `SavedJob`,
`Application`, `Resume`, or feedback rows. `cold_start.py`'s
popular-jobs signal aggregates save/application *counts* across all
users (an aggregate, not attributed to any individual), the same
privacy posture as any "X people saved this" feature.

## What `RecommendationEvent` stores (and doesn't)

The analytics event log (`RecommendationEvent`) stores exactly
`user_id`, `job_id`, `event_type`, `created_at` â€” no resume text, no
score, no explanation payload, no free-text field of any kind. It is
never read as a source of truth for "is this saved/applied" (that
stays `SavedJob`/`Application`) and is only aggregated, never joined
back to per-user content, by the admin analytics endpoint.

## IDOR / access-control testing performed

`test_v21_3_ai_job_recommendation_engine.py` includes:
`test_recommendations_require_auth` (no token â†’ 401/403),
`test_feedback_is_scoped_to_own_user_not_shared` (two real users,
confirms A's dismiss doesn't affect B's feed), `test_analytics_requires_admin`
(non-admin â†’ 401/403, admin key â†’ 200), and
`test_explanation_for_unpublished_job_not_found` (an unpublished job's
id, requested by a candidate, returns 404 rather than leaking its
existence/content).

No dedicated penetration test or automated IDOR fuzzing tool was run
against this release â€” the above are the specific access-control paths
this feature introduces, exercised with real requests, not a
comprehensive security audit. NOT VERIFIED beyond what's listed above.

