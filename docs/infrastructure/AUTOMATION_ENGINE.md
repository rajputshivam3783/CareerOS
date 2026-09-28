# AUTOMATION_ENGINE.md â€” V19.4

## What this is

`app/services/automation.py` â€” decides *who* gets notified about a
recruitment-lifecycle event and *why*, then hands off to the channel
abstraction in `NOTIFICATION_ENGINE.md` to actually deliver it.

## Subscriptions

`Subscription(user_id, subscription_type, value, job_id, enabled)`.
`subscription_type` is one of:

```
recruitment | organization | exam | category | qualification | state
| central | psu | bank | railway | police | teaching | medical | engineering | defence
```

`recruitment` matches by `job_id` directly. The value-based types match
a case-insensitive substring of `value` against the relevant `Job`
column (`organization`, `title`, `category`, `qualification`,
`location`). The flat govt-level/category types (`central`, `psu`,
`bank`, ...) match `Job.category`/`Job.govt_level` against the same
vocabulary `app.api.platform`'s FILTERS section already uses â€” see
`_CATEGORY_SUBSCRIPTION_VALUES` in `automation.py`.

Managed via `POST/GET/DELETE /subscriptions`
(`frontend/src/app/subscriptions`).

## What triggers a notification

Three independent scans, each with its own cursor
(`AutomationCursor` â€” a `(trigger, last_id)` high-water mark, so a
scan never re-notifies for a row it already processed):

**1. `recruitment_published`** â€” every newly-published Government
`Job`. Recipients: anyone who saved/applied to it (`recruitment_published`
template) **or** anyone whose subscription matches it (`subscription_match`
template) â€” a user can be in both sets; each gets one notification per
template that applies.

**2. Lifecycle updates** â€” every new `RecruitmentUpdate` row (admit
card released, result declared, cutoff published, ...). Mapped to a
template key via `_UPDATE_TYPE_TEMPLATE_KEY`:

| `update_type` | Template key |
|---|---|
| `result` | `result` |
| `admit_card` | `admit_card` |
| `answer_key` | `answer_key` |
| `exam_date` | `exam_date` |
| `cutoff` | `cutoff` |
| `merit_list` | `merit_list` |
| `dv` | `document_verification` |
| `joining` | `joining` |
| `medical` | `medical_examination` |
| `cancelled` | `recruitment_cancelled` |
| `application_open` | `application_open` |
| `correction_window` | `correction_window` |
| `city_intimation` | `city_intimation` |
| `objection_window` | `objection_window` |
| `final_answer_key` | `final_answer_key` |
| `score_card` | `score_card` |
| everything else (`admission`, `syllabus`, `counselling`, `application_closed`, `final_selection`, `completed`, `notice`, `notification`) | `new_notification` (generic fallback â€” nothing is silently dropped) |

Recipients: saved/applied users + subscribers to that job/organization/category.

**3. `deadline_extended`** â€” reuses the existing `AuditLog` rows
`app/api/admin.py`'s `update_job_lifecycle` already writes on every
admin edit (unmodified â€” Government Core wasn't touched to add this).
Any such row whose `detail` mentions `'deadline'`, on a still-published
job, notifies that job's interested users.

> **Known limitation, stated plainly:** the audit log records the
> *new* value, not the old one, so this fires on **any** post-publish
> deadline edit â€” it cannot currently distinguish an extension from a
> shortening. A true distinction would require storing the previous
> deadline, which is out of scope for V19.4 (see `RELEASE_NOTES_V19_4.md`).

## Manual run / scheduling

`POST /admin/automation/run` (admin) runs `run_automation_scan` +
`sync_auto_reminders` + `fire_due_reminders` synchronously and returns
counts. `POST /admin/automation/run/{job_id}` runs one specific
scheduled job by id (`careeros_automation`, `careeros_reminder_sync`,
`careeros_notifications`, `careeros_ingestion`). See `app/scheduler.py`
for the interval-based scheduling (default: automation scan hourly,
reminder sync daily) â€” extended additively; the pre-existing V2
ingestion job and V7 notification scan are untouched.

## Automation logs

Every scan writes one `AutomationLog` row per triggering `Job`
(`trigger`, `job_id`, `notifications_created`, `detail`). Distinct from
the V9 `AuditLog`: `AuditLog` is "who did what administrative action";
`AutomationLog` is "what did the automation engine itself do." Viewed
via `GET /admin/automation/logs` or the Admin console's "Automation
logs" tab.

