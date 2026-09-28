# CareerOS â€” ATS Scoring

`GET /resume-ai/ats` and the `ats_compatibility` component of
`GET /resume-ai/analysis`. Logic in `backend/app/resume_ai/
ats_analysis.py` (full breakdown) and `scoring.py`
(`ats_compatibility_score`, the single headline number).

## What "ATS" means here

This checks well-documented, vendor-agnostic risk factors â€” the kind
of advice you'd find in any credible resume-writing guide â€” not any
specific ATS vendor's actual parsing behavior. CareerOS has no way to
verify against a real vendor's parser, and claiming to emulate one
specifically would be a claim this system can't back up. Both
`ats_analysis.py` and `scoring.py` say this explicitly in their own
docstrings/notes fields.

## Risk factors checked

| Factor | How it's detected | Why it matters |
|---|---|---|
| Table/multi-column layout | `Resume.has_tables_or_columns` â€” see below | Some ATS parsers read table cells or columns out of visual order |
| Missing contact info | Email/phone not found by `extraction.py` | Many ATS systems require both to create a candidate record |
| Missing skills section | No technical skills detected anywhere | Keyword-matching ATS relies heavily on a visible skills list |
| Missing summary | No summary/objective section found | Recruiter-facing dashboards adjacent to ATS often surface this first |
| Section structure | Which of Summary/Skills/Experience/Education are present | A resume with major missing sections reads as incomplete to both ATS and humans |
| Keyword placement | Whether detected skills also appear in Experience/Project text, or only in a Skills list | Skills only listed once are still keyword-matched, but recruiters weight in-context mentions higher |
| Job title alignment (when a target title is given) | Word overlap between the target job title and resume text | A resume that never mentions related terms to the target title may read as a weaker fit |
| Action verbs | Count of known strong verbs (Led, Built, Reduced, ...) in experience bullets | Active, results-oriented phrasing reads better to both parsers and reviewers |
| Achievement statements | Ratio of bullets containing a number | Quantified achievements are more credible and specific |

## Why table/column detection only works for DOCX

`Resume` only ever persisted *extracted text*, never the original
file bytes â€” so this signal can only be computed once, at upload time,
while the file is still in memory for that request (see
`app/api/platform.py`'s `POST /resume` handler and
`extraction.detect_tables_or_columns`). Even then, only DOCX can be
checked reliably, using `python-docx`'s table API (already a
dependency, via `app.services.resume_parser`). PDF column detection
would require real layout/geometry analysis this project doesn't do â€”
PDFs always report `has_tables_or_columns = None` ("unknown"), and
every score/analysis treats `None` as **neutral** â€” never a penalty,
never a pass. A resume uploaded before this column existed also reads
as `None` for the same reason.

## Readability verdict

`ats_analysis.analyze()` rolls the above into one of three verdicts:

- **`good`** â€” no missing expected sections, no known layout risk, has
  detected skills.
- **`fair`** â€” 1-2 risk signals.
- **`at_risk`** â€” 3+ risk signals.

This is a coarse summary for quick scanning â€” the detailed breakdown
(`structure`, `formatting_risks`, `keyword_placement`,
`skill_visibility`, `job_title_alignment`, `action_verbs`,
`achievement_statements`) is always returned alongside it so nothing
is hidden behind the one-word verdict.

