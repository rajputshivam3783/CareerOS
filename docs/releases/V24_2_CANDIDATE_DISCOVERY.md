# V24.2 — Advanced Candidate Discovery & Search

## Summary

A recruiter-side candidate search and matching layer, built entirely
on existing tables and engines. No second search engine, no second
recommendation engine, no duplicated `users`/`profiles`/`resumes`/
`jobs`/`applications` table. The only schema change is one privacy
opt-in flag that genuinely didn't exist before this version.

## Candidate privacy model (the most important part)

A recruiter can discover exactly two kinds of candidate, enforced
entirely server-side in `_authorized_candidate_ids`
(`app/api/recruiter_candidates.py`) — never inferred from
`recruiter_id`/`company_id` supplied by the frontend:

1. **Applied** — the candidate has an `Applicant` row for a job owned
   by this recruiter's team (`team_owner_ids`, the same V18.6
   team-shared ownership every other recruiter endpoint already uses).
2. **Opted in** — `Profile.candidate_searchable == True` (new column,
   default **False**). A candidate who has never touched this setting,
   or explicitly left it off, is invisible to `GET /recruiter/candidates`
   and `GET /recruiter/candidates/{id}` for every recruiter they
   haven't applied to — full stop.

There is no third path and no public candidate directory. A candidate
who has neither applied to a given recruiter's jobs nor opted in does
not appear in that recruiter's results, is not returned by the detail
endpoint (404, not filtered client-side), and cannot be discovered by
guessing an id (see "Security" below).

The opt-in is a single boolean on the candidate's own profile
(`PUT /api/v1/profile`, `candidate_searchable`), exposed as a checkbox
on the existing candidate dashboard profile form. It changes *only*
visibility for recruiter discovery — it does not change anything about
applying to jobs, being found by admins, or any other existing
behavior.

## What already existed (reused, not touched)

| Need | Reused from |
|---|---|
| Skill normalization / catalog matching | `app.search.normalization.normalize_skills` → `app.skill_intelligence.normalization.resolve_many` (V20.5 catalog — exact name/alias match only, so "Java" and "JavaScript" are always distinct) |
| Location/text normalization | `app.search.normalization` (V21.1) |
| Candidate feature extraction | `app.recommendations.candidate_features.build` (V21.3) |
| Job feature extraction | `app.recommendations.job_features.build` (V21.3) |
| Deterministic, explainable matching | `app.recommendations.matching.compute` (V21.3/21.4) |
| Recruiter auth/ownership | `require_recruiter`, `team_owner_ids`, the same pattern every V9/V16/V18.x/V24.1 recruiter endpoint uses |
| Resume access | `Resume.extracted_text`/`skills_detected` — the same fields `GET /recruiter/applicants/{id}` already returns; there is no raw file-storage path anywhere in this schema to accidentally expose |
| "Shortlist" | the existing `PATCH /recruiter/applicants/{id}/stage` (V16/V18.2) |
| "Recently active" sort | `UserSession.last_seen_at` (V17.1) |

Nothing above was copied or forked — the API calls the same functions
the rest of the codebase calls.

## What's new

### 1. `Profile.candidate_searchable` (new column, additive)

Nullable-free boolean, `DEFAULT false`. See `migrations/
v24_2_candidate_discovery.sql`. Indexed, since every discovery query
filters on it.

### 2. `GET /recruiter/candidates`

