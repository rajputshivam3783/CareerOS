# CareerOS — Known Limitations

The authoritative, maintained list is the **"What's deliberately not
claimed as done"** section of [`PROJECT_STATUS.md`](./PROJECT_STATUS.md#whats-deliberately-not-claimed-as-done).
Keeping one copy there (rather than a duplicate here that can drift
out of sync) covers:

- Live automated scraping of specific government/private sites — the
  framework exists, no source ships pre-verified against today's live
  markup
- No AI-generated exam content (syllabus/papers/mock tests are
  admin-curated links only)
- Email delivery requires SMTP to be configured; no SMS/WhatsApp/push
  channel exists
- RBAC permission layer exists but isn't wired into every route yet
- Scholarship/internship/fellowship sections have no admin write path
- No verified load-test result
- **This V19.5 pass's own changes were not verified by running the
  real test suite or build** — the environment had no network access
  to install dependencies. See `TEST_REPORT.md` for exactly what was
  and wasn't checked, and the release-gate steps required before
  deployment.

For per-version detail on any of the above, see `docs/archive/`.
