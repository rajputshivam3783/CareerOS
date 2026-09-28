# NORMALIZATION_ENGINE â€” V19.2

## What normalization means here

Every collector â€” old (V2's RSS/HTML-list adapters, V19.1's
`SmartOfficialAdapter`) or new (V19.2's XML/JSON API/PDF-metadata/
Sitemap collectors) â€” emits the same shape: a `JobRecord`
(`app/ingestion/models/job_record.py`, unchanged Pydantic model). No
new adapter of any source type produces a different intermediate
shape, and there is no parallel "Government Job" table â€” everything
still flows into the single, existing `Job` table
(`app/models/domain.py`), exactly as V19.1 requires.

`SourceAdapter.normalize()` (default implementation) is a thin wrapper
around the existing, unmodified `app.ingestion.services.normalize.normalize_job`
â€” every V2/V19.1 adapter already ran through this function, so its
behavior for every pre source is byte-for-byte unchanged:

- Whitespace/casing cleanup on text fields.
- `organization`, `title`, `description` defaulting/trimming.
- Structural fields (`vacancies`, `deadline`, `exam_date`, ...) pass
  through as typed values, not free text, so downstream duplicate
  detection and change detection can compare them directly.

## New source types feed the same pipeline

The point of adding `XMLFeedAdapter`, `JSONAPIAdapter`,
`PDFMetadataAdapter`, and `SitemapAdapter` in V19.2 was specifically
so each of them constructs a `JobRecord` the same way the existing
collectors do â€” they differ only in *how they read the source*, never
in what they hand off to `normalize_job()`. For example:

- `JSONAPIAdapter` maps arbitrary JSON keys (via a configured
  `field_map`) onto the standard `JobRecord` fields before returning.
- `PDFMetadataAdapter` runs the existing V5 `pdf_parser.parse_notification_fields`
  heuristic extractor and maps its output (`qualification`, `age_limit`,
  `vacancies`, `application_fee`, `deadline`, `exam_date`) onto the same
  fields â€” it doesn't invent new ones.
- `SitemapAdapter` is the lowest-fidelity source (URL slug â†’ best-effort
  title) but still emits a standard `JobRecord`, deliberately flagging
  its own low confidence in the record's `description` field rather
  than pretending to structured data it doesn't have.

## Adapter-specific normalization

An adapter can override `normalize()` if a source needs bespoke
cleanup beyond the shared normalizer (e.g. a source that encodes
vacancy counts as roman numerals). None of the V19.2 collectors
currently need this â€” the override point exists for future sources
where it becomes necessary, without changing the shared default for
everyone else.

## Where this sits in a run

`app.ingestion.orchestrator.run_source`: `fetch()` â†’ **`normalize()`
per record** â†’ `detect_change()` â†’ `publish_to_review()` (which itself
calls `is_duplicate()` again as a safety net). Normalization always
happens before duplicate/change detection, so both of those compare
clean, consistent values rather than raw source-specific formatting.

