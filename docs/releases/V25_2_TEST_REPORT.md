# V25.2 — Test & Verification Report

**Status: the implementation is complete; the verification is not.**

This report exists because the honest answer to "did the tests pass?"
is "they were never run." The build environment for this version had
**no outbound network access**, so no dependency could be installed and
nothing that requires dependencies could be executed.

---

## What could not be run, and why

| Check | Status | Blocker |
|---|---|---|
| Backend test suite (`pytest`) | **NOT VERIFIED** | `pip install -r requirements.txt` fails — no network. FastAPI, SQLAlchemy, pytest and the rest are not importable in this sandbox. |
| New V25.2 tests (~55) | **NOT VERIFIED** | Same. |
| V1–V25.1 regression suite (~711 tests) | **NOT VERIFIED** | Same. |
| Frontend production build (`next build`) | **NOT VERIFIED** | `npm install` fails — no network. `frontend/node_modules` is absent. |
| TypeScript type-check (`tsc --noEmit`) | **NOT VERIFIED** | Same. |
| ESLint (`next lint`) | **NOT VERIFIED** | Same. |
| OpenAPI schema generation | **NOT VERIFIED** | Requires importing the FastAPI app. |
| Migration applied against PostgreSQL | **NOT VERIFIED** | No database reachable. |

**These are reported as NOT VERIFIED, not as passing.** Do not treat
this version as validated until the checks below are run in an
environment that has network access.

---

## What *was* verified

| Check | Method | Result |
|---|---|---|
| Python syntax, every new and modified file | `ast.parse` on each file | Pass |
| Undefined names (typos, missing imports) | Custom AST scanner over module and function scopes | Clean — no undefined name in any new or modified backend file |
| Route-path collisions across the four routers mounted at `/admin` | Manual enumeration of `app/api/admin.py`, `admin_rbac.py`, `search.py`'s admin router and the new `admin_platform.py` | Two overlaps found, both resolved deliberately — see below |
| Existing callers of changed routes | `grep` across `backend/tests/` and `frontend/src/` | One found (`tests/test_v21_1_unified_search.py:270` posts to `/admin/jobs/{id}/reject` with no body); the new body was made optional so that call still works |
| ORM column existence for every field referenced by new code | Read against `app/models/domain.py` | All present |
| SQL migration vs. ORM model parity | Manual field-by-field comparison | Consistent |

The undefined-name scanner is not a substitute for a real linter. It
catches typos and missing imports; it does not catch type errors,
wrong argument counts across modules, or runtime behaviour.

---

## Route collisions found and how each was handled

1. **`GET /admin/users`** — existed in `app/api/admin.py` (V9,
   unpaginated, top 200). With both routers mounted at `/admin`,
   FastAPI would silently serve whichever was registered first. The V9
   handler was **removed** and the path now has exactly one owner, in
   `admin_platform.py`, with search/filters/pagination. Every field the
   old response contained is still present on each result. No test or
   frontend file consumed it.

2. **`POST /admin/jobs/{job_id}/reject`** — existed in
   `app/api/admin.py` and is called **body-less** by
   `tests/test_v21_1_unified_search.py`. Rather than adding a second
   route on a new path, the existing route gained an **optional**
   Pydantic body defaulting to `reason="other"`. The body-less call is
   unaffected.

No other path in the new router overlaps an existing one.
`/admin/search` is free (`/admin/search/reindex` and
`/admin/search/index-health` exist and do not conflict).

---

## How to verify this version

From the repository root, in an environment with network access:

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate
pip install -r requirements.txt

# The new suite
pytest tests/test_v25_2_admin_platform_governance.py -v

# Full regression. NOTE: run per-file. V23.5 documented that a
# module-level engine singleton means only the first test file's
# DATABASE_URL is honoured in a combined run — a test-harness
# limitation, not a production issue.
for f in tests/test_*.py; do pytest "$f" -q || echo "FAILED: $f"; done

# Frontend
cd ../frontend
npm install
npx tsc --noEmit
npm run lint
npm run build
```

Then, against a PostgreSQL deployment:

```bash
cd backend
python -m scripts.run_migrations
```

---

## What the new tests assert

~55 tests in
`backend/tests/test_v25_2_admin_platform_governance.py`, grouped:

- **Authorization (8)** — candidate, recruiter and organization OWNER
  receive 403 on every admin read and write; unauthenticated and
  wrong-key receive 401; privilege-escalation attempts are logged
  without credentials; a real platform admin gets through.
- **Dashboard (2)** — counts move with real data; omissions are
  declared.
- **Users (7)** — search/filter/pagination; no sensitive field in any
  response; suspension blocks auth and preserves records; reactivation
  restores access; organization membership survives suspension;
  self-suspension refused; invalid reason refused; IDOR returns 404.
- **Organizations (4)** — list/detail counts; suspension unpublishes
  jobs, blocks members, leaks no reason, deletes nothing; reactivation
  restores *exactly* the jobs it suspended and not an individually
  moderated one; applications preserved.
- **Jobs (5)** — full approve/suspend/restore cycle; double-suspend
  refused; legacy body-less reject still works; structured reject
  works; internal note absent from the public endpoint; filters;
  restore never auto-publishes.
- **Audit (4)** — every action writes a record with reason/result/
  actor; filters and per-resource history; no edit/delete route exists
  and the row survives attempts; metadata sanitization drops
  secret-ish keys and summarizes long lists.
- **Search (2)** — cross-entity results, permission-scoped;
  injection-shaped input is harmless.
- **Analytics (2)** — dense zero-filled series, range cap; no
  candidate identity, no application content, no demographic term
  anywhere in the payload.
- **System health (4)** — real indicators, no secrets, driver family
  only; unconfigured providers report `unknown` not `ok`; background
  jobs and ingestion report only real state; no arbitrary-job
  execution route exists.
- **Settings & maintenance (5)** — typed validation, unknown key 404,
  bounds enforced, change audited, registration closable; maintenance
  blocks users but never admins, health probes or login.
- **Announcements (3)** — creation delivers nothing, send is a
  separate step, re-send refused, email off unless enabled, send
  audited.
- **Bulk (2)** — partial failure reported, per-item plus summary
  audit, size cap enforced, no delete route.
- **Regression (4)** — V25.1 organization invite/accept flow;
  cross-tenant isolation still 404s and is now logged; legacy admin
  routes (`/stats`, `/review`, `/audit-logs`, `/recruiters/pending`,
  `/jobs/{id}/publish`) unchanged; candidate core flows unaffected.

A test that has not been executed proves nothing. The list above
describes intent, not evidence.

---

## Known risks given the lack of execution

Ranked by how likely they are to bite on first run:

1. **Test-fixture mismatches.** The tests were written against the
   routes and schemas as read from source. Small mismatches in request
   payload shape or status code are plausible and would surface
   immediately as test failures rather than as production bugs.
2. **Frontend type errors.** The admin pages were written without
   `tsc`. Type errors in the `any`-typed API responses are possible.
3. **SQLAlchemy query construction.** The analytics aggregations
   (multi-table joins, `cast(column, Date)` bucketing) are the most
   likely place for a runtime SQL error, and SQLite and PostgreSQL
   differ in date-cast behaviour. `_dense_series` handles both the
   string form SQLite returns and the `date` form PostgreSQL returns,
   but this is unexecuted.
4. **Middleware ordering.** The maintenance middleware is registered
   after the request-context middleware, which should place it inside
   it. Unverified at runtime.
5. **Migration on PostgreSQL.** The SQL is written in the same style
   as every prior migration in this project, but has not been applied.
