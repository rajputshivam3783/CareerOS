# CareerOS â€” AI Resume Privacy

How AI Resume Intelligence protects resume data and prevents
fabrication â€” mechanism, not just policy.

## Hallucination prevention

The brief for this feature lists what the AI must never invent:
experience, education, certifications, projects, companies, skills,
achievements, salary, employment history. Here is exactly how each
module enforces that:

### Structured facts never touch a model at all

Name, email, phone, location, links, and every section's raw text are
extracted by `extraction.py` using regex and heading matching â€” zero
AI calls. A model never sees "extract this candidate's work history"
as a task, because the module that does that (`extraction.py`) has no
AI call in it whatsoever. This is the single biggest source of
hallucination risk in resume-parsing systems generally (an LLM asked
to "extract the candidate's job titles" will sometimes confidently
produce a plausible-sounding one that isn't in the text), and it's
closed structurally here, not by asking a model nicely not to do it.

### Scores are deterministic

Every score in `scoring.py`, `ats_analysis.py`, `job_match.py`, and
`skill_gap.py` is a plain function of countable facts (section
presence, bullet counts, keyword overlap) with a fixed point
allocation. A model is never asked "what score should this resume
get" â€” so there's no path for a score to reflect an invented fact.

### Generative modules are grounded and fallback-safe

Four modules make an actual model call: `bullet_improver.py`,
`summary_generator.py`, `project_improver.py`, `job_advice.py`. Each:

1. Sends **only** facts already extracted/normalized from the
   candidate's own resume â€” never open-ended "write me a resume
   summary for a software engineer."
2. Includes an explicit system-prompt instruction not to add a
   company, technology, metric, or outcome that isn't already present
   in what it was given (see each module's `_SYSTEM_PROMPT` constant
   for the exact wording).
3. Has a **deterministic fallback** that runs with zero AI calls when
   no provider is configured â€” a mechanical rewrite, a template built
   from detected facts, or a structured (non-prose) response. The
   fallback path can only rearrange or template words already present
   in the input; it has no capacity to invent, by construction.
4. Every response is tagged with `"source": "ai" | "template" |
   "structured_only" | "cache"` so the caller (and the UI) always
   knows whether a given piece of text came from a model or a
   deterministic fallback.

### "Not found in resume"

Any field extraction couldn't confidently locate â€” a phone number, a
GitHub link, a summary â€” is reported as the literal string `"Not found
in resume"`, never omitted silently and never guessed. This is what
lets a candidate (or a recruiter reviewing an applicant) trust that
every non-"Not found" field really is backed by text in the resume.

### What this system does not (and cannot) verify

None of this checks whether the resume's own claims are *true* â€” if a
candidate's resume states an employer or metric that isn't real, this
system has no way to know that and doesn't attempt to. "Never invent"
here means "never add something beyond what the resume already
states" â€” it is not a truthfulness/fact-check guarantee about the
resume's original content.

## Privacy

### What's stored

| Table | Contents | Notes |
|---|---|---|
| `resume_analyses` | Latest normalized profile + scores (JSON) | Derived, structured data only. Replaced on recompute, not archived. |
| `resume_job_matches` | Latest match score + skill gap breakdown per (user, job) pair | Derived, structured data only. |
| `resume_ai_suggestions` | The generated **output** text of a bullet rewrite / summary / project suggestion / job-advice narration | See "What's never stored" below â€” this is the output only. |

### What's never stored

**The prompt sent to a model is never persisted anywhere.** The four
generative modules build a prompt in memory, send it via
`app.ai.completion_service` (which itself only logs token counts/cost/
latency to `AIUsageLog` â€” never prompt or response text, per
`AI_ARCHITECTURE.md`), and only the *generated output* is optionally
cached in `resume_ai_suggestions`. A resume's raw extracted text is
never written into any AI-usage or logging table â€” it lives in exactly
one place, `Resume.extracted_text` (V8, unchanged), which this feature
reads from but never duplicates elsewhere.

### Access control

- A candidate's own resume analysis, job match, skill gap,
  recommendations, and generative endpoints only ever operate on
  *their own* stored `Resume` â€” there is no parameter anywhere on a
  candidate-facing endpoint that accepts another user's resume or
  user id.
- The recruiter endpoint (`GET /resume-ai/applicant/{applicant_id}/
  analysis`) reuses the exact same team-ownership check
  (`app.core.team_access.team_owner_ids`) every other recruiter
  endpoint in `app.api.recruiter` uses, and reads only
  `Applicant.resume_snapshot` â€” the resume text *as it was when the
  candidate applied*, which is the same boundary `Applicant`'s own V9
  docstring already establishes (never the candidate's live,
  possibly-updated `Resume` row). No new candidate PII is exposed to a
  recruiter beyond what `app.api.recruiter`'s existing endpoints
  already show for that applicant.
- `GET /resume-ai/usage` (admin-only, reuses `app.api.admin.guard`)
  returns aggregated usage/cost/latency numbers and per-call metadata
  (provider, model, operation label, success/failure) â€” never resume
  content, never a candidate identifier beyond what's already in
  `AIUsageLog.user_id` (a plain foreign key, not resume text).

### Logs

No resume text, extracted profile field, or generated suggestion is
ever written to application logs. The only durable record of an AI
call is `AIUsageLog` (V20.1, reused as-is), which stores token counts,
cost estimates, latency, and success/failure â€” never content.

