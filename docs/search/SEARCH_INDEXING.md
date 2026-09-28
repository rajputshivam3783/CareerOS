# SEARCH INDEXING â€” V21.1

All indexing operations live in `backend/app/search/indexer.py`. It's
the only module allowed to write to `search_index_documents`.

## Operations

| Operation | Function | Notes |
|---|---|---|
| Create/Update | `index_job(db, job_id)`, `index_company(db, org_id)`, `index_government_organization(db, org_id)`, `index_skill(db, skill_id)`, `index_learning_resource(db, resource_id)` | Upsert by `(entity_type, entity_id)`. If the source row no longer exists, deletes any stale index row instead of erroring â€” "reindex a deleted thing" and "reindex a never-existed thing" behave the same. |
| Delete | `delete_entity(db, entity_type, entity_id)` | |
| Bulk Index | `bulk_index(db, entity_type)` | Walks every row of the source table for one entity type, commits every 200 rows. Returns an `IndexResult(indexed, errors)` â€” a per-row exception is logged and counted, not raised, so one bad row doesn't abort the whole batch. |
| Reindex (full) | `reindex_all(db)` | Runs `bulk_index` for every entity type. Idempotent â€” running it twice produces the same index state (given unchanged source data), because every write is an upsert keyed on `(entity_type, entity_id)`. |
| Partial Update | Same as Create/Update â€” `index_job` etc. re-derive and overwrite every column from the current source row; there's no separate "patch only this field" path, since the source row is the only thing that's allowed to be authoritative. |
| Index Health | `index_health(db)` | Returns per-entity-type source-row counts vs. indexed-document counts, `last_indexed_at`, and a `healthy` boolean. |

## How freshness is kept up

**Real-time (Phase 3).** `app/search/hooks.py` provides five thin,
error-swallowing sync functions â€” `sync_job`, `sync_company`,
`sync_government_organization`, `sync_skill`, `sync_learning_resource`
â€” each re-indexing one entity and committing, without ever raising
into the calling endpoint's own transaction (a search-indexing failure
must never break publishing a job, verifying a company, etc.). Every
identified write path that changes a searchable entity's status,
content, or visibility calls the matching `sync_*` right after its own
final `db.commit()`:

- `app/api/recruiter.py` â€” job create (draft + published), update,
  delete, submit-for-review, close, reopen, archive, clone
- `app/api/admin.py` â€” job publish, reject, delete, lifecycle-update,
  manual ingest (single + bulk), company verify/reject
- `app/api/company.py` â€” company profile create/update
- `app/api/government_core.py` â€” government organization create,
  update, archive
- `app/api/skill_intelligence.py` â€” skill creation, alias addition,
  learning-resource create/update

That's 25 call sites, none of which needed more than a one-line
addition â€” see CHANGELOG_V21_1.md "Real-time indexing (Phase 3)" for
the full list and for a real ordering bug this wiring surfaced (a
`sync_*` call's own commit expiring the object the endpoint was about
to return â€” fixed by calling `sync_*` before the endpoint's own final
`db.refresh()`, not after).

**Not wired, deliberately:** the automated source-ingestion loop
(`app/ingestion/ingest.py`). Jobs land there at `status="review"` (not
public), and the publish step that actually makes a job public *is*
hooked (`app/api/admin.py`'s `publish` endpoint) â€” so nothing
user-facing was stale by leaving the ingestion loop itself alone.

**The periodic scheduler job remains, as a safety net, not the primary
mechanism.** `careeros_search_reindex` in `app/scheduler.py` still runs
`reindex_all()` every `settings.search_reindex_interval_minutes`
minutes (default 10) â€” it catches anything a hook call site missed, a
process that crashed mid-write, or a future write path someone adds
without remembering to call the matching `sync_*`. Real-time indexing
reduces how often that safety net is what actually saves the day; it
doesn't replace having one.

## Admin operations

- `POST /api/v1/admin/search/reindex` â€” triggers `reindex_all()`
  synchronously and returns per-entity-type counts. Same auth as
  every other `/admin/*` route (`app.api.admin.guard` â€” shared
  `X-Admin-Key` or a JWT for a `role="admin"`/`"super_admin"` user).
- `GET /api/v1/admin/search/index-health` â€” the Index Health report
  above.

## Bulk index batching

`bulk_index` commits every 200 rows (`commit_every` parameter) rather
than holding one transaction open for the whole table, so a full
reindex of a large table doesn't lock other writers out for the
duration.

