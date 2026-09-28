# V25.3 — Data Intelligence, Career & Market Analytics

This version adds an analytics and intelligence layer over CareerOS's
existing data: candidate career intelligence, platform-derived job
market intelligence, organization hiring intelligence, admin platform
intelligence, and data-quality monitoring — plus a thin AI layer that
explains those numbers in plain language without ever calculating one
itself.

Two rules shape every decision in this version, and are worth stating
before anything else:

1. **Deterministic calculation is the source of truth.** Every number
   any endpoint returns is a `COUNT`, a ratio of two counts, or date
   arithmetic over rows that exist. AI receives numbers already
   computed and may only phrase them.
2. **Platform-derived, and labelled as such.** Everything measured here
   is CareerOS activity, not "the job market." CareerOS holds no
   external labour-market dataset, so nothing is described as one.

---

## 1. Architecture

```
CareerOS tables
    │
    ├─ app/intelligence/corpus.py    one filtered job/application corpus loader
    ├─ app/intelligence/skills.py    one skill aggregation engine
    ├─ app/intelligence/roles.py     one role → corpus resolver
    │
    ├─ candidate.py   ─┐
    ├─ market.py       ├─ five views over the same corpus/skills engine
    ├─ organization.py ├─ (organization.py itself is mostly a thin
    ├─ platform_intel.py┘  wrapper around V24.4's own service)
    │
    ├─ ai.py            explains; never calculates
    │
    └─ candidate / recruiter / organization / admin API routers
```

One analytics layer, five views, not five analytics implementations.
`app/intelligence/corpus.py` is the single place a job set is
assembled — skill frequency, role demand, location distribution,
trends, and organization skill demand are all "count something over a
filtered set of jobs," and every one of them gets that set from the
same function so there is exactly one definition of which jobs count
(published, matching whatever filters were given — see §2).

### Reuse over reimplementation

This is the load-bearing design decision in V25.3. Concretely:

| What | Reused from | Where |
|---|---|---|
| Skill canonicalization (alias resolution) | V20.5 `app.skill_intelligence.normalization` | `app/intelligence/skills.py` |
| Hiring funnel, time-in-stage, time-to-interview, offer conversion, stale candidates, job performance | V24.4 `app.recruiter_analytics.service` | `app/intelligence/organization.py` |
| AI generate → cache → parse → fairness-guard pipeline | V24.4 `app.recruiter_analytics.ai._generate_grounded` + the `RecruiterAIInsight` cache table | `app/intelligence/ai.py` |
| Platform user/organization/job counts | V25.2 `app.services.platform_analytics.dashboard_metrics` | `app/intelligence/platform_intel.py` |
| Sample-size thresholds | V25.2 typed platform settings | `app/intelligence/thresholds.py` |
| Tenant isolation | V25.1 `require_organization_membership` | `app/api/organization_intelligence.py` |
| Platform-admin authorization | V25.2 `require_platform_permission` | `app/api/admin_intelligence.py` |

None of the formulas in that left column were rewritten. Organization
hiring intelligence, specifically, is V24.4's service called with the
organization's own member ids — a CareerOS organization owns jobs
through `Job.owner_user_id ∈ member_ids`, the same relationship V24.x
and V25.2 already use, so "this organization's analytics" is
literally "these members' analytics, aggregated by the existing
engine."

---

## 2. The shared corpus (`app/intelligence/corpus.py`)

Every analytic in this version answers "count something over a
filtered set of jobs." `CorpusFilter` describes that filter (days,
role, location, category, job type, work mode, employment type,
organization scope, status), and `_clauses()` translates it into
parameterized SQLAlchemy `WHERE` clauses — never string-built SQL.

**Which jobs count, by default:** `status = 'published'` only. A job
in `review` has not been seen by a candidate; a `rejected` or
`suspended` one (V25.2) was removed for cause. Counting either as
market activity would report moderation backlog as demand. Admin
platform intelligence can request the unfiltered set explicitly,
because "how many jobs are stuck in review" is a legitimately
different question.

**Which date field:** `published_at`, not `created_at`. A listing
edited today but published three weeks ago belongs in a three-week
window, not today's.

