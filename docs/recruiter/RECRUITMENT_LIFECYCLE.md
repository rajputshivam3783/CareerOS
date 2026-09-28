# RECRUITMENT_LIFECYCLE â€” V19.1

Every government recruitment's lifecycle is tracked as a series of
`RecruitmentUpdate` rows (table `recruitment_updates`), each attached
to a `Job` via `job_id` and typed via `update_type`. This table
already existed (V14, extended V16); V19.1 only extends the
*vocabulary* of `update_type` values it accepts â€” no schema change.

## Full lifecycle vocabulary (`RECRUITMENT_UPDATE_TYPES` in `app/core/constants.py`)

| Stage (spec name) | `update_type` value | Introduced |
|---|---|---|
| Notification | `notification` | V19.1 |
| Application Start | `application_open` | V19.1 |
| Application End | `application_closed` | V19.1 |
| Correction Window | `correction_window` | V19.1 |
| Exam Date | *(`Job.exam_date` column, not an update)* | V1 |
| City Intimation | `city_intimation` | V19.1 |
| Admit Card | `admit_card` | V14 |
| Answer Key | `answer_key` | V14 |
| Objection Window | `objection_window` | V19.1 |
| Final Answer Key | `final_answer_key` | V19.1 |
| Result | `result` | V14 |
| Score Card | `score_card` | V19.1 |
| Cutoff | `cutoff` | V16 |
| Merit List | `merit_list` | V16 |
| DV (Document Verification) | `dv` | V16 |
| Medical | `medical` | V19.1 |
| Final Selection | `final_selection` | V19.1 |
| Joining | `joining` | V16 |
| Completed | `completed` | V19.1 |
| Cancelled | `cancelled` | V19.1 |

Also present, not part of the linear lifecycle above but validated
through the same set: `admission`, `syllabus`, `exam_date` (an update
variant, distinct from the `Job.exam_date` column), `notice`,
`counselling`.

## Why "Exam Date" isn't a lifecycle event

`Job.exam_date` has been a first-class column on `Job` since V1 (it's
a known, usually-single date rather than a moving target announced
later, unlike admit cards/results/etc., which are genuinely added
after the fact). V19.1 leaves this as-is rather than migrating it into
`RecruitmentUpdate`, to avoid a breaking change to every existing
caller of `Job.exam_date`. An `exam_date` *update type* still exists
in the vocabulary (pre-dates V19.1) for cases where an exam date is
revised/announced after initial notification and that revision itself
needs to show up in the timeline feed.

## How a stage gets recorded

Unchanged from V14/V16: `POST /admin/jobs/{job_id}/updates` (admin/
X-Admin-Key protected, `app/api/admin.py`), body
`{"update_type": "...", "title": "...", "event_date": "...", "source_url": "..."}`.
`update_type` is validated against `RECRUITMENT_UPDATE_TYPES` â€” an
unrecognized value is rejected with `400`, exercised by
`test_v16c_government_hub.py::test_unknown_lifecycle_stage_is_rejected`
and, for the twelve new V19.1 values specifically, by
`test_v19_1_government_core.py::test_new_v19_1_lifecycle_stages_are_accepted`.

## How a stage is read back

Unchanged: `GET /jobs/{id}/timeline` returns every published update
for a job ordered by `event_date`; `GET /government/sections/{section}`
returns a cross-recruitment feed for one stage (e.g.
`/government/sections/document-verification` â†’ `dv`). The V19.1 stages
are reachable the same way once a section slug is added for them in
`_GOVT_SECTIONS` (`app/api/platform.py`) â€” left as a follow-up, since
adding new public section slugs/URLs is a product decision (naming,
SEO, nav placement) rather than a backend requirement of this pass;
the data is fully queryable today via the `update_type` filter even
without a dedicated section slug.

## Cancellation

`cancelled` is new in V19.1 and is recorded the same way as any other
stage (a `RecruitmentUpdate` row) rather than a `Job.status` value â€”
a cancelled recruitment typically stays `published` (visibly retired,
with the cancellation notice) rather than reverting to `review` or
`archived`, matching how source sites present it.