The main search/browse endpoint (also covers the separately-listed
"search" endpoint from the spec — one route with a `q` param, not a
duplicate, same call as V24.1's job-list enrichment).

Query params: `q`, `skills` (repeatable) + `skills_mode` (`any`/`all`),
`min_experience_years`/`max_experience_years`, `location`, `education`,
`application_status`, `resume_available`, `min_profile_completeness`,
`sort_by` (allow-listed: `profile_completeness` | `experience` |
`recently_active` | `name`), `sort_dir`, `page`/`page_size` (max 50).

**Never a full-table scan.** The very first thing this endpoint does
is resolve the authorized pool (bounded by this recruiter's own
applicants + however many candidates have opted in platform-wide —
never "every user"). Every filter after that runs over that bounded,
already-loaded set. For the realistic scale of a recruiter's own
applicant pool plus an opted-in candidate pool, this is a handful of
queries per request (users/profiles/career-preferences/resumes/
sessions, each `WHERE id IN (...)` on the bounded id set), not N+1 —
see `_load_candidate_rows`.

Each result card returns only authorized fields (name, headline, top
skills, experience band, location, education, resume-on-file flag,
completeness score, this recruiter's own application(s) if any) —
**never the full resume text in a list response** (spec section 21's
"avoid loading complete resumes" — full `extracted_text` is only ever
returned by the single-row detail endpoint below).

### 3. `GET /recruiter/candidates/{id}`

Full authorized detail: everything the card has, plus full resume
text (if on file), preferred roles/locations, career goal. Logs
`view_candidate_profile` (and `access_candidate_resume` if a resume is
returned) via the existing `app.core.audit.log_audit` — no second
audit system. Never returns password/auth fields, an exact address
(there is no address field anywhere in this schema — `Profile.location`
is already city/region-level free text), or another recruiter's
`ApplicantNote` rows (notes aren't part of this endpoint's payload at
all; they stay behind the existing, unchanged
`GET /recruiter/applicants/{id}`).

### 4. `GET /recruiter/jobs/{id}/candidate-matches`

"Find candidates for this job." Builds `JobFeatures` for the job and,
for every candidate in that job's authorized pool (its own applicants
+ the opted-in pool), calls the *same* `app.recommendations.matching.
compute()` the candidate-facing job recommender already uses in the
reverse direction — then narrows the resulting 10-component
`MatchResult` down to the four that make sense for a recruiter judging
a candidate (skill, experience, education, location), plus a new,
small `title` component (candidate's target/preferred role vs. the
job title — the one signal `MatchResult` didn't already have). Career
goal/work mode/salary/recency/behavior/deadline-urgency are excluded —
a recruiter doesn't care how recently the job was posted.

Weight redistribution mirrors `app.recommendations.scoring`'s own
rule: an unavailable component's weight goes to the available ones,
never to zero. `match_reasons` are built directly from each
component's own `reason` string — nothing here is a fabricated
sentence.

**Safety cap:** `MAX_CANDIDATES_TO_SCORE = 300`. If a job's authorized
pool (mostly driven by the platform-wide opted-in count, since a
single job's own applicant count is naturally small) exceeds this, the
response sets `"truncated": true` and only the first 300 (by id) are
scored — a defensive ceiling, not something expected to trigger at
this project's realistic scale, but present so one request can never
turn into an unbounded scoring pass.

### 5. `POST /recruiter/candidate-search/parse`

Converts a natural-language query into the exact same filter shape
`GET /recruiter/candidates` accepts. **Deterministic only — no LLM
call in this version.** See "AI usage" below for why that's a
documented decision, not an oversight.

- Experience: a `\d+\+?\s*years?` regex.
- Location: a `(?:in|near|at|from)\s+<Capitalized words>` heuristic.
- Skills: 1–3 word sliding windows over the query resolved against the
  real Skill catalog (`resolve_many` — exact name/alias match, the
  same one everywhere else in this codebase), longest match wins so
  "Spring Boot" isn't also reported as a spurious "Spring".

Returns `{parsed, filters, fallback_q, note}` — `fallback_q` is set
whenever nothing could be confidently extracted, so the caller always
has a safe path (pass the raw text back as `q`). **This endpoint never
builds or executes SQL from the input** — its only output is a small,
fixed JSON object; the caller passes that, unchanged, into the same
validated/allow-listed query parameters `GET /recruiter/candidates`
already enforces. A `'; DROP TABLE users; --`-style query is inert:
nothing here treats the raw string as anything but text to run three
regexes and a catalog lookup over.

## Experience filtering — the honest derivation (spec section 6)

There is **no numeric years-of-experience field anywhere in this
schema** — not on `Profile`, not on `CareerPreference`, not derived
from `Resume` (its `experience_entries` are raw bullet-point strings
with no parsed dates). The only structured signal is
`CareerPreference.experience_level`, a self-reported band: `entry` /
`mid` / `senior` / `lead`. `min_experience_years`/
`max_experience_years` are honestly mapped onto approximate band
boundaries (entry 0–2, mid 2–5, senior 5–10, lead 10–40) rather than
compared against a per-candidate number that doesn't exist. A
candidate with no `experience_level` set is **excluded** from a
numeric-experience filter, never guessed into a band.

## AI usage (spec sections 23–24)

Candidate discovery works completely without AI — every endpoint
above is deterministic. The natural-language parser
(`/candidate-search/parse`) is also deterministic in this version: no
LLM call is made. This is a **documented scope decision**, not a
half-finished feature pretending otherwise: the spec's actual
requirement ("must work without AI... AI may *optionally* assist") is
satisfied by the deterministic path existing and working end to end.
Wiring the optional AI-assisted enhancement on top of it — validating
LLM output against the same strict filter schema before use, per
section 24's "never allow an LLM to generate SQL" — was not attempted
in this pass so it isn't shipped half-tested; it's a clearly-labeled
next step, not a silent gap.

## Security review performed (manual/static — see "Tests" for what
actually ran)

- **IDOR** — `candidate_detail` checks `candidate_id in
  _authorized_candidate_ids(...)` before loading anything, and returns
  404 (not 403) for an unauthorized id, so a recruiter can't
  distinguish "not yours" from "doesn't exist" — same posture as
  V24.1's job 404s. `job_candidate_matches` re-derives job ownership
  via `Job.owner_user_id.in_(team_owner_ids(...))` before doing
  anything with the job id.
- **Cross-recruiter / cross-company access** — every query in this
  module is scoped through `team_owner_ids(db, recruiter)`, the exact
  function every pre-existing recruiter endpoint uses; there is no
  parallel, looser ownership check introduced here.
- **Mass assignment** — `NaturalLanguageParseIn` only accepts `query`;
  the candidate-facing `candidate_searchable` opt-in is a plain
  boolean field on the pre-existing, already-allow-listed `ProfileIn`.
- **SQL injection / unsafe filters** — every query is built with
  SQLAlchemy's parameterized `select()`/`where()`; `sort_by` is
  constrained by a FastAPI `Query(pattern=...)` allow-list, not an
  arbitrary column name, so a value like `users.password_hash` is
  rejected at the request-validation layer (422) before any query
  logic runs.
- **Private field exposure** — see "What's new" #2/#3 above for
  exactly what is and isn't returned; nothing here returns password
  hashes, auth tokens, another recruiter's notes, or an address field
  (none exists).
- **Prompt/NL-injection** — the parser has no AI call to inject a
  prompt into; a malicious string can only ever produce the same
  `{skills, min_experience_years, location}` shape or an empty one
  with `fallback_q` set.

## Database

- `migrations/v24_2_candidate_discovery.sql` — `ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS candidate_searchable BOOLEAN NOT NULL
  DEFAULT false;` + an index. Safe to re-run. No historical migration
  touched.
- SQLite dev/test path creates the column/index automatically from the
  updated `Profile` model.

## API

New, all under `/api/v1/recruiter`:

| Method | Path |
|---|---|
| GET | `/candidates` |
| GET | `/candidates/{id}` |
| GET | `/jobs/{id}/candidate-matches` |
| POST | `/candidate-search/parse` |

`GET /recruiter/candidates/search` from the spec's own "possible
endpoints" list was not created separately — folded into
`GET /recruiter/candidates` via `q`, per the "only create routes that
do not already exist [in spirit]" instruction and the same reasoning
V24.1 used for job enrichment.

## Tests

`backend/tests/test_v24_2_candidate_discovery.py` — 10 new tests:
visibility (applied / opted-in / neither), skill filter Java-vs-
JavaScript disambiguation, skill AND vs. OR logic, location filtering,
sort-field allow-list rejection (unsafe-filter protection),
cross-recruiter isolation on both list and detail (IDOR), job-specific
match scoring/explanation, job-candidate-matches ownership isolation,
NL-parser correctness on a realistic query plus a SQL-injection-style
query never producing anything but the same safe JSON shape, and a
role check (a candidate account cannot call the recruiter search
endpoint).

## PASS / FAIL / NOT VERIFIED

| Check | Result |
|---|---|
| `python -m py_compile` / `ast.parse` on every changed/added Python file | **PASS** — ran in this sandbox |
| Isolated `tsc` structural check on every new/changed frontend file | **PASS** — no syntax errors; only "missing type declarations" noise expected from having no `node_modules` in this sandbox |
| New backend tests (10) | **NOT VERIFIED** — same sandbox limitation as V24.1: no outbound network access, so `pip install fastapi`/etc. fails and the suite cannot be executed here. Written to the existing `pytest`/`TestClient` pattern (`test_v16b_recruiter_ats.py`, `test_v24_1_recruiter_workspace.py`); needs a real environment to run. |
| Full existing backend suite (regression) | **NOT VERIFIED** — same reason. Every change in this version is additive (new file, new column, one new field on an existing, already-permissive `ProfileIn`) — no existing function's signature or behavior was altered, so no regression is *expected*, but that's not the same as a passing run. |
| Frontend build / type-check / lint | **NOT VERIFIED** — same sandbox limitation (no `npm install`). |
| Manual security review | **PASS** (manual/static) — see "Security review performed" above. |
| Migration validity | **PASS** (manual review) — same `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` / index pattern as every other additive migration in this repo. |

## Known limitations

- **Natural-language parsing has no AI-assisted path yet** — fully
  deterministic in this version (see "AI usage" above). Recognizes
  only skills already in the Skill catalog, a `<number> years`
  pattern, and a simple `in/near/at/from <Capitalized words>` location
  heuristic — it will miss anything phrased differently, and that's
  fine because the deterministic filters remain usable directly and
  `fallback_q` always gives the caller a safe way to retry as a plain
  keyword search.
- **Experience filtering is band-based, not numeric** — see
  "Experience filtering" above; this is a direct consequence of no
  numeric years-of-experience field existing anywhere in the schema,
  not a shortcut taken for this version.
- **`job_candidate_matches` has a hard 300-candidate scoring cap** —
  documented above; only matters if the platform-wide opted-in pool
  becomes very large.
- **The opted-in candidate pool is genuinely global** — any approved
  recruiter can discover any candidate who has opted in, regardless of
  whether that candidate has ever heard of that recruiter's company.
  This is what "opt in to recruiter discovery" means as specified
  (section 16's "candidates otherwise explicitly made discoverable");
  it is not scoped to "discoverable by recruiters at companies I've
  applied to."
- **Tests were not executed** (see table above) — code-review-complete,
  not deployment-verified, until run in a real environment.
- Advanced pipeline actions beyond a minimal "Shortlist" (Reject, full
  stage transitions for opted-in-but-not-applied candidates) are
  explicitly out of scope, per the spec's own "prepare the
  architecture, don't build the full pipeline" instruction for V24.3.

## Files changed

- `backend/app/models/domain.py` — `Profile.candidate_searchable`.
- `backend/migrations/v24_2_candidate_discovery.sql` — new.
- `backend/app/api/recruiter_candidates.py` — new (all V24.2 endpoints).
- `backend/app/api/platform.py` — `ProfileIn.candidate_searchable`.
- `backend/app/api/routes.py` — router registration.
- `backend/tests/test_v24_2_candidate_discovery.py` — new.
- `frontend/src/app/dashboard/page.tsx` — opt-in checkbox.
- `frontend/src/app/recruiter/candidates/page.tsx`,
  `CandidatesClient.tsx`, `[id]/page.tsx` — new.
- `frontend/src/app/recruiter/jobs/page.tsx`,
  `frontend/src/app/recruiter/page.tsx` — "Find candidates" links.
- `CHANGELOG.md`, `README.md` — version entries.