**Cost control:** two access shapes. `aggregate_counts`/`daily_counts`
push work into SQL (`GROUP BY`, indexed `WHERE`) and return small
result sets — used for anything whose answer is a distribution.
`load_jobs` materializes rows, but only behind a hard 2,000-row cap
(`MAX_MATERIALIZED_JOBS`), and only for skill parsing, which has to
read the `jobs.skills` text column no database can usefully
`GROUP BY`. There is no code path that loads every job in the
database, and none that issues a query per job. Every response that
materializes a bounded sample says so (`corpus_truncated`) and reports
the true total from a separate `COUNT` alongside it.

---

## 3. Skill intelligence (`app/intelligence/skills.py`)

### Where skills come from

`jobs.skills` — the comma-separated list a recruiter entered, or an
ingestion adapter mapped. That is the *only* field read as a skill
requirement.

**Deliberately not used:** `description`, `requirements`,
`qualification`, `responsibilities`. Scanning prose for skill names
would let "no Java experience required" and "Java" count identically
as demand for Java. A keyword hit in a paragraph is not a stated
requirement, and inventing requirements is exactly what the spec
forbids. Verified by test
(`test_description_text_never_scanned_for_skills`).

The consequence is reported honestly: every skill response carries
`jobs_with_skill_data` / `skill_data_coverage_pct`, so a frequency
computed over 12 of 400 jobs says so rather than presenting itself as
a finding about 400 jobs.

### Normalization

Through `app.skill_intelligence.normalization`'s raw lookup map
(`_lookup_map`) — exact, case-insensitive matching against the curated
`skills`/`skill_aliases` catalog. "Postgres" and "PostgreSQL" merge
because the catalog's own alias table says so, not because this layer
guesses.

**A real bug found and fixed during implementation, worth documenting
here:** V20.5's `resolve_many()` dedupes its *output* by resolved
skill id within one call. If a batch of raw names contains two
different aliases of the same skill — "Postgres" on one job,
"PostgreSQL" on another, both present in the same corpus — only the
alphabetically-first is returned, and the second is silently dropped:
neither counted as that skill nor reported as unrecognized. That
behaviour is correct for `resolve_many`'s original one-job caller
(duplicate skills *on a single job* are genuinely redundant); it is
wrong for frequency counting *across many jobs*, where it would
silently undercount. `app/intelligence/skills.py` therefore builds the
lookup map once per corpus and resolves every job's raw names against
it independently, rather than calling `resolve_many`. Regression-tested
(`test_postgres_and_postgresql_alias_both_count_in_the_same_batch`).

Names the catalog does not recognize are **not discarded** — counted
separately as `unrecognized_skill_names`, and surfaced as a
data-quality signal (§9).

### Required vs. preferred

CareerOS has one `skills` column, no required/preferred split. No tier
is fabricated by guessing from word order or position; every skill
response returns `requirement_tiers_available: false` so the absence
is explicit.

### No opaque scores

Every ratio in this package — skill coverage, interview conversion,
profile completeness — carries its own `formula` string stating the
numerator, denominator, and what a match means, taken from the same
response. No "career score" of any kind is produced anywhere in
V25.3.

---

## 4. Candidate career intelligence (`app/intelligence/candidate.py`)

`GET /api/v1/career-intelligence/{overview,skills,relevant-skills,
skill-gaps,roles,roles/{role}}`, `POST /api/v1/career-intelligence/
ai-summary`.

**Authorization is structural, not just enforced:** no endpoint in
`app/api/career_intelligence.py` accepts a user id, candidate id, or
any other identity parameter. The candidate is always derived from
`Depends(current_user)`. There is no id for a caller to manipulate,
because the API provides no way to name one — verified by a test that
introspects every route's own parameter list
(`test_career_intelligence_has_no_identity_parameter`), not merely by
testing that a forged id is rejected.

### Target role resolution (spec §4)

In priority order, and never any other way:

