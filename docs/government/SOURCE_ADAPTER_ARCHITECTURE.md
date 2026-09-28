# SOURCE_ADAPTER_ARCHITECTURE â€” V19.2 Official Source Adapter Framework

Builds on V19.1 (Government Recruitment Core). Authentication, Security,
Recruiter ATS, AI, Search, Notifications, Analytics, Deployment, and
Docker were not touched. This is a framework, not a scraper collection â€”
see the "What is/isn't included" section at the end for the exact
scope boundary.

## The core idea

V19.1 built `SourceRegistry` (one catalog row per organization) but
explicitly deferred the pieces needed to actually *run* those rows on
a schedule with retries, health tracking, and change detection
(`SOURCE_REGISTRY.md`: "V19.1 only builds the registry, not a
scheduler for it"). V19.2 is that missing piece, built as a plugin
framework rather than one bespoke class per organization:

```
SourceRegistry row (DB)  â†’  ConfiguredSourceAdapter  â†’  a collector
  (name, url, type,           (the plugin factory)        (SmartOfficialAdapter /
   config JSON, schedule,                                  HTMLListAdapter / RSSAdapter /
   priority, status)                                        XMLFeedAdapter / JSONAPIAdapter /
                                                              PDFMetadataAdapter / SitemapAdapter)
```

Adding organization #301 is a database row (via
`POST /government/sources` or the admin Source dashboard), not a code
change. That's what "no monolithic scraper" means in practice here â€”
a monolithic scraper is exactly what an ever-growing `if org ==
"UPSC": ... elif org == "SSC": ...` ladder would become; a config row
per organization avoids that entirely.

## The plugin interface

`app/ingestion/adapters/interface.py` defines `SourceAdapter`, extending
the existing V2 `BaseJobAdapter` (whose only contract was `fetch()`).
Every method has a working default built from existing V2/V19.1
services, so a minimal adapter needs only `fetch()` + `metadata()`:

| Method | Default implementation | Purpose |
|---|---|---|
| `metadata()` | *(required)* | Static description (org, source type, URL) for the admin UI |
| `validate()` | URL well-formedness check | Cheap, no-network config sanity check before scheduling |
| `fetch()` | *(required)* | Unchanged V2 contract â€” hit the source, return `JobRecord`s |
| `normalize()` | `app.ingestion.services.normalize.normalize_job` | Same normalizer every V2/V19.1 adapter already uses |
| `deduplicate()` | `app.ingestion.services.deduplicate.is_duplicate` | Same dedup logic, extended in V19.2 (see `DUPLICATE_DETECTION.md`) |
| `save()` | `app.ingestion.services.publisher.publish_to_review` | Still review-queue-only â€” nothing here auto-publishes |
| `health()` | `app.ingestion.services.health.get_health` | Reads the `SourceRegistry` health snapshot |

## The plugin factory: `ConfiguredSourceAdapter`

`app/ingestion/adapters/configured.py` turns one `SourceRegistry` row
into a runnable `SourceAdapter` by delegating to the right collector
based on `collector_type`, using a small JSON `config` column for
collector-specific parameters (CSS selectors, JSON paths, XML item
paths, etc â€” see the docstring in that file for the exact shape per
type). `validate()` catches a malformed config (missing selector,
missing URL, an unimplemented placeholder type) before the source is
ever scheduled, not mid-run.

## Source types supported

| `collector_type` | Collector class | Notes |
|---|---|---|
| `official_html` | `SmartOfficialAdapter` | Keyword-scans a notice board for recruitment-shaped links |
| `html_list` | `HTMLListAdapter` | CSS-selector-driven table/list scraping |
| `rss` | `RSSAdapter` | RSS 2.0 / Atom |
| `xml` | `XMLFeedAdapter` (**new**) | Arbitrary XML with a configurable item path |
| `json_api` | `JSONAPIAdapter` (**new**) | JSON REST/feed endpoint with a dotted list-path + field map |
| `pdf_metadata` | `PDFMetadataAdapter` (**new**) | Listing page of PDF links; best-effort field extraction via the existing V5 PDF parser |
| `sitemap` | `SitemapAdapter` (**new**) | `sitemap.xml` (one level of sitemap-index nesting) filtered by URL pattern |
| `selenium`, `playwright` | *(none yet)* | Registry-only placeholders for Future Browser Automation â€” no collector is implemented in this version |

## Orchestration: `app/ingestion/orchestrator.py`

`run_source(db, source_row)` is the V19.2 counterpart to the existing
V2 `ingest.run_ingestion` (unchanged) â€” it runs one *database-registered*
source end to end:

1. Skip if `status != "active"` or the circuit breaker is open.
2. `validate()` â€” fail fast on bad config.
3. `fetch()` wrapped in retry-with-backoff (`app.ingestion.services.errors`,
   3 attempts, exponential delay).
4. Per record: `normalize()` â†’ `detect_change()` (see below) â†’
   `publish_to_review()`. A single bad record goes to the dead letter
   queue (`IngestionDeadLetter`) instead of failing the whole run.
5. Record health (`SourceRegistry.last_latency_ms`/`availability_pct`/...)
   and circuit-breaker state.
6. Write structured, timestamped log lines (`IngestionRunLog`) and the
   roll-up `IngestionRun` row (unchanged V2 table).

Every run â€” success, failure, or skip â€” leaves an inspectable
`IngestionRun` row. Nothing here is a silent no-op.

## Adding a new organization

1. `POST /government/sources` with `source_name`, `official_url`,
   `collector_type`, and (if needed) `config`. Leave `status` at its
   default (`"disabled"`).
2. `POST /government/sources/{id}/validate` â€” confirms the config is
   well-formed.
3. `POST /government/sources/{id}/run` â€” a manual trial run; inspect
   the resulting `IngestionRun`/logs/dead-letters.
4. Once you've confirmed the source behaves, `PATCH` `status` to
   `"active"` and set a `schedule` (`"hourly"` / `"daily"` / `"manual"`).

This is exactly how the ~30 central organizations in
`app/ingestion/registry_seed.py` are meant to be activated, and it's
also the documented path for **state-level bodies** (State PSCs,
Police Recruitment Boards, High Courts, Universities, Health
Recruitment Boards) â€” one row per state, added the same way. They are
deliberately **not** pre-seeded (see that file's docstring): there are
~29 states behind each category, and seeding specific URLs this
codebase never loaded live would be exactly the "unofficial scraper"
risk this framework exists to avoid.

## What is / isn't included in V19.2

**Included:** the plugin interface and factory, six real collector
types, retry/backoff, circuit breaker, dead letter queue, health
tracking, change detection, an in-process scheduler with priority
ordering, admin API (manual run/validate/health/runs/logs/statistics/
scheduler/seed), the admin Source dashboard, and a curated (disabled-
by-default) catalog of ~30 central organizations.

**Not included** (see `ROADMAP.md` for V19.3+): a real background
worker process / cron wiring (the scheduler is a pure function you
call from *something* â€” a cron hitting `POST /government/scheduler/run-due`
is the simplest option, see `SCHEDULER.md`), browser-automation
collectors (Selenium/Playwright), a distributed task-queue integration,
and any Government Portal-facing pages (Latest Jobs / Results / Admit
Cards / Answer Keys / Scholarships / Admissions) â€” those remain V19.3/
V19.4 per the original scope boundary.

