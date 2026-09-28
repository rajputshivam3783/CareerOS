# CareerOS â€” Career Context Engine

`GET /career-copilot/context` and `backend/app/career_copilot/
context_engine.py`. This is the single function every other module in
`career_copilot` â€” and the chat prompt itself â€” reads its facts from.

## What it assembles

| Source | Table(s) | Notes |
|---|---|---|
| Candidate profile | `Profile` | Location, qualification, skills, preferred roles/locations |
| Career preferences | `CareerPreference` | Target role, industry, work mode, goals â€” self-reported only |
| Resume summary | `ResumeAnalysis` | Technical/soft skills, missing sections, overall score â€” the *already-computed* analysis, not a fresh resume parse on every chat message |
| Saved jobs | `SavedJob` + `Job` | Up to 20 most recent |
| Applications | `Application` | Up to 30 most recent, plus which have a deadline in the next 14 days |

Every query is scoped to the one `user_id` passed in â€” there is no
function in this module callable with one user's id that can return
another's data. Authorization is enforced by which id gets passed in
(from the authenticated session), not by a filter that could be
bypassed.

## Known vs. unknown

`CareerContext.unknown_fields` is populated alongside every other
field, not derived afterward â€” each accessor
(`_profile_dict`, `_preferences_dict`, `_resume_summary`) returns its
data *and* the specific sub-fields it couldn't find, in the same pass.
This is what makes "clearly distinguish known information from unknown
information" a property of the data structure, not a hope about how
the model phrases its answer.

`to_prompt_text()` renders this into a prompt block with two
explicitly labeled sections:

```
=== KNOWN CANDIDATE CONTEXT (verified from CareerOS records) ===
...
=== UNKNOWN / NOT YET PROVIDED (do not assume or invent values for these) ===
...
=== END CONTEXT ===
```

The system prompt (`system_prompt.py`) instructs the model to treat
this block as the *only* source of truth about the candidate â€” see
AI_SAFETY.md.

## Why nothing here is a second copy of resume/matching data

`context_engine` reads `ResumeAnalysis` (the already-computed V20.2
result), not a fresh resume parse â€” a chat message never triggers a
new AI Resume Intelligence pass. If a candidate wants an updated
resume analysis, they use `GET /resume-ai/analysis?refresh=true` directly; the Copilot picks up whatever the latest stored
analysis says. Job recommendations and skill gaps are computed
on-demand by `job_recommendations.py`/`roadmap.py` calling the
existing V6/V20.2 engines directly â€” `context_engine` itself doesn't
duplicate that logic, it only summarizes what's already stored
(profile, resume analysis, saved jobs, applications).

## Why there's no separate "AI context metadata" table

The original spec's database section lists "AI context metadata" as
something to support. This is deliberately *not* a stored table here:
persisting a record of exactly which context fields were fed into
each chat turn would mean storing a structured echo of the candidate's
profile/resume/application data a second time, purely for audit â€” with
no feature benefit, and a real privacy cost (a second place personal
data lives, that could drift from the source of truth, per "Do not
store sensitive information unnecessarily"). The chat response itself
already returns a `context_used` object (booleans/counts â€” see
`assistant.send_message`'s return shape) showing *which categories*
of context were available for that turn, which is enough for the
frontend's transparency needs without a persisted audit trail of the
content itself.

## Performance note

`context_engine.build()` runs a handful of indexed queries (`Profile`
by PK, `CareerPreference` by PK, `ResumeAnalysis` by PK, `SavedJob`/
`Application` by indexed `user_id`, both capped at a small limit) â€”
no AI call, no expensive computation. It's called once per chat turn
and once for the standalone `/context` endpoint; there is no caching
layer for it because there's no cost to avoid.

