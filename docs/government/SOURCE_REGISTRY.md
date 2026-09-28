# SOURCE_REGISTRY â€” V19.1

## Two tables, two purposes

This codebase already had `IngestionRun` (table `ingestion_runs`,
since V2) â€” one row **per run** of an adapter, recording
discovered/created/skipped counts and a status for that run. V19.1
adds `SourceRegistry` (table `source_registry`) â€” one row **per
source**, a standing catalog entry every future adapter registers
itself into. They complement each other:

- `IngestionRun` â€” the log ("what happened each time X ran")
- `SourceRegistry` â€” the catalog ("what sources exist, and their
  current schedule/status/health at a glance")

## Schema

| Column | Type | Notes |
|---|---|---|
| `id` | int, PK | |
| `source_name` | varchar(220), unique | Matches `IngestionRun.source_name` and the existing `SourceConfig.name` values in `app/ingestion/sources.py` |
| `official_url` | varchar(1000), nullable | |
| `collector_type` | varchar(30) | One of `official_html`, `rss`, `xml`, `json_api`, `selenium`, `playwright` â€” see `SOURCE_COLLECTOR_TYPES` in `app/core/constants.py` |
| `schedule` | varchar(60), nullable | Free text (e.g. `"daily"`) â€” a cadence description, not a cron scheduler |
| `status` | varchar(20) | `active` / `paused` / `disabled` (default `disabled`) |
| `last_run_at` | timestamp, nullable | Populated by `POST /government/sources/{id}/sync-runs` |
| `last_success_at` | timestamp, nullable | Same |
| `error_count` | int | Count of `IngestionRun` rows with `status="failed"` for this source, refreshed the same way |
| `created_at`, `updated_at` | timestamp | |

## Registering a source

`POST /api/v1/government/sources` (admin-only):

```json
{
  "source_name": "UPSC",
  "official_url": "https://www.upsc.gov.in/examinations/active-exams",
  "collector_type": "official_html",
  "schedule": "daily",
  "status": "disabled"
}
```

Registering a source is purely a catalog entry â€” it does **not**
enable scraping. Turning an adapter on for real is still governed
entirely by `app/ingestion/sources.py` (`SourceConfig.enabled`), per
the pre-existing V2 policy documented there: an operator must
manually verify a source's live page structure before flipping
`enabled=True`. Nothing added in V19.1 changes that policy or
auto-enables anything.

## Keeping the registry's health fields current

`POST /api/v1/government/sources/{id}/sync-runs` re-derives
`last_run_at`, `last_success_at`, and `error_count` from the existing
`ingestion_runs` table for that `source_name`. This is a pull, not a
push â€” nothing in `app/ingestion/ingest.py` (unchanged) writes to
`source_registry` automatically. Wiring an automatic sync after every
run is a reasonable V19.2+ follow-up once real collectors exist to
generate that traffic; V19.1 only builds the registry itself, per the
"ingestion framework only, no new collectors" scope boundary.

## Relationship to the existing coverage catalog

`app/ingestion/source_catalog.py` (`TIER_A`/`COVERAGE_TARGETS`,
surfaced at `GET /government/coverage`) is a **static, code-level**
list of sources with implemented-but-unverified adapters, or ones
targeted for future adapter work. `SourceRegistry` is the
**database-level**, admin-editable counterpart â€” a `TIER_A` entry
becoming operational is expected to also get a `SourceRegistry` row
(via `POST /government/sources`) so its schedule/status/health is
trackable at runtime, but the two lists are not automatically kept in
sync in this pass.

