# CareerOS â€” Skill Gap Engine

`GET /resume-ai/skill-gap/{job_id}` and the `skill_gap` object
returned by `GET /resume-ai/job-match/{job_id}`. Logic in
`backend/app/resume_ai/skill_gap.py`.

## Categories

| Category | Definition | How it's computed |
|---|---|---|
| **Matched skills** | On the resume and required/preferred by the job | Intersection of the resume's detected technical skills and the job's detected skill vocabulary (both via the shared `SKILLS` list from `app.services.career`) |
| **Missing skills** | Wanted by the job, not on the resume | Job's skill set minus the resume's skill set |
| **Weak skills** | Claimed in the Skills list but never reinforced | A matched skill that never appears anywhere in the resume's Experience or Project text â€” listed, but not demonstrated in this resume's own words |
| **Transferable skills** | A missing skill with a curated adjacency to something the candidate has | Looked up in a small, fixed, hand-curated adjacency map (`_ADJACENT_SKILLS`) â€” e.g. Java to Spring Boot, React to Next.js. Empty/no match is the expected, correct result far more often than a hit â€” this is deliberately conservative |
| **Recommended skills** | Missing skills with *no* transferable bridge | The "worth learning closer to scratch" set â€” missing skills minus whatever's already covered by a transferable bridge |
| **Prioritized gaps** | Missing skills ranked by how often the job listing mentions them | `missing_skills` sorted by mention count in the job's title/description/qualification/category/selection-process text, most-mentioned first |

## Why "weak" and "transferable" are rule-based, not AI judgments

Everything else in this list (matched/missing) is a simple set
operation. "Weak" and "transferable" are the two genuine judgment
calls â€” so both are pinned to one explicit, inspectable rule rather
than a model's impression, specifically so the same resume against the
same job always produces the same gap analysis, and so a candidate
disputing a "weak" or "transferable" label can see exactly why it was
assigned by reading the one rule that assigned it.

## Extending the transferable-skills map

`_ADJACENT_SKILLS` in `skill_gap.py` is a fixed, small, editorial map
â€” add to it carefully. It only ever connects two skills that are
already in the shared `SKILLS` vocabulary (`app.services.career`), so
a "transferable" claim never introduces a skill concept nothing else
in the platform recognizes. This is intentionally not auto-generated
or inferred per-candidate â€” every entry is a real, reviewable
editorial claim ("Java experience gives a head start on
Kotlin-flavored JVM roles"), not a per-resume guess.

## What this engine does not do

- It does not rank or verify *proficiency* â€” "matched" means the
  keyword is present, not that the candidate is an expert.
- It does not infer a skill the resume never states, even if the
  candidate's experience *sounds like* it would involve that skill â€”
  see `AI_RESUME_PRIVACY.md`'s hallucination-prevention section.
- Prioritization is purely mention-frequency in the job text â€” it does
  not weigh "required" vs. "preferred" differently unless that
  distinction is itself reflected in how many times a skill is
  mentioned, since the job description text this reads doesn't
  reliably separate those two lists structurally across every job
  posting format CareerOS ingests.

