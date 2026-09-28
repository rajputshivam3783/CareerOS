# CareerOS â€” Career Copilot Guide

How to use the Career Copilot, from both the API and the UI
(`/career-copilot`).

## Getting started

1. Fill in your `Profile` and (optionally) `CareerPreference` â€” the
   more the Copilot knows, the more specific its answers. Neither is
   required to start chatting; an incomplete profile just means more
   fields show up in the "not yet known" list.
2. Upload a resume (`POST /resume`, V8) and let it analyze
   (`GET /resume-ai/analysis`, V20.2) â€” the Copilot reads the latest
   stored analysis automatically.
3. Open `/career-copilot` (linked from Dashboard, Jobs, Applications,
   Resume, and Government pages) and start a conversation, or use one
   of the suggested questions.

## What you can ask

The Copilot is grounded in your real CareerOS data and will say
"not on file" rather than guess when something's missing:

- "What jobs are suitable for me?" -> uses `job_recommendations.py`
  (the same matching engine as `GET /recommendations`)
- "What skills am I missing?" / "What should I learn next?" -> uses
  your resume's skill gap against your best-matching or stated target
  role (`roadmap.py`)
- "How can I improve my resume?" -> points to
  `GET /resume-ai/recommendations` â€” the Copilot doesn't
  duplicate that analysis, it narrates it
- "Why is my match score low?" -> explains which sub-score
  (skills/experience/education/keywords) is weakest, from the same
  breakdown `GET /resume-ai/job-match/{job_id}` returns
- "Which saved jobs should I prioritize?" -> reads your `SavedJob` list
  and any deadlines
- "What should I prepare for this job?" -> for a job you reference,
  combines its stated selection process/exam date with your skill gap
- "Which government jobs match my profile?" / "Which exams am I
  eligible for?" -> never invents eligibility â€” see below
- "What is the deadline?" -> states the job's own `deadline` field, or
  says it's not stated and to check the official notification

## Government job questions â€” how eligibility actually works

The Copilot never computes or states an eligibility verdict itself. It
relays exactly what `app.services.eligibility.eligibility()` (V5, used
everywhere else in CareerOS eligibility is shown) already computed for
that job and your profile:

- **Eligible** â€” profile data supports it, with the reasoning shown.
- **Not eligible** â€” at least one stated requirement isn't met.
- **Cannot be confirmed** â€” required profile data (e.g. date of birth
  for an age check) is missing, or the job's own requirement text
  can't be parsed confidently. This is the answer whenever the
  underlying data is insufficient â€” never a guess.

Every government answer ends with a reminder to verify against the
official notification, and the notification/official links (when
CareerOS has them) are included directly.

## Career Roadmap

`GET /career-copilot/roadmap?job_id=<optional>` returns: Current
Position -> Target Role -> Skill Gaps -> Learning Priorities ->
Projects -> Interview Preparation -> Applications. Without a `job_id`,
it uses your top job recommendation as the implicit target; without a
resume or profile at all, it says so plainly rather than inventing a
generic roadmap.

## Action Plan

`GET /career-copilot/action-plan` returns tasks bucketed into Today /
This Week / This Month / Next 3 Months, prioritized by deadline
proximity, skill gaps, and your stated career goal. Mark an item done
or dismissed with `PATCH /career-copilot/action-plan/{id}` â€” that
status survives the next time the plan regenerates (it won't reappear
as a fresh "pending" item).

## Managing conversations

- **New conversation** â€” `POST /career-copilot/conversations`
- **List / resume a past conversation** â€” `GET /career-copilot/conversations`, then `GET .../conversations/{id}/messages`
- **Rename** â€” `PATCH /career-copilot/conversations/{id}`
- **Clear** (keep the conversation, delete its messages) â€” `POST /career-copilot/conversations/{id}/clear`
- **Delete** (remove the conversation entirely) â€” `DELETE /career-copilot/conversations/{id}`

All of the above only ever operate on conversations you own.

## When the Copilot can't answer

If every configured AI provider is unavailable, sending a message
returns a `503` with a clear message â€” your message is still saved to
the conversation, and the UI shows a retry option rather than losing
what you typed. Every other Copilot feature (recommendations, roadmap,
action plan, government guidance, context) has no AI dependency at all
and keeps working regardless of provider status.

