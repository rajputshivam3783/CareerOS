# AI Privacy Guide â€” V20.6

## What's stored, and where

| Data | Table | Contains raw prompt/response? |
|---|---|---|
| Conversation messages (copilot + generic AI chat) | `ai_messages` | Yes â€” this is the point of a chat history; content is the actual message text |
| Usage/observability | `ai_usage_log` | No â€” tokens, cost, latency, provider, model, success/error **string**, never the prompt or completion body |
| Resume-derived analysis | `resume_analyses` | No â€” structured, derived facts (scores, extracted profile) |
| AI resume suggestions | `resume_ai_suggestions` | The generated suggestion text only (the *output*, not the prompt that produced it) |
| Interview evaluations/reports | `mock_interview_evaluations`, `mock_interview_reports` | Structured scores + narrative text; not the raw prompt |
| Learning/skill data | `skills`, `learning_plans`, `practice_recommendations`, etc. | No AI content at all â€” this module is fully deterministic (see `AI_LEARNING_ARCHITECTURE.md`) |

**No raw prompt is durably stored anywhere.** Prompts are constructed
in memory per-request (`context_builder.py`, each module's own prompt
assembly) and never written to a table â€” only the *inputs* that went
into them (which are the candidate's own resume/profile/answer data,
already stored for other reasons) and the *outputs* (suggestions,
evaluations, narratives) are persisted.

**No debug logging of prompt or completion content** â€” confirmed by
grep across `app/ai`, `app/resume_ai`, `app/career_copilot`,
`app/interview_ai` in this audit; the only logger calls in that
surface area are startup/scheduler messages, not per-request content.

## Deletion capability (V20.6 fixes)

Two real gaps were found and closed this release:

1. **`DELETE /resume`** previously deleted only the `Resume` row,
   leaving `ResumeAnalysis` and every `ResumeAISuggestion` (the
   candidate's AI-derived profile and every AI suggestion ever
   generated for them) in place â€” silently surviving a deletion the
   candidate explicitly requested. Now cascades to both.
2. **`DELETE /ai/conversations/{id}`** didn't exist on the generic
   conversation surface (it existed on `career_copilot`'s equivalent
   surface using the same tables). Added, with the same ownership
   check as every other endpoint.

**Intentionally left alone**: `resume_job_matches` (per-job match
scores) is not deleted when a resume is deleted. These rows are
deterministic, re-derivable, and job-scoped rather than
resume-content-scoped (they don't retain resume text, only a score
per job) â€” treating them as part of "delete my resume" would be
scope creep beyond what the candidate asked for, and they're
naturally superseded the next time the candidate re-uploads a resume
and re-matches.

**Interview sessions/reports have no delete endpoint.** Reviewed this
release and judged intentional, not a gap: a mock interview report is
closer to a performance record the candidate builds a history against
(readiness scoring reads "latest interview" â€” see
`AI_LEARNING_ARCHITECTURE.md`) than a chat log. If a future release
wants candidate-initiated interview-history deletion, it should be a
deliberate product decision, not a silent stabilization-release
addition.

## Who can see what (authorization boundaries, re-verified this release)

- **Candidates**: only their own conversations, resume analysis,
  interview sessions/reports, and learning data. Every relevant
  endpoint checks `resource.user_id == current_user.id` and returns
  404 (not 403) on mismatch â€” confirmed via IDOR tests in
  `test_v20_6_ai_production_stabilization.py`.
- **Recruiters**: can view a candidate's resume analysis **only**
  for applicants within their own recruiting team
  (`_owned_applicant_or_404` in `resume_ai.py`) â€” cannot see copilot
  conversations, interview data, or learning data for any candidate;
  no such route exists at all.
- **Admins**: usage logs, provider config, prompt templates, and
  catalog/resource management â€” never a specific candidate's
  conversation content, resume analysis, or interview answers. Admin
  routes that touch AI data are metadata/aggregate-only
  (`/ai/usage`, `/ai/usage/logs`, `/interview/usage`).
- **Other candidates / other companies**: no cross-boundary access
  exists anywhere in the AI surface area.

## Retention posture

No AI-specific data-retention *time limit* (auto-expiry) exists in
this codebase for any module â€” conversations, analyses, and reports
persist until the candidate explicitly deletes the parent resource
(resume, conversation) or their account. This matches the platform's
general data posture (V17 account deletion cascades everything via
`ON DELETE CASCADE` on `user_id`) and was not changed in V20.6. If a
time-based retention policy is required for compliance, it should be
a deliberate future decision with its own migration and candidate
notice â€” out of scope for a stabilization release.

