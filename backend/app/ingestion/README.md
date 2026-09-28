# CareerOS ingestion (V2 automated collection + V3 private careers)

## Pipeline

`Adapter.fetch()` → `normalize_job()` → `is_duplicate()` → `publish_to_review()`

Adapters emit `JobRecord` objects. The pipeline normalizes text fields,
checks stable identifiers (source+reference, notification URL, apply
URL, then organization+title) for duplicates, and inserts new records
with `status="review"`. **Nothing an adapter collects is ever
auto-published** — an admin must call `/admin/jobs/{id}/publish` first.
This is the deliberate boundary that lets automated collection exist
at all without risking bad data reaching candidates.

## Adapter types

- **Manual/metadata adapters** (`adapters/ssc.py`, `adapters/upsc.py`,
  `adapters/rrb.py`, `adapters/demo.py`, `adapters/generic_metadata.py`)
  — take a list of dicts you (or an upstream integration) supply. No
  network access. `generic_metadata.py` is the reusable one for V3
  private/internship/apprenticeship listings, parameterized by
  organization and job type rather than hardcoded per employer.
- **`collectors/rss_adapter.py` — `RSSAdapter`** — generic RSS/Atom
  reader. Point it at any feed URL; it emits one `JobRecord` per entry.
- **`collectors/html_list_adapter.py` — `HTMLListAdapter`** — generic,
  *configured* HTML listing-page scraper for government notice boards
  that don't expose a feed.
- **`collectors/greenhouse_adapter.py` / `collectors/lever_adapter.py`**
  — V3 private-sector collectors against Greenhouse's and Lever's
  public, documented, unauthenticated job-board APIs. These are
  legitimate to read (the companies expose them for exactly this
  purpose) — unlike scraping LinkedIn/Naukri/Internshala, whose terms
  of service generally prohibit it. See each module's docstring.

## V3 partner submissions (private careers)

The primary intake path for private-sector listings isn't scraping —
it's direct submission via `app/api/partners.py`:

1. Admin registers the employer/aggregator: `POST /admin/partners`
   (admin key required) — returns a one-time API key; only its hash is
   stored, so save it immediately.
2. The partner submits listings: `POST /partners/jobs` with
   `X-Partner-Id` / `X-Partner-Key` headers. Same review-queue pipeline
   as everything else — a partner key does not bypass admin review.
3. `POST /admin/partners/{id}/deactivate` revokes a partner without
   touching anyone else's access.

## Automated collection (V2/V3 scheduled sources)

`app/ingestion/sources.py` is the single registry of sources for
scheduled collection (both government and private/Greenhouse/Lever
entries live here). Every entry ships **disabled** — see the
docstring at the top of that file for the enable checklist. Once
enabled:

- The in-process scheduler (`app/scheduler.py`, backed by
  APScheduler) runs every `INGESTION_INTERVAL_MINUTES` while
  `INGESTION_ENABLED=true`.
- `POST /admin/ingest/run` (admin key required) triggers a pass
  on-demand — useful right after enabling a source, or from an
  external cron if you'd rather not run the in-process scheduler on
  every replica.
- `GET /admin/ingest/sources` lists configured sources and whether
  they're enabled.
- `GET /admin/ingest/runs` shows the last 50 runs (source, counts,
  status, error if any) — backed by the `ingestion_runs` table.

## Adding a new source

1. Confirm the official URL and, for HTML sources, the current CSS
   structure of the listing page (browser dev tools → inspect a row).
   For Greenhouse/Lever, confirm the real board token/site slug from
   the company's public careers page URL.
2. Add a `SourceConfig` entry in `sources.py`, with `enabled=False`
   initially.
3. Run it once manually: `POST /admin/ingest/run?source=<name>` (or
   `python -m scripts.run_ingestion_now` locally) and check
   `/admin/review` — never flip `enabled=True` for unattended
   scheduling until a manual run looks correct.
4. Flip `enabled=True` once you've verified the output.

## Operational notes

- All requests go out with an identifying `User-Agent`
  (`INGESTION_USER_AGENT`) and respect `robots.txt` on a best-effort
  basis — set a real contact email in the user-agent string before
  enabling anything against a live site.
- A single replica should own scheduled collection in a
  multi-replica deployment (set `INGESTION_ENABLED=false` on the
  others) to avoid duplicate concurrent runs; deduplication in
  `services/deduplicate.py` also protects against double-inserts if
  that's ever violated.
- Government site layouts and feed availability change without
  notice. Treat every selector in `sources.py` as needing periodic
  re-confirmation, not a one-time setup.
- Never build a scraper against a platform whose terms of service
  prohibit it (LinkedIn, Naukri, Internshala, and similar) — use the
  V3 partner submission path for those employers/postings instead.

