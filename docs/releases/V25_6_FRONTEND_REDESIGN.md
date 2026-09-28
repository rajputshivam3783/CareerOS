# V25.6 — frontend visual redesign

A production-quality visual pass over the whole app. No backend files touched; no route,
component prop, or API contract changed — this is styling, typography and copy only.
Verified after the change: `python -m pytest` (backend) -> 1025 passed, 0 failed;
`npm run build` and `npm run test:security` (frontend) both pass.

## Design direction
CareerOS's job is verified opportunities (government + private), so the identity leans into
that: a civic-registry look rather than a generic SaaS-blue template.
- **Color**: deep navy ink (`#0f1b30`) on a cool paper background (`#f5f7fb`, not the
  cliché warm cream), a confident signal blue (`#2451e6`) for actions, and a brass "seal"
  accent (`#8a6014`) reserved only for verification/trust cues — never decorative.
- **Type**: Archivo (variable, self-hosted via fontsource) for headlines, Public Sans
  (also self-hosted) for body/UI — Public Sans is the U.S. government's own interface
  typeface, a deliberate fit for a jobs + government-exams product.
- **Motion**: one orchestrated hero entrance on the homepage, nothing else animates;
  `prefers-reduced-motion` is respected.

## What changed
- `src/app/globals.css`: full rewrite. Every one of the 156 class names the app already
  used (`.card`, `.btn`, `.field`, `.chip`, `.badge-*`, ...) was restyled in place with the
  new tokens, so the redesign reaches every page without editing each one individually.
  Refined shadows, radii, focus rings, and a `[data-theme="dark"]` palette.
- `src/components/Nav.tsx`: the flat wall of ~15 links is now grouped — a "Workspace"
  menu for candidate tools, an "Admin" menu for admin tools — using native
  `<details>/<summary>` (no extra JS).
- `src/app/page.tsx`, `src/app/layout.tsx`: homepage hero and footer rewritten with real
  copy (no invented stats), sentence-case labels, and the numbered "01/02/03" marker
  removed from the three feature cards (they're categories, not a sequence).
- 46 files: every hardcoded ALL-CAPS "eyebrow" label (`OPPORTUNITY ENGINE`, `CAREEROS ·
  GOVERNMENT PORTAL`, ...) converted to sentence case with acronyms (AI, LLM, UPSC, OS)
  and the CareerOS brand name preserved — all-caps tracked-out labels are a well-known
  generated-page tell.
- ~20 hardcoded hex colors scattered across page files replaced with the new CSS
  variables, so score bars, chat bubbles and progress tracks stay correct in dark mode.
- Login/admin-login buttons: "Login" -> "Log in" (a CTA names the action it performs).
- Installed `@fontsource-variable/archivo` and `@fontsource-variable/public-sans`
  (self-hosted, no external font requests at runtime).

## Verified visually
Built the app, served it, and screenshotted the homepage (light + dark + mobile), jobs
search, government hub and candidate login with a headless Chromium fetched via npm
(`@sparticuz/chromium` + `puppeteer-core`) — not part of the shipped app, used only to
review the redesign during this change.
