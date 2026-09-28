"""V25.3 — the reusable skill analytics engine (spec section 3).

Every skill figure in V25.3 — candidate coverage, role requirements,
market demand, organization skill demand, gap analysis — is computed
by this module over a corpus from ``corpus.py``. One implementation,
five callers.

WHERE SKILLS COME FROM
----------------------
``jobs.skills`` — the comma-separated list a recruiter entered on the
job, or an ingestion adapter mapped. That is the only field treated as
a skill requirement.

Deliberately **not** used: the free-text ``description``,
``requirements``, ``qualification`` or ``responsibilities`` columns.
Scanning prose for skill names would let "no Java experience
required", "we are migrating off Java" and "Java" all count
identically as demand for Java. A keyword hit in a paragraph is not a
stated requirement, and inventing requirements is exactly what spec
section 3 forbids.

The consequence is honest and visible: jobs with no ``skills`` value
contribute nothing, and every response reports how many jobs in the
corpus actually carried skill data
(``jobs_with_skill_data``/``skill_data_coverage_pct``). A skill
frequency computed over 12 of 400 jobs is reported as such rather
than presented as a finding about 400 jobs.

NORMALIZATION
-------------
Through ``app.skill_intelligence.normalization`` (V20.5) only —
exact, case-insensitive matching against the curated ``skills``
catalog and its ``skill_aliases``. "Postgres" and "PostgreSQL"
normalize together because the catalog says so, not because this file
guesses. Nothing fuzzy, no stemming, no AI call, and no new alias
table.

Names the catalog does not recognize are **not discarded** — they are
counted separately as ``unrecognized_skills`` so a genuinely common
skill missing from the catalog shows up as a data-quality signal
(see ``quality/rules.py``) rather than vanishing.

REQUIRED VS PREFERRED
---------------------
CareerOS has no structured required/preferred split on a job — there
is one ``skills`` column. This module therefore reports skills as
**stated** requirements and does not fabricate a tier. Section 3
lists required-vs-preferred as a *possible* metric; inventing the
distinction by guessing from word order would be worse than not
reporting it. ``requirement_tiers_available`` is returned as False so
the absence is explicit rather than looking like an oversight.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.intelligence import thresholds
from app.models.domain import Job, Profile, Resume
from app.skill_intelligence.normalization import _lookup_map

# A job listing more than this many skills is almost always a keyword
# dump rather than a requirement list; counting all of them would let
# one listing dominate a frequency table.
MAX_SKILLS_PER_JOB = 40


def split_skill_text(value: str | None) -> list[str]:
    """Split a comma-separated skill column into raw names."""
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()][:MAX_SKILLS_PER_JOB]


@dataclass
class NormalizedSkills:
    """Canonical skill names plus the names that did not resolve."""

    canonical: list[str] = field(default_factory=list)
    unrecognized: list[str] = field(default_factory=list)


def normalize(db: Session, raw_names: list[str]) -> NormalizedSkills:
    """Resolve raw skill names through the V20.5 catalog.

    Returns canonical names (lowercase, catalog-authoritative) and the
    unresolved remainder verbatim.

    Uses ``_lookup_map`` — the plain alias/canonical-name dictionary
    V20.5 builds — rather than ``resolve_many``. ``resolve_many``
    dedupes its *output* by resolved skill id within one call, so if a
    batch contains two different aliases of the same skill (e.g.
    "Postgres" and "PostgreSQL" both appearing among a corpus's raw
    skill strings), only the alphabetically-first is returned in
    ``resolved`` and the second is silently dropped — neither
    resolved nor reported as unrecognized. That is fine for
    ``resolve_many``'s original one-job caller, where duplicate skills
    on a single job are genuinely redundant; it is wrong for skill
    *frequency counting* across many jobs, where losing which jobs
    used which alias would undercount. Building the lookup once and
    resolving every name against it independently avoids that.
    """
    if not raw_names:
        return NormalizedSkills()
    lookup = _lookup_map(db)
    canonical: list[str] = []
    unrecognized: list[str] = []
    for raw in raw_names:
        clean = (raw or "").strip()
        if not clean:
            continue
        skill = lookup.get(clean.lower())
        if skill is not None:
            canonical.append(skill.canonical_name)
        else:
            unrecognized.append(clean.lower())
    return NormalizedSkills(canonical=canonical, unrecognized=unrecognized)


@dataclass
class SkillCorpus:
    """Per-job canonical skill sets, plus coverage bookkeeping."""

    per_job: list[set[str]] = field(default_factory=list)
    job_count: int = 0
    jobs_with_skill_data: int = 0
    unrecognized: Counter = field(default_factory=Counter)
    display_names: dict[str, str] = field(default_factory=dict)

    @property
    def coverage_pct(self) -> float:
        if not self.job_count:
            return 0.0
        return round(self.jobs_with_skill_data / self.job_count * 100, 1)

    def coverage_note(self) -> dict:
        return {
            "jobs_in_corpus": self.job_count,
            "jobs_with_skill_data": self.jobs_with_skill_data,
            "skill_data_coverage_pct": self.coverage_pct,
            "note": (
                "Skill figures are computed only over jobs that list skills explicitly. "
                "Job description text is never scanned for skill names."
            ),
        }


def build(db: Session, jobs: list[Job]) -> SkillCorpus:
    """Normalize a corpus's skills in ONE catalog pass.

    Builds ``_lookup_map`` once (a single query pass over the skills
    and aliases tables) and resolves every job's raw skill names
    against it directly — not ``resolve_many``, whose per-call dedup
    by resolved skill id would silently drop a job's skill entirely
    when a different job in the same corpus already claimed that
    skill's first alias (see the comment on ``normalize`` above for
    why that is wrong for frequency counting specifically).
    """
    corpus = SkillCorpus(job_count=len(jobs))
    if not jobs:
        return corpus

    per_job_raw = [split_skill_text(job.skills) for job in jobs]
    flat = [name for names in per_job_raw for name in names]
    if not flat:
        corpus.per_job = [set() for _ in jobs]
        return corpus

    lookup = _lookup_map(db)
    for skill in lookup.values():
        corpus.display_names[skill.canonical_name] = skill.display_name

    for raw_names in per_job_raw:
        canonical = set()
        for name in raw_names:
            key = name.lower()
            skill = lookup.get(key)
            if skill is not None:
                canonical.add(skill.canonical_name)
            else:
                corpus.unrecognized[key] += 1
        corpus.per_job.append(canonical)
        if canonical:
            corpus.jobs_with_skill_data += 1

    return corpus


def frequency(corpus: SkillCorpus, *, limit: int = 25) -> list[dict]:
    """How many jobs in the corpus list each skill.

    Document frequency, not term frequency: a job that lists "SQL"
    three times counts once, because the question is "how many
    employers want this", not "how many times was the word typed".
    """
    counter: Counter = Counter()
    for skills in corpus.per_job:
        counter.update(skills)
    base = corpus.jobs_with_skill_data or 1
    return [
        {
            "skill": name,
            "display_name": corpus.display_names.get(name, name),
            "job_count": count,
            "pct_of_jobs_with_skills": round(count / base * 100, 1),
        }
        for name, count in counter.most_common(limit)
    ]


def co_occurrence(corpus: SkillCorpus, *, limit: int = 20, minimum: int = 2) -> list[dict]:
    """Skill pairs that appear together on the same job.

    Bounded by ``MAX_SKILLS_PER_JOB``: a job listing n skills
    contributes n*(n-1)/2 pairs, so an unbounded skill list would make
    this quadratic in a single row's content. Pairs seen fewer than
    ``minimum`` times are dropped as noise.
    """
    counter: Counter = Counter()
    for skills in corpus.per_job:
        ordered = sorted(skills)
        for i, first in enumerate(ordered):
            for second in ordered[i + 1 :]:
                counter[(first, second)] += 1
    return [
        {"skills": [first, second], "job_count": count}
        for (first, second), count in counter.most_common(limit)
        if count >= minimum
    ]


def unrecognized_report(corpus: SkillCorpus, *, limit: int = 15) -> list[dict]:
    return [
        {"name": name, "job_count": count}
        for name, count in corpus.unrecognized.most_common(limit)
    ]


# ---------------------------------------------------------------------------
# Candidate-side skills
# ---------------------------------------------------------------------------


def candidate_skills(db: Session, user_id: int) -> NormalizedSkills:
    """A candidate's canonical skill set, from their own data only.

    Two sources, both the candidate's: the ``skills`` they typed on
    their profile, and the skills detected from the resume they
    uploaded. Nothing is inferred from their name, location, education
    institution, date of birth or reservation category — the last two
    exist on ``Profile`` for the V5 eligibility engine and are never
    read here (spec section 5, and section 29's protected-attribute
    audit).
    """
    import json

    raw: list[str] = []
    profile = db.get(Profile, user_id)
    if profile and profile.skills:
        raw.extend(split_skill_text(profile.skills))

    resume = db.get(Resume, user_id)
    if resume and resume.skills_detected:
        try:
            parsed = json.loads(resume.skills_detected)
            if isinstance(parsed, list):
                raw.extend(str(item) for item in parsed)
        except (ValueError, TypeError):
            raw.extend(split_skill_text(resume.skills_detected))

    return normalize(db, raw)


@dataclass
class Coverage:
    """A deterministic, fully explainable coverage result.

    No weighting, no learned model, no opaque score: matched / total,
    with both lists returned so a candidate can check the arithmetic
    themselves. Spec section 2 forbids an unexplainable "career
    score", so none is produced anywhere in this package.
    """

    matched: list[str]
    missing: list[str]
    total_required: int

    @property
    def pct(self) -> float:
        if not self.total_required:
            return 0.0
        return round(len(self.matched) / self.total_required * 100, 1)

    def as_dict(self, corpus: SkillCorpus | None = None) -> dict:
        display = corpus.display_names if corpus else {}
        return {
            "matched_skills": [{"skill": s, "display_name": display.get(s, s)} for s in self.matched],
            "missing_skills": [{"skill": s, "display_name": display.get(s, s)} for s in self.missing],
            "matched_count": len(self.matched),
            "required_count": self.total_required,
            "coverage_pct": self.pct,
            "formula": (
                f"{len(self.matched)} of {self.total_required} reference skills matched "
                f"= {self.pct}%. A skill matches when the candidate's normalized skill name "
                f"equals the reference skill's canonical name in the CareerOS skill catalog."
            ),
        }


def coverage(candidate: set[str], reference: list[str]) -> Coverage:
    """Match a candidate's skills against a reference skill list."""
    reference_set = list(dict.fromkeys(reference))
    matched = [skill for skill in reference_set if skill in candidate]
    missing = [skill for skill in reference_set if skill not in candidate]
    return Coverage(matched=matched, missing=missing, total_required=len(reference_set))


