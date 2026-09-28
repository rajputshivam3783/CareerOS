# V25.3 — Test & Verification Report

**Status: the implementation is complete; the verification is not.**

Same constraint as V25.2: the build environment for this version has
**no outbound network access**, so no dependency could be installed
and nothing requiring them could be executed.

---

## What could not be run, and why

| Check | Status | Blocker |
|---|---|---|
| Backend test suite (`pytest`) | **NOT VERIFIED** | `pip install -r requirements.txt` fails — no network. |
| New V25.3 tests (54) | **NOT VERIFIED** | Same. |
| V1–V25.2 regression suite | **NOT VERIFIED** | Same. |
| Frontend production build (`next build`) | **NOT VERIFIED** | `npm install` fails — no network. |
| TypeScript type-check / ESLint | **NOT VERIFIED** | Same. |
| OpenAPI schema generation | **NOT VERIFIED** | Requires importing the FastAPI app. |
| Migration applied against PostgreSQL | **NOT VERIFIED** | No database reachable. |
| A live AI provider call | **NOT VERIFIED** | No provider credentials in this sandbox; the fallback path is exercised by design (see below), the success path is not. |

---

## What was verified, and how

Given that tests could not run, verification for this version went
further than V25.2's did: rather than syntax-checking alone, every
model field, function signature, and column constraint that new code
*references* was checked against the actual source before being
trusted. This caught three real bugs before they would have surfaced
as runtime failures:

| Bug | Where | How it was caught | Fix |
|---|---|---|---|
| `resolve_many()`'s per-batch output dedup silently drops a second alias of an already-resolved skill (e.g. "Postgres" and "PostgreSQL" together) | `app/intelligence/skills.py` | Reading V20.5's `normalization.py` source in full rather than assuming its behaviour from its name | Build the lookup map once and resolve every name independently, bypassing `resolve_many`'s dedup |
| `scope_type="organization_intelligence"` (25 chars) against a `String(20)` column | `app/intelligence/ai.py`, reusing V24.4's `RecruiterAIInsight` cache table | Checking the actual column definition in `app/models/domain.py` before trusting a value would fit | Shortened to `"org_intelligence"` (16 chars); documented on the model |
| `user_id=0` passed as a fallback for admin-key callers, into a column (`AIUsageLog.user_id`) with a foreign key to `users.id` | `app/api/admin_intelligence.py` | Checking the FK constraint on the target column | Pass `None` through instead, which `generate()` already accepts |

A fourth issue was found and fixed while writing the tests themselves,
not the implementation: the test suite's own `_seed_job` helper
originally didn't account for `app.ingestion.services.deduplicate
.is_duplicate()`, which treats any two jobs sharing an
(organization, title) pair — case-insensitively, with no deadline — as
duplicates and silently returns the *first* matching job instead of
creating a second one. Since many tests deliberately seed several
distinct jobs under one shared title (to build a corpus "for that
role"), this would have silently collapsed most multi-job test
fixtures down to a single row without any test failing outright (the
corpus would just have been smaller than intended, and several
threshold-boundary assertions would have been trivially — and
wrongly — satisfied). Fixed by giving every seeded job its own
organization via a counter, and by writing the one test that
deliberately wants a true duplicate pair
(`test_data_quality_duplicate_jobs_detected`) to insert both rows
directly rather than through the ingest endpoint. A second test-only
bug — `_auth()`'s helper using `id(client)` for uniqueness, which
CPython can and does reuse across different `TestClient` instances in
different test functions, risking silent cross-test account
collisions — was also found and replaced with a monotonic counter.

Also performed:

| Check | Method | Result |
|---|---|---|
| Python syntax, every new and modified file | `ast.parse` | Pass |
| Undefined names / missing imports | Custom AST scanner (module + function scope) | Clean on every new/modified file, including after each fix |
| Route-path collisions across all `/admin` routers and the new `/career-intelligence`, `/market-intelligence`, `/organizations/{id}/intelligence*` routers | Manual enumeration against V9, V17.3, V25.1, V25.2 routers | None found |
| Every referenced ORM field (`Job`, `Profile`, `Resume`, `CareerPreference`, `Applicant`, `Organization`, `OrganizationMember`, `Skill`) | Read against `app/models/domain.py` | All present, correct types |
| `require_organization_membership` return shape | Read against `app/core/organizations.py` | Matches usage |
| `_generate_grounded` / cache signatures | Read against `app/recruiter_analytics/{ai,cache}.py` | Matches usage |
| V24.4 `overview()`/`funnel()` response shapes vs. frontend expectations | Read against `app/recruiter_analytics/service.py` | Frontend corrected to use `funnel.steps`, not `funnel.stages` |
| Rate-limit bucket mechanism | Read against `app/core/rate_limit.py` | Free-form bucket string, no registration needed — `"ai"` is a valid new bucket |
| Parameter ordering in routes mixing plain `Request` params with `Depends(...)` defaults | Manual check of every affected function signature | All valid (Request placed before any defaulted parameter) |

---

## How to verify this version

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest tests/test_v25_3_data_intelligence.py -v
for f in tests/test_*.py; do pytest "$f" -q || echo "FAILED: $f"; done

# Frontend
cd ../frontend
npm install
npx tsc --noEmit
npm run lint
npm run build
```

