# PUBLIC_API â€” Government Portal

All endpoints below are public (no auth required), mounted under the
existing `/api/v1` prefix, and documented automatically in the
existing Swagger/OpenAPI UI (`/api/v1/docs`, `/api/v1/openapi.json`) â€”
V19.3 added no new documentation mechanism, only new routes on the
existing FastAPI app.

## `GET /government/home`

Aggregated dashboard payload for the portal landing page.

**Response:**
```json
{
  "counts": { "latest_jobs": 0, "results": 0, "admit_cards": 0, "...": 0 },
  "latest_jobs": [ /* up to 12 most recent published Job rows */ ],
  "closing_soon": [ /* up to 12 published Job rows with the nearest deadline */ ]
}
```

## `GET /government/sections/{section}`

One endpoint behind every section page. `section` is one of:
`latest-jobs`, `results`, `admit-cards`, `answer-keys`, `admissions`,
`syllabus`, `exam-dates`, `important-notices`, `cutoffs`,
`merit-lists`, `document-verification`, `counselling`, `joining`,
`medical-examination` *(new)*, `final-selection` *(new)*,
`cancelled-recruitments` *(new)*, `scholarships`,
`government-internships`, `research-fellowships`, `archive` *(new)*.

| Query param | Type | Notes |
|---|---|---|
| `search` | string | Title/organization/qualification/ad-number substring |
| `organization` | string | Organization substring |
| `qualification` | string | *(new)* Qualification substring |
| `ad_number` | string | *(new)* Advertisement number substring |
| `location` | string | *(new)* Location substring |
| `govt_level` | string | *(new)* Exact match against `Job.govt_level` |
| `category` | string | *(new)* Category substring |
| `sort` | `newest`\|`deadline`\|`vacancies`\|`organization` | *(new)* Only affects `Job`-shaped sections; update-shaped sections always sort by event date |
| `limit` | int, 1â€“100, default 30 | |
| `offset` | int, default 0 | |

**Response shape** depends on the section kind:
- *Job-shaped* (latest-jobs, scholarships, government-internships,
  research-fellowships, archive): `Job[]`.
- *Update-shaped* (everything else): `[{ "update": RecruitmentUpdate, "job": Job }]`.

`X-Total-Count` response header *(new)* gives the total match count
for pagination, independent of `limit`.

## `GET /government/filters` *(new)*

No parameters. Returns the real distinct facet values found in
published Government jobs â€” never a hardcoded list:

```json
{ "govt_levels": ["Central", "PSU", "..."], "categories": ["Banking", "..."], "organizations": ["...", "..."] }
```

## `GET /government/search` *(new)*

Advanced, cross-section search over every published Government job.

| Query param | Maps to |
|---|---|
| `organization` | `Job.organization` |
| `exam` | `Job.title` OR `Job.category` |
| `post` | `Job.title` |
| `qualification` | `Job.qualification` |
| `location` | `Job.location` |
| `ad_number` | `Job.ad_number` |
| `govt_level`, `category` | Same as above |
| `sort`, `limit`, `offset` | Same as above |

Returns `Job[]` with an `X-Total-Count` header.

## `GET /jobs/{id}` and `GET /jobs/{id}/timeline`

Unchanged from before V19.3 â€” the recruitment detail page's data
source. `timeline` returns `{ "updates": RecruitmentUpdate[] }` for
Government jobs.

## `GET/POST/DELETE /saved-jobs...`

Unchanged â€” the bookmark mechanism every "Save" button in the portal
(recruitments, results, admit cards alike) calls, since a result/
admit card bookmark is really a bookmark on its parent `Job`.

## SEO-adjacent routes

`GET /sitemap.xml` and `GET /robots.txt` are served by the
**frontend** (Next.js native `app/sitemap.ts`/`app/robots.ts`), not
the backend API â€” see `SEO_GUIDE.md`. The sitemap itself calls
`GET /jobs?limit=500&job_type=Government` (unchanged endpoint) to
enumerate recruitment detail URLs.

