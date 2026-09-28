# V22.3 — Application Timeline, Notes & Documents

Turns each application (V22.1 `Application` / `ApplicationStatusHistory`,
V22.2 dashboard/Kanban) into a full candidate workspace: notes,
interview tracking, application-specific tasks/follow-ups, secure
document storage, and a unified chronological timeline. All additive —
no existing table, migration, model, or endpoint is modified.

## Architecture

```
app/models/domain.py
    ApplicationNote        — NEW
    ApplicationInterview   — NEW
    ApplicationTask        — NEW
    ApplicationDocument    — NEW (metadata only; bytes live on disk)
    ApplicationEvent       — NEW (unified activity log; see Timeline model)

app/applications/
    service.py    — V22.1/V22.2, UNCHANGED. get_application() is the one
                     ownership check every module below calls first.
    notes.py       — NEW: create/list/update/delete notes
    interviews.py  — NEW: create/list/update/delete interview rounds
    tasks.py       — NEW: create/list/update/delete + overdue check
    documents.py   — NEW: secure upload/list/download/delete
    events.py      — NEW: shared ApplicationEvent writer, called by the
                     four modules above at the moment they create (or,
                     for interviews/tasks, meaningfully transition) a row
    timeline.py    — NEW: merges ApplicationStatusHistory + ApplicationEvent
                     into one ordered feed at read time

app/api/
    applications.py            — V22.1/V22.2, UNCHANGED
    application_workspace.py   — NEW: all V22.3 HTTP endpoints
```

Every notes/interviews/tasks/documents/timeline function resolves the
parent application through `service.get_application(db, user_id,
application_id)` first — the exact same function
`app/api/applications.py` already relies on — so application ownership
continues to live in exactly one place, and a mismatched or
nonexistent `application_id` always surfaces as 404 before any child
row is touched.

## Database schema

Migration: `backend/migrations/v22_3_application_workspace.sql` (new
file only — no existing migration edited).

| Table | Key columns | Notes |
|---|---|---|
| `application_notes` | `application_id` FK CASCADE, `content`, `created_at`, `updated_at` | |
| `application_interviews` | `application_id` FK CASCADE, `interview_type`, `round_name`, `scheduled_at`, `duration_minutes`, `interviewer_name/email`, `meeting_url`, `location`, `notes`, `result` | `result` starts `SCHEDULED` |
| `application_tasks` | `application_id` FK CASCADE, `title`, `description`, `due_at`, `completed`, `completed_at` | |
| `application_documents` | `application_id` FK CASCADE, `category`, `original_filename`, `stored_filename` (unique), `file_size`, `mime_type`, `uploaded_at` | see Document security below |
| `application_events` | `application_id` FK CASCADE, `event_type`, `title`, `description`, `metadata_json`, `occurred_at` | status changes are NOT stored here — see Timeline model |

All five tables index `(application_id, <primary time column>)` for
fast per-application list/timeline queries. `ON DELETE CASCADE`
everywhere, so deleting an `Application` cleans up all of its child
rows automatically (V22.1's delete path is untouched and gets this for
free).

## Timeline model

`app/applications/timeline.get_timeline()` does **not** introduce a
second status-change log. It reads `ApplicationStatusHistory` (V22.1,
unchanged) directly for status-change entries — including the
synthetic `old_status IS NULL` row written when the application itself
was created, surfaced as `APPLICATION_CREATED` — and merges those with
`ApplicationEvent` rows (notes/interviews/tasks/documents activity,
written by their own modules via `events.record_event()`), sorting the
combined list by timestamp. Default order is newest-first
(`?order=desc`); `?order=asc` is also supported.

`event_type` vocabulary: `APPLICATION_CREATED`, `STATUS_CHANGED`,
`NOTE_ADDED`, `INTERVIEW_SCHEDULED`, `INTERVIEW_COMPLETED`,
`TASK_CREATED`, `TASK_COMPLETED`, `DOCUMENT_UPLOADED`.

`INTERVIEW_COMPLETED` is recorded only on the transition *into* a
resolved result (`COMPLETED`/`PASSED`/`FAILED`) from a
non-resolved one — editing an already-resolved interview again does
not spam the timeline.

## Document security

Documents are the one V22.3 feature that touches the filesystem, so
the design leans on "never trust the client" throughout:

- **Filename**: the on-disk name (`stored_filename`) is always a
  fresh `uuid4().hex` plus an already-validated extension — the
  client's `original_filename` is stored *only* as display metadata
  and is never used to build a filesystem path. This closes off path
  traversal by construction rather than by sanitizing traversal
  sequences out of a user-controlled name.