Against PostgreSQL:

```bash
cd backend
python -m scripts.run_migrations
```

---

## What the new tests assert (54 tests)

- **Corpus/skills engine (3)** — document-frequency counting (not
  occurrence counting); the Postgres/PostgreSQL alias-batch bug
  specifically, as a named regression test; unrecognized skill names
  reported rather than dropped.
- **Career intelligence (9)** — explainable coverage formula; no
  opaque score anywhere in the payload; target-role resolution
  priority (explicit > preference > profile > none); "no target role"
  offers choices rather than picking one; insufficient-data on a tiny
  role corpus; missing-skills arithmetic verified by hand; interview
  conversion suppressed below threshold with raw counts still shown;
  structural absence of any identity parameter; protected
  characteristics absent from every response.
- **Market intelligence (9)** — scope label correctness; skill-demand
  coverage reporting; description text never scanned for skills;
  trend insufficient-data and trend-with-direction cases; salary
  reported as disclosure, never as analytics, with no
  median/average anywhere in the payload; location intelligence never
  reports a candidate location; small location groups suppressed.
- **Organization intelligence (7)** — V24.4 reuse verified by
  response shape; tenant isolation (404, not 403, for a non-member);
  manipulated organization id rejected; deterministic difficult-to-fill
  with disclosed reasons; candidate-pool gaps suppressed below the
  privacy floor and, separately, verified to identify no candidate
  even when not suppressed; AI insights endpoint smoke-tested for
  graceful degradation.
- **Admin intelligence (3)** — permission gating; extension (not
  duplication) of V25.2's dashboard, verified by checking
  `platform_counts` and `computed_by`; candidate activity is
  counts-only.
- **Data quality (11)** — five specific rule detections (missing
  title, invalid URL, stale-in-review, plus pagination and an
  unknown-rule 404); the core guarantee that triage never modifies
  the inspected row, verified byte-for-byte; triage is audited;
  permission gating; clean rules stay listed at zero rather than
  disappearing; duplicate-job-group detection (seeded directly, since
  ingestion's own dedup prevents creating the pair through the API).
- **AI grounding and fallback (4)** — graceful degradation with no
  provider configured; no fabrication when the underlying analysis is
  itself insufficient; respects the `ai_features_enabled` platform
  switch; fact-builders verified directly (not just through the API)
  to exclude descriptions/notes/resumes and to truncate an
  adversarial job title to inert, correctly-sized data.
- **Privacy (5)** — cross-candidate isolation; unauthorized AI insight
  request; confirmation that no export endpoint was added (so there's
  nothing new to misauthorize); no sensitive data in market
  intelligence; structural confirmation that exactly one new table was
  added and it is administrator triage state, not user behaviour.
- **Regression (5)** — V25.2 admin governance, V25.1 organizations,
  V24.4 recruiter analytics, V20.5 skill intelligence, and core
  candidate/recruiter flows.

A test that has not been executed proves nothing; the above describes
intent, checked as carefully as source-reading allows, not evidence.

---

## Known risks given the lack of execution

1. **SQLite-vs-PostgreSQL date handling in trend queries.**
   `corpus.densify()` handles both the string form SQLite's
   `cast(..., Date)` returns and the native `date` object PostgreSQL
   returns, but this branch is unexecuted on either backend.
2. **`is_duplicate()` interaction with test fixtures**, beyond what was
   already caught and fixed (see above) — the fix (unique organization
   per seeded job) is reasoned through carefully but not run.
3. **Threshold-boundary arithmetic** (`>=` vs `>` at exactly N
   observations) in `thresholds.py` and `market.py`'s trend comparison
   — logic was read multiple times but not exercised.
4. **Frontend `any`-typed API responses** — written without `tsc`;
   the two response-shape mismatches already caught (V24.4 funnel
   `steps` vs. a guessed `stages`) suggest there may be others not yet
   found.
5. **The AI success path** (an actual provider call succeeding and
   producing valid JSON matching `{"summary": ..., "points": [...]}`)
   is not exercised in this sandbox at all — only the failure/fallback
   path is naturally exercised, since no provider is configured.