1. An explicit `role` query parameter.
2. `CareerPreference.target_role` (the candidate's own V20.3 setting).
3. The first entry of `Profile.preferred_roles`.
4. None of the above → `status: "no_target_role"`, with a list of
   roles actually present on CareerOS offered as options. The
   candidate is never assigned a role.

Resolution priority is regression-tested end to end
(`test_target_role_resolution_priority_explicit_then_preference_then_profile`).

### Gap analysis (spec §5)

A skill counts as a "requirement" for a role when it appears on at
least 2 of the real published jobs matching that role's title — that
floor is stated in every response
(`requirement_definition`/`how_this_was_calculated`) so the
methodology is never hidden behind the numbers. Experience and
education requirements are reported as the **text these jobs actually
state**, with a frequency count — never a computed "you are N years
short," because CareerOS stores neither a structured candidate
experience total nor a structured job experience *number* to subtract.

### Interview conversion honesty

Reported only when the candidate's own application count clears
`intelligence_min_trend_observations`. Below that, the endpoint
returns `status: "insufficient_data"` with the raw counts still shown
— the counts are true; the rate is what would have been misleading
with four applications.

### Protected characteristics

`Profile.date_of_birth`, `reservation_category`, `is_pwd` exist for
the V5 eligibility engine. Nothing in this file reads any of the
three. Verified by test
(`test_career_intelligence_never_reveals_protected_characteristics`),
which seeds all three and asserts none appear in any response.

---

## 5. Market intelligence (`app/intelligence/market.py`)

`GET /api/v1/market-intelligence/{overview,skills,roles,trends,
locations,salary}`.

### The scope label is load-bearing

Every response carries `scope: "careeros_platform"`,
`scope_label: "CareerOS job-market activity"`, a `scope_note`
explaining the distinction, and `external_market_data_available:
false`. This is not a disclaimer bolted onto the response — it is why
the module is named for the platform rather than "the market," and
the AI prompt (§8) repeats the same instruction so a model summarizing
these numbers cannot upgrade "31 CareerOS listings" into "demand in
India."

### Trends (spec §7)

Two **equal, adjacent** periods, never a trailing window against "all
of history" (which would make every established skill look like it's
collapsing). Reported only when *both* periods individually clear
`intelligence_min_trend_observations`; a skill whose combined
observations still fall short is returned with `status:
"insufficient_data"` and `direction: null` rather than being dropped
from the list — a skill silently disappearing from a trend report
reads as "demand went to zero," which is a much stronger and more
misleading claim than "we don't know."

### Salary (spec §9) — disclosure, not analytics

`jobs.salary` is free text ("As per 7th CPC", "₹8-12 LPA",
"Negotiable") never validated on entry. **No salary distribution,
median, or salary-by-role/experience/location breakdown is produced.**
Building one would mean parsing arbitrary prose into numbers and
presenting the result as reliable — exactly the fabrication §9
prohibits. What `/market-intelligence/salary` reports instead is
**disclosure coverage**: how many listings state anything about pay
at all, and how many state a figure a conservative regex can read with
confidence — reported as a data-quality-shaped statistic, with
`salary_analytics_available: false` stated explicitly, never
aggregated into a "typical salary." Test:
`test_salary_is_disclosure_not_fabricated_analytics`.

### Location intelligence (spec §8)

Every figure is about **jobs**; no function in this module reads a
candidate's location, and no per-candidate location breakdown exists
anywhere in V25.3. Per-location rows are suppressed below
`intelligence_min_group_size` — "3 jobs in a town of 40,000" is an
aggregate in form and closer to identification in effect, so it's
withheld, and `suppressed_locations` reports how many rows were
withheld rather than silently truncating the list.

---

## 6. Organization hiring intelligence (`app/intelligence/organization.py`)

`GET /api/v1/organizations/{id}/intelligence[/hiring|/skill-demand|
/candidate-pool|/difficult-to-fill|/job-performance]`,
`POST /api/v1/organizations/{id}/ai-insights`.

### Tenant isolation

Every route depends on V25.1's `require_organization_membership`,
which is the single place in the codebase that answers "is this user
in this organization." A non-member gets **404**, identical to a
nonexistent organization — and, per V25.2, that dependency logs a
`cross_tenant_access_attempt` security event on the attempt. A
platform-suspended organization also fails this check, because
suspension flips the same `is_active` flag the dependency already
tests. `organization_id` in the path is authorized *before* it is used
to derive member ids inside the service layer — it is never trusted on
its own. Tested directly:
`test_organization_tenant_isolation_on_intelligence`,
`test_manipulated_organization_id_rejected`.

### What's genuinely new here (vs. V24.4)

- **Skill demand** — the same skill engine as §3, scoped to this
  organization's own jobs.