- **Storage location**: `settings.application_document_storage_dir`
  (`var/uploads/application_documents` by default) is a private
  directory never mounted as static/public by `app/main.py`. The only
  way to read a file back is `GET
  /applications/{id}/documents/{document_id}/download`, which
  re-resolves ownership on every call.
- **Type validation**: extension allowlist (`.pdf .docx .doc .txt
  .png .jpg .jpeg`) plus content-type allowlist, reusing
  `app.core.uploads.read_upload_limited` (the same helper the V17
  resume upload already uses).
- **Size validation**: capped by
  `settings.application_document_max_upload_mb` (10 MB default),
  enforced while streaming the read (not after loading an unbounded
  body into memory).
- **List responses never include `stored_filename`** or any path —
  only id/category/original_filename/file_size/mime_type/uploaded_at.
- **Ownership**: every document operation (list/upload/download/delete)
  re-checks `application_id` ownership via `service.get_application`
  before touching the DB row or the file on disk.

## Interview model

`interview_type` ∈ `{PHONE, VIDEO, TECHNICAL, HR, MANAGERIAL,
ASSESSMENT, ONSITE, OTHER}`. `result` ∈ `{SCHEDULED, COMPLETED,
PASSED, FAILED, CANCELLED, RESCHEDULED}`, defaulting to `SCHEDULED`.
Interview results are informational only — they never automatically
change the parent `Application.status`; the candidate still updates
that explicitly via the existing V22.1 status endpoint, same as
before V22.3.

## Task model

Tasks are scoped to one application (`application_id` required), not
a general to-do list, so they surface directly in that application's
workspace and timeline. `is_overdue()` compares `due_at` against
today's date and is always `False` once `completed=True`; the API
exposes it as a computed `overdue` field on every task in list/detail
responses rather than making the frontend recompute it.

## API

All under `/api/v1`, all require the existing bearer-token
`current_user` dependency, all scoped through the parent application:

```
Notes
  GET    /applications/{id}/notes
  POST   /applications/{id}/notes
  PATCH  /applications/{id}/notes/{note_id}
  DELETE /applications/{id}/notes/{note_id}

Interviews
  GET    /applications/{id}/interviews
  POST   /applications/{id}/interviews
  PATCH  /applications/{id}/interviews/{interview_id}
  DELETE /applications/{id}/interviews/{interview_id}

Tasks
  GET    /applications/{id}/tasks?include_completed=true|false
  POST   /applications/{id}/tasks
  PATCH  /applications/{id}/tasks/{task_id}
  DELETE /applications/{id}/tasks/{task_id}

Documents
  GET    /applications/{id}/documents
  POST   /applications/{id}/documents            (multipart: category, file)
  GET    /applications/{id}/documents/{document_id}/download
  DELETE /applications/{id}/documents/{document_id}

Timeline
  GET    /applications/{id}/timeline?order=asc|desc   (default desc)
```

Every endpoint returns 404 (not 403) for a nonexistent or not-owned
`application_id`/child id, matching V22.1's existing convention —
this avoids confirming to a caller *whether* a given id exists versus
whether they own it. Validation errors (bad `interview_type`, empty
note content, oversized file, unsupported file type) return
400/413/422 as appropriate.

## Testing

`backend/tests/test_v22_3_application_workspace.py` covers:

- Notes: create/read/update/delete, content-length validation,
  cross-user isolation (IDOR) on list/update/delete
- Interviews: create/update/delete, `interview_type` validation,
  `INTERVIEW_COMPLETED` timeline event on result transition
- Tasks: create/complete/uncomplete/update/delete, `overdue` flag for
  past vs. future `due_at`, title validation
- Documents: upload/list/download/delete round-trip, unsupported
  extension rejected (400), oversized file rejected (413), cross-user
  isolation on download/delete, `stored_filename` never present in
  API responses
- Security: an invalid/foreign `application_id` returns 404 rather
  than exposing whether the resource exists
- Timeline: newest-first default ordering, `?order=asc`, and that both
  `ApplicationStatusHistory`-derived and `ApplicationEvent`-derived
  entries appear together

**Execution status: NOT VERIFIED.** This sandbox has no network
egress (`pip install` / `npm install` both fail with 403 from a
network policy, confirmed when attempted), so neither `pytest` nor a
frontend build could actually be run here. Every new/modified Python
file passed `python -m py_compile` (syntax-valid), and every new
import, model field, function signature, and CSS class referenced by
the new frontend code was manually cross-checked against the existing
codebase it calls into (see PR notes / final report). This is not a
substitute for actually running the suite — please run
`pytest backend/tests/test_v22_3_application_workspace.py` and the
full existing suite, plus `npm run build`, in an environment with
package-registry access before deploying.
