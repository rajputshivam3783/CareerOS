# CareerOS â€” AI Resume Architecture

## What this is

V20.2 adds `backend/app/resume_ai/` â€” AI Resume Intelligence â€” built on
top of the V20.1 AI Gateway (`app/ai/`) and the V8 resume module
(`app.services.resume_parser` / `app.services.resume_match`, both
unchanged). It analyzes resumes, scores them, matches them against
CareerOS jobs, identifies skill gaps, and generates wording
suggestions â€” all grounded strictly in what a resume's own text
actually contains. See `RESUME_ANALYSIS.md`, `ATS_SCORING.md`,
`SKILL_GAP_ENGINE.md`, and `AI_RESUME_PRIVACY.md` for the detail this
file doesn't cover.

## The one rule everything else follows

**Every score is deterministic. Only wording is generative, and only
from facts already extracted.** Concretely:

- Resume Quality, ATS Compatibility, Content Quality, Skills,
  Experience, Education, Project, Keyword Coverage, and Achievement
  Strength scores (`scoring.py`) are plain functions of countable
  facts â€” never a model's opinion. Same inputs, same score, every time.
- Job match scoring (`job_match.py`) and skill gap analysis
  (`skill_gap.py`) are equally deterministic â€” text overlap, shared
  vocabulary matching, a small curated adjacency map for
  "transferable" skills.
- The only genuinely generative modules are `bullet_improver.py`,
  `summary_generator.py`, `project_improver.py`, and `job_advice.py`
  â€” and every one of them is instructed, explicitly, to use *only*
  facts already present in what's given to it, with a deterministic
  fallback that runs with zero AI calls when no provider is configured.

This is what makes "Do NOT produce arbitrary scores. Every score must
have an explanation" and the hallucination-prevention requirements
structural rather than aspirational â€” see `AI_RESUME_PRIVACY.md` for
exactly how each generative prompt enforces "never invent."

## Never bypasses the AI Gateway

Every call to a model goes through `app.ai.completion_service.generate`
â€” the exact same V20.1 entry point `app.api.ai`'s conversation
endpoints use. Nothing in `resume_ai/` imports a provider adapter or
calls a vendor SDK/URL directly. This means resume_ai automatically
inherits, for free: provider fallback, retry, token/cost estimation,
and usage logging (queryable via `GET /resume-ai/usage`, which filters
`app.ai.observability` by the `resume_ai.*` operation prefix rather
than keeping a second usage-tracking system).

## Pipeline

```
Resume (V8, unchanged)
  -> extraction.extract()        # deterministic: regex + section headers
  -> normalization.normalize()   # skill aliasing, dedup, missing-section flags
  -> scoring.*() + ats_analysis.analyze()   # deterministic scores, all explained
  -> pipeline.run_and_persist()  # -> ResumeAnalysis (latest, replaces previous)

Resume + a chosen Job
  -> job_match.match()           # explainable, multi-dimension score
  -> skill_gap.analyze()         # matched/missing/weak/transferable/recommended
  -> job_advice.build()          # narrates the above (AI Gateway + fallback)

A candidate-selected bullet/summary-request/project text
  -> bullet_improver.improve() / summary_generator.generate() / project_improver.improve()
     (AI Gateway, strict no-fabrication prompt, deterministic fallback)
```

`pipeline.py` is the only module that touches the database directly
for the analysis path; every other module is a pure function of its
inputs, which is what makes the scoring/matching logic directly unit
testable without a database or a running app (see
`test_v20_2_ai_resume_intelligence.py`).

## Reuse, not rewrite

| Reused as-is | From |
|---|---|
| PDF/DOCX/TXT extraction, `POST /resume` upload | `app.services.resume_parser`, `app.api.platform` |
| Shared `SKILLS` vocabulary, `job_text()` | `app.services.career` |
| Base resume-vs-job matching signal | `app.services.resume_match.match_resume_to_job` |
| Provider selection, retry/fallback, cost estimation, usage logging | `app.ai.*` |
| `current_user`, `require_recruiter` | `app.core.security` |
| Recruiter team ownership check | `app.core.team_access.team_owner_ids` |
| Admin auth for `/resume-ai/usage` | `app.api.admin.guard` |

Only one existing file gained new lines: `app/api/platform.py`'s
`POST /resume` handler now also captures a table/multi-column layout
signal for DOCX uploads (see "Why `Resume` gained one column" below)
â€” wrapped defensively so a detection failure can never break the
upload itself, and the endpoint's response shape is unchanged.

## Why `Resume` gained one column

ATS formatting-risk analysis wants to know whether a resume uses a
multi-column/table layout â€” a well-documented ATS parsing risk. But
`Resume` only ever stored *extracted text*, never the original
file bytes, so this can't be computed after the fact â€” only at upload
time, while the bytes are still in memory for that one request. The
fix is a single nullable, backward-compatible column,
`Resume.has_tables_or_columns` (`NULL` for every resume uploaded
before this column existed, or for formats detection can't handle â€”
see `extraction.detect_tables_or_columns`'s docstring for exactly
which). Every score/analysis that uses it treats `NULL` as neutral,
never as a penalty or a pass.

## Storage

Structured, derived results only â€” three new additive tables
(`resume_analyses`, `resume_job_matches`, `resume_ai_suggestions`),
described fully in `AI_RESUME_PRIVACY.md`, which also covers exactly
what is and is not persisted from a generative call.

## What's intentionally not here

Career Copilot, AI Interviewer, AI Learning System, and AI Career
Roadmap are V20.3+ (see `ROADMAP.md`) â€” this pass stops at resume
intelligence, per the original brief's stop condition.