- **Candidate-pool skill gaps** — where this organization's *own
  applicant pool* (not the platform's candidate population) falls
  short of what its own listings ask for. Suppressed entirely below
  `intelligence_min_group_size`; aggregate counts only, and no
  candidate is ever named (tested:
  `test_candidate_pool_gaps_no_candidate_identified`,
  `test_candidate_pool_gaps_suppressed_below_privacy_floor`).
- **Difficult-to-fill** — a fixed, disclosed rule, not an AI judgement:
  a published job flagged when it has been open ≥30 days **and**
  either has fewer than 5 applications, or ≥70% of its applicants are
  still at the earliest pipeline stage. Every flagged row returns the
  exact numbers that triggered it (`test_difficult_to_fill_has_deterministic_reasons`).

---

## 7. Admin platform intelligence (`app/intelligence/platform_intel.py`)

`GET /api/v1/admin/intelligence[/skills|/trends]`,
`POST /api/v1/admin/intelligence/ai-summary`. Gated on V25.2's
`PLATFORM_ANALYTICS` permission — an organization OWNER/ADMIN gets 403
here exactly as on every other admin route (V25.2's separation
extends unchanged; no exception was added).

`overview()` calls V25.2's `dashboard_metrics()` unmodified under
`platform_counts`, and adds the content dimensions V25.2 had no notion
of: category/skill/role distributions, per-organization job and
application volume (one grouped query, not one per organization),
candidate participation as **counts only**, and ingestion activity
summed from real `IngestionRun` rows.

---

## 8. The AI insight layer (`app/intelligence/ai.py`)

### AI is not the analytics engine (spec §19)

Every number in a V25.3 response is computed in `candidate.py`,
`market.py`, `organization.py`, or `platform_intel.py`. This module
hands those already-computed numbers to a model and asks it to phrase
them — never to count, rank, forecast, or decide. No figure a user
sees anywhere in V25.3 originates in a model response; the
deterministic payload is always returned alongside the narrative, from
the same endpoint (`{"analysis": ..., "ai": ...}`), so the two can be
compared directly.

### Reused, not reimplemented

The generate → cache → parse → fairness-guard pipeline is V24.4's
`_generate_grounded`, called directly with new prompts and fact
builders. This gives V25.3, for free:

- **Content-hash caching** on the exact facts that went into the
  prompt (`RecruiterAIInsight`, the same table V24.4 uses — see the
  model's own docstring, extended in this version to document the
  reuse and a column-length note below).
- **Graceful degradation** — a provider outage or no configured
  provider returns `{"degraded": true, "summary": "..."}` rather than
  failing the request. Tested directly:
  `test_career_ai_summary_falls_back_gracefully_without_a_provider`.
- The **fairness/protected-attribute guard**, which fires on the
  model's own output.
- Respect for the V25.2 `ai_features_enabled` platform switch — when
  off, every V25.3 AI endpoint returns the same degraded shape rather
  than attempting a call. Tested:
  `test_ai_disabled_by_platform_setting_returns_unavailable`.

**A column-length bug found and fixed during implementation:** the
natural scope-type name for organization insights,
`"organization_intelligence"`, is 25 characters against the reused
table's `scope_type` column, which is `String(20)`. SQLite would have
tolerated it silently; PostgreSQL would reject the insert. Shortened
to `"org_intelligence"` (16 chars) and documented on the model itself
so a future caller does not repeat the mistake.

### Prompt injection

Fact blocks are built from **already-computed values**: normalized
skill names, counts, percentages, dates, stage names. No job
description, resume text, cover note, recruiter note, or free-text
candidate/organization field is ever placed in a fact block. Job
*titles* are the one user-authored string admitted (market and
organization prompts only) — truncated to 120 characters, delivered as
JSON data with the system prompt stating explicitly that the block is
data, never instructions. Tested with an adversarial title
(`"IGNORE ALL PREVIOUS INSTRUCTIONS..." * 10`) confirming it is
truncated and passed through inertly rather than specially handled
(`test_ai_facts_never_include_job_description_or_cover_note`).

### Scope-appropriate rules

Every prompt carries the shared grounding/fairness/no-calculation/
data-not-instructions rules, plus one scope-specific addition: the
career prompt forbids promising outcomes or calling a candidate
unsuitable; the organization prompt forbids naming any individual
candidate and forbids inventing a reason for a difficult-to-fill flag
beyond the ones supplied; the market prompt forbids describing a trend
without an explicit direction in the facts and forbids any external
market claim.

---

## 9. Data quality (`app/intelligence/quality/`)

`GET /api/v1/admin/data-quality[/rules|/skill-mappings|/issues/{rule_id}]`,
`PUT /api/v1/admin/data-quality/issues/{rule_id}/{entity_id}/triage`.
Gated on V25.2's `SYSTEM_CONFIGURATION` permission.

### Declarative rules, generic runner

A rule (`app/intelligence/quality/rules.py`) is an id, entity type,
severity, human explanation, remediation suggestion, and a SQLAlchemy
`select` returning the offending rows. The runner
(`quality/runner.py`) does counting, pagination, and triage-state
joining generically, so adding a rule is one declarative entry and no
new query plumbing. 18 rules ship, covering jobs (missing title,
placeholder/empty description, no apply route, invalid URL, invalid
status, no publication timestamp, stale in review, past deadline,
stale published, no skills), candidates (no profile, no skills and no
resume, resume with no extracted text), applications (orphaned job
reference, orphaned user reference, inconsistent hired state, invalid
pipeline stage, tracker application orphan), plus a duplicate-job-group
detector and an unrecognized-skill-name report.

**Rules that find nothing are still listed, with a count of zero.** A
clean rule disappearing from the report would make "we stopped
checking" indistinguishable from "there is nothing wrong" — tested
directly (`test_data_quality_no_rules_disappear_when_clean`).

### Nothing here modifies inspected data (spec §13)

No `UPDATE`, `DELETE`, or `INSERT` against any inspected table exists
anywhere in the data-quality feature, and no "fix" or "clean up"
endpoint exists at all. The **only** write is an administrator's
triage decision (`open`/`acknowledged`/`resolved`/`wont_fix` plus an
optional note), stored in the one new table this version adds
(`data_quality_issue_states`) and committed together with its V25.2
platform-audit record. Data-quality *issues themselves are not
stored* — they're recomputed from the rule catalog on every request,
so the report can never drift from the data it describes, and a fixed
row simply stops being flagged on its own. Verified end to end by
`test_data_quality_never_modifies_inspected_record`, which triages an
issue and then asserts the underlying job row is byte-for-byte
unchanged.

`entity_id` is a plain integer, not a foreign key — several rules
exist specifically to find rows whose references are *already broken*
(`application_orphan_job`, `application_orphan_user`), and a foreign
key would make those particular issues impossible to triage.

### Duplicate detection

Same-title + same-organization jobs are grouped and reported as a
**review signal**, never auto-merged: two genuinely different postings
can legitimately share a title and employer (different locations,
different years), so automatic merging would destroy real listings.
Note for anyone extending this: the *ingestion* pipeline's own
`is_duplicate()` check (organization + title, case-insensitive, no
deadline) already prevents two such jobs from being created through
`POST /admin/ingest` in the first place — the data-quality rule exists
for rows that predate stricter dedup, arrived through direct import, or
came from adapters that bypass that check.

---

## 10. Privacy (spec §17)

| Audience | Sees |
|---|---|
| Candidate | Their own profile/resume/applications/skills, plus aggregate CareerOS market figures. Never another candidate's data, at any granularity. |
| Recruiter/organization | Their own organization's aggregate hiring data, gated by V25.1 membership. Never another organization's data. |
| Platform admin | Platform-level aggregates, gated by V25.2 permissions. Organization authority grants nothing here (unchanged from V25.2). |

Never leaked, anywhere in V25.3: private candidate notes, private
documents, unauthorized resumes, internal recruiter notes,
organization-private data outside the caller's own organization, or
any protected characteristic (date of birth, reservation category,
disability status — none is read, none is inferred, none is used as a
grouping key anywhere in this package).

**Small-sample suppression** (`app/intelligence/thresholds.py`) is a
*privacy* control, not just a statistical one: a breakdown row backed
by fewer than `intelligence_min_group_size` distinct entities is
withheld outright, because a small "aggregate" can function as an
identification. Every suppression is visible in the response
(`suppressed_rows`/`suppressed_locations` plus a stated reason) rather
than a silent gap.

---

## 11. Data retention (spec §18)

**No new event table was added.** Everything spec §16 lists as a
candidate event — job viewed/saved, application created, status
changed, interview scheduled, recommendation clicked, search/filter
usage, recruiter job interaction — is already recorded by
`recommendation_events` (impressions/opens/saves/applies/dismissals/
search/filter), `application_events`, `application_status_history`,
`recruiter_pipeline_history`, `search_query_logs`/`recent_searches`,
and `saved_jobs`/`applicants` themselves. Adding a general page-view
tracker would be new behavioural collection with a new retention
obligation, for a metric this codebase has already chosen to report
honestly as unavailable (`active_users`, see §7 of the dashboard
response's `omitted_metrics`) rather than approximate with a
newly-collected proxy. Retention for all of those event sources is
unchanged by V25.3.

The one new table, `data_quality_issue_states`, holds an
administrator's own triage judgement, not user behaviour, and has no
retention concern beyond ordinary operational data.

---

## 12. Sample-size thresholds (spec §21)

Three thresholds, all V25.2 typed platform settings — not hardcoded at
call sites, so they are validated, bounded, operator-tunable at
runtime, and audited on change:

| Setting | Default | Guards |
|---|---|---|
| `intelligence_min_corpus_jobs` | 5 | Any skill/role/location breakdown of a job set |
| `intelligence_min_trend_observations` | 10 | Whether a trend reports a direction at all |
| `intelligence_min_group_size` | 5 | Whether a single breakdown row is shown (privacy floor) |

Every suppression returns `{"status": "insufficient_data",
"sample_size": N, "required_sample_size": M, "message": "..."}` rather
than an empty list, so "insufficient data" and "genuinely zero" are
never visually identical.

---

## 13. Database

### New

One table: `data_quality_issue_states` (administrator triage state —
see §9). One model comment block documenting why nothing else was
added.

### Deliberately not added (spec §§15, 16, 30)

- **No aggregate/snapshot tables, no materialized views.** Every V25.3
  aggregate is a `GROUP BY`/`COUNT` over indexed columns, bounded by a
  date window and a page size, over tables sized in jobs and
  applications, not raw events. Section 15 says to create these only
  when necessary for performance and to prefer real-time calculation
  when it's efficient enough; that measurement has not shown a need.
  Materialized views specifically would also give CareerOS's two
  supported database backends (SQLite, PostgreSQL) different freshness
  semantics for the same endpoint, since SQLite has no equivalent.
- **No new analytics event table** — see §11.

### Indexes (migration `v25_3_data_intelligence.sql`)

`ix_jobs_status_published_at` (the corpus filter every analytic
shares), narrow composites on `(status, category)` /
`(status, location)` / `(status, work_mode)` / `(status, job_type)`
for the distribution `GROUP BY`s, `(owner_user_id, status)` for
organization scoping, `(user_id, created_at)` on `applicants` for a
candidate's own history, `(job_id, pipeline_stage)` for organization
pipeline grouping, `(source_name, started_at)` on `ingestion_runs` for
ingestion activity, plus the two indexes on
`data_quality_issue_states` serving its own lookups. All additive,
all `IF NOT EXISTS`, no backfill required.

---

## 14. API endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/career-intelligence/overview` | |
| GET | `/career-intelligence/skills` | |
| GET | `/career-intelligence/relevant-skills` | |
| GET | `/career-intelligence/skill-gaps` | |
| GET | `/career-intelligence/roles` | Roles observed on CareerOS |
| GET | `/career-intelligence/roles/{role}` | |
| POST | `/career-intelligence/ai-summary` | Rate-limited (`ai` bucket) |
| GET | `/market-intelligence/overview` | |
| GET | `/market-intelligence/skills` | |
| GET | `/market-intelligence/roles` | |
| GET | `/market-intelligence/trends` | Skill + volume trends |
| GET | `/market-intelligence/locations` | |
| GET | `/market-intelligence/salary` | Disclosure coverage, not analytics |
| GET | `/organizations/{id}/intelligence` | Full payload |
| GET | `/organizations/{id}/intelligence/hiring` | V24.4, unmodified |
| GET | `/organizations/{id}/intelligence/skill-demand` | |
| GET | `/organizations/{id}/intelligence/candidate-pool` | Privacy-floored |
| GET | `/organizations/{id}/intelligence/difficult-to-fill` | |
| GET | `/organizations/{id}/intelligence/job-performance` | |
| POST | `/organizations/{id}/ai-insights` | Rate-limited |
| GET | `/admin/intelligence` | `PLATFORM_ANALYTICS` |
| GET | `/admin/intelligence/skills` | |
| GET | `/admin/intelligence/trends` | |
| POST | `/admin/intelligence/ai-summary` | Rate-limited |
| GET | `/admin/data-quality` | `SYSTEM_CONFIGURATION` |
| GET | `/admin/data-quality/rules` | Catalog only, runs nothing |
| GET | `/admin/data-quality/skill-mappings` | |
| GET | `/admin/data-quality/issues/{rule_id}` | Paginated |
| PUT | `/admin/data-quality/issues/{rule_id}/{entity_id}/triage` | Audited |

No duplicate of any V21/V24 endpoint was created; every path above
either serves a request no existing endpoint answers, or extends
(never re-implements) one that does.

---

## 15. Frontend

| Route | Screen |
|---|---|
| `/career-intelligence` | Profile completeness, skills, application activity, target role, skill gaps, AI summary |
| `/recruiter/intelligence` | Hiring overview, pipeline conversion, skill demand, candidate-pool gaps, difficult-to-fill, AI insights |
| `/admin/intelligence` | Platform intelligence (categories, skills, roles, organizations, candidates, ingestion, AI summary) |
| `/admin/data-quality` | Rule summary, per-rule paginated issue review, triage |

Every screen renders `insufficient_data` payloads as a labelled empty
state rather than an empty chart, shows the sample size and threshold
that were not met, and shows an explicit "AI unavailable, figures
above are unaffected" state when `ai.degraded` is true rather than
hiding the AI panel. No chart implies precision the underlying sample
doesn't support — a suppressed row is shown as suppressed, not
omitted silently.

---

## 16. Security

Tested explicitly (`tests/test_v25_3_data_intelligence.py`):

| Test | Result |
|---|---|
| Career-intelligence router has no identity parameter on any route | Structural — introspected, not just probed |
| Candidate cannot see another candidate's skills/activity | Verified via two independent accounts |
| Organization OWNER of org A → org B's intelligence | 404 |
| Manipulated/nonexistent `organization_id` | 404 |
| Unauthorized AI insight request (non-member) | 404 |
| Admin intelligence / data quality without platform permission | 403 |
| Data-quality triage does not modify the inspected job | Byte-for-byte unchanged, verified |
| AI fact blocks never contain descriptions/notes/resumes | Verified with real analysis payloads |
| Adversarial job title in an AI fact block | Truncated to 120 chars, delivered as inert data |
| No new invasive event-collection table | Verified structurally (one new table, and it's admin triage state) |
| Protected characteristics never appear in career-intelligence responses | Seeded and asserted absent |
| Skill-frequency alias-batch dedup bug | Found and fixed pre-emptively; regression-tested |

---

## 17. Performance

- Every list/aggregate endpoint is either a `GROUP BY`/`COUNT` in SQL
  or a bounded (≤2,000-row) materialization, never an unbounded scan.
- Organization activity and location detail use single grouped joins,
  not a query per organization/location.
- Skill resolution builds the catalog lookup map once per corpus call
  (a single pass over `skills`/`skill_aliases`), not once per job.
- All new indexes are documented in §13 and match the exact filter/
  group shapes the intelligence layer issues.
- AI calls are rate-limited (`ai` bucket) and content-hash cached, so
  an unchanged analysis costs nothing on a repeat request.

---

## 18. Limitations, stated plainly

- **No true "active users" metric** — CareerOS records session
  creation, not per-request activity; "users with a session in this
  period" is reported instead, under its own name (inherited from
  V25.2, unchanged here).
- **No salary analytics** — disclosure coverage only, by design (§5).
- **No role taxonomy** — job titles are reported and grouped as
  entered; "Senior Backend Engineer" and "Backend Developer" are not
  clustered into one role family, because CareerOS has no basis to
  decide that clustering.
- **No demographic analytics of any kind** — not implemented, and none
  is planned; CareerOS stores no protected characteristics and this
  version introduces no proxy for one.
- **`job_performance` remains per-job** (inherited from V24.4,
  unmodified) — acceptable at the bounded page sizes V25.3 calls it
  with, not re-optimized here since that would be rewriting stable
  V24.4 code the spec asks to leave alone.

---

## Verification status

See `V25_3_TEST_REPORT.md` for what was and was not executed. In
short: full source-level verification (every model field, function
signature, and column constraint referenced was checked against the
actual codebase, catching two real bugs — see §3 and §8 above — before
they would have surfaced at runtime), but the build environment has no
network access, so the ~54-test suite, the frontend build, lint and
type-check could not be run. They are reported **NOT VERIFIED**, not
as passing.
