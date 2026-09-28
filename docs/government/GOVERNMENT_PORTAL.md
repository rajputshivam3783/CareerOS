# GOVERNMENT_PORTAL â€” V19.3

Builds on V19.1 (Government Recruitment Core) and V19.2 (Official
Source Adapter Framework). Authentication, Security, Recruiter ATS,
AI, Search Engine, Notifications, Analytics, Deployment, and Docker
were not touched. This document covers the public-facing portal only.

## Data source discipline

**Every page in this document reads from the existing `Job` /
`RecruitmentUpdate` tables, populated only by the V19.2 adapter
framework (or, for now, the existing `POST /admin/ingest` manual path
that predates it) â€” nothing added in V19.3 hardcodes a recruitment.**
Where a section currently has no data (most sources are still
`status="disabled"` pending operator verification, per
`SOURCE_ADAPTER_ARCHITECTURE.md`), the page shows a genuine empty
state, not placeholder content.

## What already existed (V16/V9) vs. what V19.3 adds

Reading the full repository before starting turned up substantially
more than the V19.3 task brief assumed already existed:

| Already there (unchanged) | Added in V19.3 |
|---|---|
| `GET /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/timeline` | 4 new lifecycle sections: medical-examination, final-selection, cancelled-recruitments, archive |
| `GET /government/home`, `GET /government/sections/{section}` (12 sections) | `GET /government/filters` (real facet values), `GET /government/search` (organization/exam/post/qualification/location/ad-number) |
| `SavedJob` bookmarks (`POST`/`DELETE`/`GET /saved-jobs`) | Sort (`newest`/`deadline`/`vacancies`/`organization`) + `X-Total-Count` on section/search endpoints |
| A basic single-page `/government` hub | The full dedicated-page portal structure described below |
| A client-only `/jobs/[id]` detail page | Server-rendered metadata + `JobPosting` structured data on the same page, plus Eligibility/Age Limit/Application Fee/Important Dates sections |

Bookmarks in particular are **not** a new entity per content type â€”
"Save Recruitments / Results / Admit Cards" all bookmark the
underlying `Job` row (`lib/bookmarks.ts` wraps the existing
`SavedJob` endpoints), because a result or admit card is a lifecycle
event *on* a job, not a separate saveable thing.

## Page structure

- `/government` â€” landing page (server component): hero, live section
  counts from `government/home`, a section grid linking to all 16
  dedicated pages, and a "Latest / Closing soon" preview (client
  subcomponent `GovHomeClient` for bookmark/share interactivity).
- `/government/<section>` â€” one route per section (latest-jobs,
  results, admit-cards, answer-keys, syllabus, admissions,
  scholarships, counselling, cutoffs, merit-lists,
  document-verification, medical-examination, final-selection,
  joining, cancelled-recruitments, archive). Each route is a thin
  wrapper (title/description/mode + two feature flags) around one
  shared component, `GovSectionBrowser` â€” not 16 separate
  implementations.
- `/government/search` â€” advanced search across every field a
  recruitment portal's users actually search by.
- `/jobs/[id]` â€” the recruitment detail page (shared with private-
  sector jobs, same as before V19.3): now split into a server
  component (`page.tsx`, metadata + JSON-LD) and a client component
  (`JobDetailClient.tsx`, unchanged interactive logic plus new
  Eligibility/Age Limit/Application Fee/Important Dates sections,
  breadcrumbs, and a share button).

## `GovSectionBrowser` â€” the shared component

Handles, uniformly across every section: cards/table view toggle,
pagination (Previous/Next, same pattern as the existing `/jobs` page)
or infinite scroll (opt-in per section via `allowInfiniteScroll`,
enabled only for Latest Jobs per the spec), sorting, search +
organization/govt-level/category filters (+ qualification/location/
ad-number for Latest Jobs specifically, via `showAdvancedFilters`),
bookmarking, sharing (native share sheet with clipboard fallback),
official-link/notification-PDF buttons, and an "Apply now" button
where the job has an `apply_url`.

It normalizes two different backend shapes into one rendering path:
`mode="jobs"` sections (Latest Jobs, Scholarships, Archive) get
`Job[]` directly; `mode="updates"` sections (Results, Admit Cards,
...) get `{update, job}[]` pairs from `RecruitmentUpdate` joined to
`Job`.

## Recruitment detail page sections

Overview, Important Dates (deadline/exam date/admit card/result),
Vacancy Details, Eligibility (qualification + age limit), Application
Fee, Selection Process, Recruitment Timeline (Government jobs only,
unchanged from V16), Important Links (notification/official
website/admit card/result), plus Save/Share/Apply actions and
breadcrumbs â€” all backed by existing `Job` columns; no new field was
added to the schema for this page.

## Filters taxonomy

The spec listed a fixed filter taxonomy (Central/State/PSU/Police/
Railway/Bank/Teaching/Engineering/Medical/Law/Defence/Judiciary/ITI/
Diploma/Graduation/Post Graduation). `GET /government/filters`
deliberately does **not** hardcode this list â€” it returns the actual
distinct `govt_level`/`category`/`organization` values present in
published Government jobs. Until adapters ingest data using some of
those specific category labels, they simply won't appear as filter
options â€” which is the correct behavior per "Do NOT hardcode
recruitment data," rather than showing filter buttons that silently
return zero results.

## What V19.3 does not include

Per the stated stop condition: Email/SMS/Push alerts, ingestion
automation or scheduler enhancements, and AI features remain V19.4/
V20 scope. Two existing sections from V16
(`government-internships`, `research-fellowships`) already have
working API support but were not given dedicated V19.3 route pages,
since they weren't in this version's requested section list â€” they
remain reachable via `GET /government/sections/{section}` for now.

