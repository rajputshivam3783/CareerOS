# CareerOS ATS API Reference

Base path: `/api/v1`. All endpoints below require
`Authorization: Bearer <access_token>` for a user with `role=recruiter`
(`recruiter_status=approved`) unless marked **Public**. This is a
hand-written companion to the live OpenAPI schema served by FastAPI at
`/docs` and `/openapi.json` â€” treat that as the source of truth for exact
request/response shapes; this file is for orientation.

## Company

| Method | Path | Notes |
|---|---|---|
| GET | `/recruiter/company` | 404 if you haven't created one yet |
| PUT | `/recruiter/company` | Upsert â€” creates on first call, updates after |
| GET | `/recruiter/company/branches` | |
| POST | `/recruiter/company/branches` | |
| DELETE | `/recruiter/company/branches/{branch_id}` | |
| GET | `/recruiter/company/team` | Owner or roster member |
| POST | `/recruiter/company/team/invite` | Owner only. `{ "email": "..." }` â€” the account must already be an approved recruiter |
| DELETE | `/recruiter/company/team/{member_id}` | Owner only. Can't remove the owner row |
| GET | `/companies` | **Public.** `?q=&limit=&offset=` |
| GET | `/companies/{slug}` | **Public.** Returns `{ company, branches }` |

## Email templates

Owner-only, same pattern as Company above.

| Method | Path | Notes |
|---|---|---|
| GET | `/recruiter/company/email-templates` | Lists all 5 types, seeding any not yet customized |
| GET | `/recruiter/company/email-templates/{type}` | `type` âˆˆ `application_received, interview_invitation, interview_reminder, offer, rejection` |
| PUT | `/recruiter/company/email-templates/{type}` | Body: `{ "subject": "...", "body": "..." }` |
| POST | `/recruiter/company/email-templates/{type}/reset` | Reverts to built-in default text |
| POST | `/recruiter/company/email-templates/{type}/preview` | Body: `{ "subject", "body", "values"? }`. Renders `{{placeholder}}` tokens against sample data (or your overrides) without saving. Response: `{ subject, body, values_used }` |
| GET | `/recruiter/company/email-templates-meta/variables` | Returns `{ variables: [...], sample_values: {...} }` for building an editor UI |

Response shape for a template (list/get/put/reset):
```json
{
  "id": 1,
  "template_type": "offer",
  "label": "Offer",
  "subject": "Offer from {{company_name}} â€” {{job_title}}",
  "body": "Hi {{candidate_name}}, ...",
  "is_custom": false,
  "updated_at": "2026-08-06T12:00:00"
}
```

## Jobs

Team-shared as of V18.6: any endpoint below scoped to "your jobs" actually
means "jobs owned by anyone on your company team" â€” see
`app.core.team_access.team_owner_ids`. A solo recruiter with no company
sees only their own jobs, same as before.

| Method | Path | Notes |
|---|---|---|
| POST | `/recruiter/jobs` | Create (starts in `draft`) |
| GET | `/recruiter/jobs` | List your jobs |
| GET | `/recruiter/jobs/{job_id}` | |
| PUT | `/recruiter/jobs/{job_id}` | Edit |
| DELETE | `/recruiter/jobs/{job_id}` | |
| POST | `/recruiter/jobs/{job_id}/submit-for-review` | draft â†’ review |
| POST | `/recruiter/jobs/{job_id}/close` | |
| POST | `/recruiter/jobs/{job_id}/reopen` | |
| POST | `/recruiter/jobs/{job_id}/archive` | |
| POST | `/recruiter/jobs/{job_id}/clone` | Returns a new draft copy |
| GET | `/recruiter/jobs/{job_id}/pipeline` | Kanban-shaped applicant list by stage |

## Applicants

| Method | Path | Notes |
|---|---|---|
| GET | `/recruiter/jobs/{job_id}/applicants` | |
| GET | `/recruiter/jobs/{job_id}/applicants/export` | CSV download |
| GET | `/recruiter/jobs/{job_id}/applicants/export.xlsx` | Excel (.xlsx) download, same columns as CSV |
| GET | `/recruiter/applicants/{applicant_id}` | Full candidate profile |
| PATCH | `/recruiter/applicants/{applicant_id}/stage` | Move pipeline stage |
| PATCH | `/recruiter/applicants/{applicant_id}` | General status/field update |
| POST | `/recruiter/applicants/{applicant_id}/notes` | Private recruiter note |
| GET | `/recruiter/applicants/{applicant_id}/notes` | |

## Interviews

| Method | Path | Notes |
|---|---|---|
| POST | `/recruiter/applicants/{applicant_id}/interviews` | |
| GET | `/recruiter/applicants/{applicant_id}/interviews` | |
| PATCH | `/recruiter/interviews/{interview_id}` | Update time/status/etc. |

## Offers

| Method | Path | Notes |
|---|---|---|
| POST | `/recruiter/applicants/{applicant_id}/offer` | Create (draft) |
| GET | `/recruiter/applicants/{applicant_id}/offer` | |
| POST | `/recruiter/applicants/{applicant_id}/offer/send` | draft â†’ sent |
| POST | `/recruiter/applicants/{applicant_id}/offer/withdraw` | |

## Dashboard & analytics

| Method | Path | Notes |
|---|---|---|
| GET | `/recruiter/dashboard` | Summary counts (jobs posted/published, applicants) |
| GET | `/recruiter/analytics` | Jobs, applicants, conversion, time-to-hire, pipeline, offer acceptance |

## Errors

Standard FastAPI/HTTPException shape: `{"detail": "..."}` (or a list of
validation errors for 422s). Common codes across the ATS: `403` (not the
resource owner / not an approved recruiter), `404` (resource not found or
not yours), `409` (conflict â€” e.g. duplicate company name, already on the
team).

