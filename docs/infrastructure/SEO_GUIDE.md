# SEO_GUIDE â€” Government Portal

## What's implemented

- **Metadata** â€” every government section page exports a static
  `metadata` object (title/description/canonical/OpenGraph/Twitter
  card); the landing page and recruitment detail page use
  `generateMetadata`/server-rendered `metadata` computed from live
  API data so a crawler (or a social-share unfurler) sees real,
  current content rather than a client-only shell.
- **Structured data** â€”
  - `JobPosting` JSON-LD on every recruitment detail page
    (`/jobs/[id]`), built from the same `Job` row already serving the
    page â€” `title`, `description`, `datePosted`, `validThrough`,
    `hiringOrganization`, `jobLocation`, `employmentType`, and the
    advertisement number as a `PropertyValue` identifier when present.
  - `BreadcrumbList` JSON-LD on every page using the shared
    `Breadcrumbs` component.
- **Canonical URLs** â€” set via `alternates.canonical` in each page's
  metadata.
- **`sitemap.xml`** â€” `app/sitemap.ts` (Next.js native convention):
  every static portal route plus up to 500 of the most recent
  published Government job detail URLs, pulled live from `GET /jobs`
  â€” not a static file that goes stale.
- **`robots.txt`** â€” `app/robots.ts`: allows everything except the
  admin/recruiter/candidate-private routes, points crawlers at the
  sitemap.
- **Accessibility** â€” a skip-to-content link (`.skiplink`, targets a
  new `id="main"` wrapper added to the root layout), `aria-label`s on
  the view-mode toggle and theme toggle, `aria-current="page"` on the
  active breadcrumb, `aria-pressed` on toggle buttons.
- **Performance-relevant basics** â€” pagination/`limit` capping on
  every listing endpoint (never an unbounded query), skeleton loading
  states instead of layout-shifting spinners, and the Next.js
  `fetch(..., { next: { revalidate: N } })` caching hints on
  server-rendered data fetches (landing page: 120s; detail page: 60s;
  sitemap: 3600s) so repeat crawls/visits don't hit the API for every
  request.

## Configuration needed before deploying

Set `NEXT_PUBLIC_SITE_URL` in the frontend's environment to the
portal's real public URL â€” `sitemap.ts`/`robots.ts` fall back to a
placeholder (`https://careeros.example.com`) otherwise, which is
fine for local development but must be overridden in production so
absolute URLs in the sitemap and canonical tags are correct.

## Deliberately not done in this version

- Per-organization/per-exam custom Open Graph images â€” every page
  currently uses the site default; a dedicated OG image generator is
  a reasonable V19.4+ addition, not attempted here to avoid adding a
  new image-generation dependency mid-scope.
- Full Lighthouse/axe accessibility audit â€” the accessibility items
  above are the concrete, verifiable additions made; a full audit
  needs a running instance to actually measure, which this session's
  no-network sandbox couldn't do (see `TEST_REPORT_V19_3.md`).