def reference_skills_from_corpus(
    corpus: SkillCorpus, *, top_n: int = 15, min_job_count: int = 2
) -> list[str]:
    """The skills that define a role, derived from real listings.

    A skill qualifies as part of a role's requirement profile when it
    appears on at least ``min_job_count`` jobs in the corpus. The
    floor matters: without it, one recruiter's idiosyncratic skill
    entry would become a "requirement" for the whole role, which is
    the fabrication section 5 prohibits.
    """
    counter: Counter = Counter()
    for skills in corpus.per_job:
        counter.update(skills)
    return [name for name, count in counter.most_common(top_n) if count >= min_job_count]


def skill_summary(db: Session, jobs: list[Job], *, limit: int = 25) -> dict:
    """The standard skill block returned by several endpoints."""
    corpus = build(db, jobs)
    return {
        **corpus.coverage_note(),
        "top_skills": frequency(corpus, limit=limit),
        "co_occurring_skills": co_occurrence(corpus),
        "unrecognized_skill_names": unrecognized_report(corpus),
        "requirement_tiers_available": False,
        "requirement_tiers_note": (
            "CareerOS jobs carry a single skills list with no structured "
            "required/preferred split, so no tier is reported. Inferring one would "
            "mean inventing requirements."
        ),
    }


def guard_corpus(db: Session, job_count: int) -> dict | None:
    """Return an insufficient-data payload if the corpus is too small.

    Callers do ``blocked = guard_corpus(...)`` and return it directly,
    so the threshold check is one line at every call site and cannot
    be accidentally skipped in one of them.
    """
    limits = thresholds.load(db)
    if job_count < limits.min_corpus:
        return thresholds.insufficient(job_count, limits.min_corpus, subject="CareerOS job data")
    return None
