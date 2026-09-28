# DUPLICATE_DETECTION â€” V19.2

## Unchanged foundation

The matching logic itself is the same V19.1 logic
(`app/ingestion/services/deduplicate.py`), checked in this priority
order via `find_matching_job()` (see below):

1. `(source_name, source_reference)` â€” the same adapter reporting the
   same record.
2. `notification_url` â€” same official notice, regardless of source.
3. `(organization, ad_number)` â€” an advertisement number is only
   unique *within* its issuing organization, so this is scoped to
   both together, not `ad_number` alone.
4. `official_url`.
5. Fallback: `(organization, title)`, additionally constrained by
   `deadline` when one is available, so a yearly campaign that reuses
   a title doesn't collide across years.

Shared application portals are deliberately **not** an identifier â€”
many employers reuse one apply URL for multiple, genuinely different
openings.

## What V19.2 adds

The only change to this file is refactoring the inline `is_duplicate()`
query conditions into a shared `_match_conditions()` helper, so a new
function, `find_matching_job()`, can reuse the exact same matching
rules but return the matched `Job` row instead of a boolean.
`is_duplicate()` itself is now a one-line wrapper around that helper â€”
its behavior, return type, and every call site are unchanged.

`find_matching_job()` exists for **change detection**
(`app/ingestion/services/change_detection.py`, see `SCHEDULER.md`'s
sibling doc `SOURCE_ADAPTER_ARCHITECTURE.md`): instead of only asking
"have we seen this before, yes/no", the orchestrator now asks "have we
seen this before, and if so, *what's different this time*" â€” has a
result URL newly appeared, has the deadline moved out, has the title
picked up a "cancelled" marker. That diff is only possible with the
actual matched row, not a boolean.

## Where duplicate detection runs

Every ingestion path still funnels through the same choke point:
`publish_to_review()` calls `is_duplicate()` before inserting a `Job`
row, regardless of whether the record came from `POST /admin/ingest`,
the V2 static sources (`app/ingestion/sources.py`), or a V19.2
`ConfiguredSourceAdapter` run through the new orchestrator. There is
still exactly one place a `Job` row gets created, and exactly one
dedup check gated in front of it â€” V19.2 does not introduce a second,
parallel insertion path.

## Interaction with the V19.2 orchestrator

`run_source()` calls `detect_change()` (which internally calls
`find_matching_job()`) *and* `publish_to_review()` (which internally
calls `is_duplicate()`, using the same underlying conditions) for each
record. This is intentionally two calls rather than threading one
result through both â€” `detect_change()` needs the full `Job` row to
diff against, while `publish_to_review()`'s existing contract only
needs a boolean â€” and keeps `publish_to_review()`'s public behavior
completely unchanged for every other caller.

