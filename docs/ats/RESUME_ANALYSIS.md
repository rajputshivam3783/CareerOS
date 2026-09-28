# CareerOS â€” Resume Analysis

How `GET /resume-ai/analysis` works, what each score means, and how
it's calculated. All scoring logic lives in `backend/app/resume_ai/
scoring.py` â€” read that file's docstrings alongside this for the
exact point allocations.

## Pipeline

`POST /resume` (V8, unchanged) â†’ `extraction.extract()` â†’
`normalization.normalize()` â†’ `scoring.*()` + `ats_analysis.analyze()`
â†’ persisted as `ResumeAnalysis` (one row per user, replaced on
recompute â€” call `GET /resume-ai/analysis?refresh=true` to force a
fresh pass; otherwise the last-computed result is returned).

## Extraction (deterministic, no AI)

`extraction.py` pulls name, email, phone, location, GitHub/LinkedIn/
portfolio links, and splits the resume into sections by matching
headings against a fixed alias table (`SUMMARY`/`Objective`/`Profile`
all map to `summary`, etc. â€” see `_SECTION_ALIASES`). A field that
can't be confidently found is set to the literal string
`"Not found in resume"` â€” never guessed.

## Normalization

`normalization.py` merges technical skills detected two ways: the
shared `SKILLS` vocabulary (the same one job matching uses, via
`app.services.resume_parser.detect_skills`) matched anywhere in the
text, plus whatever the candidate's own Skills section literally
lists. A small, fixed alias map folds spelling variants onto the
shared vocabulary (`js` -> `javascript`, `postgres` -> `sql`, etc.) so
a normalized skill always means the same thing here as it does in job
matching. Soft skills are matched against a short, explicit keyword
list â€” deliberately conservative, since inferring a soft skill from
tone is exactly the kind of invention this system avoids.

## Scores

| Score | What it measures | Key inputs |
|---|---|---|
| Resume Quality (overall) | Weighted blend of every score below | content_quality 15%, ats_compatibility 15%, skills 20%, experience 25%, education 10%, project 10%, achievement_strength 5% |
| Content Quality | Structural completeness | How many of 8 expected sections are present and non-empty |
| ATS Compatibility | Documented ATS risk factors | Table/column layout, contact info presence, skills section presence, summary presence |
| Skills | Breadth of recognized skills | Technical skill count (up to 10 counted), soft skill count (up to 4 counted) |
| Experience | Structural strength of experience bullets | Line count, action-verb hits, quantified (numeric) bullet hits |
| Education | Presence and count of education entries | Entry count only â€” no institution-ranking or degree-tier judgment is made |
| Project | Structural strength of project bullets | Line count, action-verb hits |
| Keyword Coverage | Technical keyword breadth | Skill count against a general baseline of 12, or against a specific job's keywords when one is supplied (see `job_match.py`) |
| Achievement Strength | Proportion of bullets with a measurable number | Quantified-bullet ratio across experience + projects + achievements |

Every score returns a `reasons` list alongside the number â€” the exact,
plain-language facts that produced it. Nothing here is ever "the model
thought this deserved a 72."

## Response shape

```json
{
  "profile": { "name": "...", "email": "...", "technical_skills": [], "missing_sections": [] },
  "scores": {
    "overall": { "score": 74, "reasons": ["..."] },
    "components": {
      "skills": { "score": 80, "reasons": ["8 technical skill(s) recognized"] },
      "experience": { "score": 65, "reasons": [] }
    },
    "ats": { "readability": "fair", "structure": {}, "formatting_risks": [] }
  },
  "analyzed_at": "2026-08-11T00:00:00"
}
```

## Recommendations

`GET /resume-ai/recommendations` runs `recommendations.py` â€” a set of
fixed, rule-triggered checks (no AI call). Each recommendation has
`area`, `reason`, `impact`, `priority` (high/medium/low), and
`suggested_action` â€” matching the AI Explanations requirement
structurally, since every field is fixed at the moment the rule fires.

