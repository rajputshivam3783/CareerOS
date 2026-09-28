# Search UX â€” V21.2

## Design intent

Learn from the *interaction patterns* mature job platforms have
converged on (category-first navigation, grouped autocomplete,
filter chips, salary-direction sorting) without copying any specific
platform's UI, copy, branding, or layout â€” CareerOS keeps its own
existing visual language (`globals.css` design tokens, `.card`/`.chip`/
`.pill` components already used across the app) rather than
introducing a new visual system for this one page.

## States implemented

| State | Where |
|---|---|
| Initial | Category tabs + empty search box, recent searches shown if any exist |
| Loading | `SearchLoadingState` (V21.1, reused as-is) |
| Results | `JobResultCard` grid |
| Empty (zero-result) | Original query echoed back, filter-removal suggestion, deterministic related-term chips from `result.suggestions` (V21.1's spelling/alternative-category engine â€” see `SEARCH_RELEVANCE.md`) |
| Error | `SearchErrorState` (V21.1, reused as-is) with a Retry button |
| Offline/retry | Not separately implemented â€” the existing `SearchErrorState`'s retry button covers a failed request generically (network failure surfaces as the same error path); no distinct "you are offline" detection was added this release |

## Search bar & autocomplete

`DiscoverySearchBox` supports combined free-text queries ("Java
Developer Noida", "Python Internship Delhi") the same way V21.1's
underlying multi-field text search always has â€” this is unchanged
tokenized/phrase matching, not new parsing. What's new in V21.2 is
**grouping the autocomplete dropdown by type** (Job Titles, Companies,
Government Organizations, Skills, Locations) instead of one flat list,
using the new `GET /search/autocomplete/grouped` endpoint. Keyboard
navigation (arrow keys move through the flattened, grouped list; Enter
selects; Escape closes) works across group boundaries, matching the
spec's explicit requirement.

## Category tabs

All Opportunities / Private Jobs / Government Jobs / Internships /
Apprenticeships â€” implemented as a chip/chip-active row (the same
pattern the Learning Center page (`/learning`) already established for
tabbed sections), not a new tab-bar component.

## Zero-result & query correction

Both reuse V21.1's existing engine unchanged (`service.py`'s
alternative-suggestion logic, spelling correction against a fixed
typo-lookup table) â€” V21.2 did not add a second suggestion mechanism.
Per the spec, no LLM is used for these suggestions anywhere in this
codebase.

## Deliberately simple, not unpolished

- **Mobile filter drawer** is a plain show/hide (no slide transition) â€”
  the spec explicitly says "Avoid unnecessary animation. Prioritize
  speed and usability," so an animated drawer was skipped by design,
  not by oversight.
- **No skeleton loaders** were added for the discovery page
  specifically â€” it reuses V21.1's spinner-style `SearchLoadingState`.
  A skeleton card matching `JobResultCard`'s shape would look more
  polished but wasn't built this release; noted as a real gap, not
  hidden.

## Accessibility

- Search input: `role="combobox"`, `aria-expanded`, `aria-autocomplete="list"`,
  `aria-controls` pointing at the listbox.
- Autocomplete list: `role="listbox"` / `role="option"` / `aria-selected`
  on the active item.
- Category tabs: `aria-current` on the active tab.
- Filter inputs: every input has an explicit `aria-label` (many also
  have a visible placeholder, but the `aria-label` doesn't depend on
  placeholder text being read correctly by every screen reader).
- Applied filter chips: each has an `aria-label` naming exactly what
  it removes ("Remove filter Location: Noida").
- Mobile filter toggle: `aria-expanded` + `aria-controls` pointing at
  the collapsible filter body.
- Skip-to-content: the app-wide `id="main"` / skiplink pattern
  (established in V19.3's SEO_GUIDE.md) is used on `/discover`'s
  `<main>` element, same as every other page.

**What was NOT independently verified**: no screen-reader session or
axe/Lighthouse accessibility audit was run against this page in this
engagement â€” the ARIA attributes above were applied by following the
same patterns already used and reviewed elsewhere in this codebase
(V21.1's SearchBox.tsx, V19.3's government portal), not verified
against real assistive technology. See `TEST_REPORT_V21_2.md`.

## SEO

- `/discover` has static metadata (title, description,
  `alternates.canonical: "/discover"`) and is listed once (bare URL
  only) in `sitemap.ts` â€” no filter-combination URL is ever generated
  into the sitemap, per the spec's "Avoid generating unlimited
  indexable URLs from arbitrary filter combinations."
- The job detail page (`/jobs/[id]`) already had complete SEO
  (per-job metadata, canonical URL, JobPosting + BreadcrumbList
  JSON-LD, Open Graph/Twitter cards) from V19.3 â€” unchanged and
  unaffected by this release; see the existing SEO_GUIDE.md.
- `robots.ts` already disallows every private/candidate/recruiter/admin
  route; `/discover` itself is public and was not added to the
  disallow list.

