"""V24.2 — Advanced Candidate Discovery & Search.

A recruiter-side, authorization-scoped candidate search layer built
entirely on existing tables (``User``, ``Profile``, ``CareerPreference``,
``Resume``, ``Applicant``, ``UserSession``) and existing engines
(``app.search.normalization`` for skill/location normalization,
``app.recommendations`` for job/candidate feature extraction and
deterministic matching). See docs/V24_2_CANDIDATE_DISCOVERY.md for the
full architecture, privacy model, and known limitations.

This is deliberately NOT a second search engine: nothing here is
indexed into ``app.search`` (V21.1's ``SearchIndexDocument``), because
that index's visibility model ("public" or "the owning recruiter's
own row") does not fit candidates at all — a candidate is never
"public"; they are visible only through the two authorization paths
enforced by ``_authorized_candidate_ids`` below. Free-text search here
is plain, bounded, in-Python filtering over an already
authorization-narrowed set of rows (see that function's docstring),
not a general-purpose text index.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.security import require_recruiter
from app.core.team_access import team_owner_ids
from app.db.session import get_db
from app.models.domain import (
    Applicant,
    CareerPreference,
    Job,
    Profile,
    Resume,
    User,
    UserSession,
)
from app.recommendations import candidate_features as cf
from app.recommendations import job_features as jf
from app.recommendations import matching as rec_matching
from app.search.normalization import normalize_location, normalize_skills, normalize_text
from app.skill_intelligence.normalization import resolve_many

router = APIRouter()

MAX_PAGE_SIZE = 50
# Job-specific matching (candidate-matches) scores every candidate in
# the job's authorized pool, which is bounded (applicants to that job
# + the platform's opted-in pool) but not infinitely so — this is a
# defensive hard ceiling, documented in docs/V24_2_CANDIDATE_DISCOVERY.md,
# so a pathologically large opted-in pool can never turn one request
# into an unbounded scoring pass.
MAX_CANDIDATES_TO_SCORE = 300

# Section 6 — there is no numeric years-of-experience field anywhere in
# this schema (confirmed against Profile/CareerPreference/Resume); the
# only structured experience signal is CareerPreference.experience_level,
# a self-reported band. Min/max-years filters are honestly mapped onto
# these bands rather than treated as precise per-candidate numbers —
# see docs/V24_2_CANDIDATE_DISCOVERY.md "Experience filtering".
_EXPERIENCE_BANDS: list[tuple[str, float, float]] = [
    ("entry", 0, 2),
    ("mid", 2, 5),
    ("senior", 5, 10),
    ("lead", 10, 40),
]
_EXPERIENCE_RANK = {name: i for i, (name, _, _) in enumerate(_EXPERIENCE_BANDS)}


def _authorized_candidate_ids(db: Session, recruiter: User, job_id: int | None = None) -> set[int]:
    """The entire candidate-privacy model in one function (spec
    sections 15-17): a recruiter may discover a candidate only if

    1. the candidate applied to one of *this recruiter's* (or their
       team's — ``team_owner_ids``) jobs — narrowed to one job when
       ``job_id`` is given, or
    2. the candidate has explicitly opted in via
       ``Profile.candidate_searchable`` (default False for every
       candidate — see the V24.2 migration).

    Both queries are bounded by construction: (1) is bounded by this
    recruiter's own job/applicant rows, never another team's; (2) is
    bounded by however many candidates have actually opted in, never
    "every user in the system." Neither is a full scan of ``users``.
    """
    owner_ids = team_owner_ids(db, recruiter)
    applied_stmt = select(Applicant.user_id).join(Job, Job.id == Applicant.job_id).where(Job.owner_user_id.in_(owner_ids))
    if job_id is not None:
        applied_stmt = applied_stmt.where(Applicant.job_id == job_id)
    applied_ids = set(db.scalars(applied_stmt))
    opted_in_ids = set(db.scalars(select(Profile.user_id).where(Profile.candidate_searchable.is_(True))))
    return applied_ids | opted_in_ids


def _experience_band(level: str | None) -> tuple[str, float, float] | None:
    if not level:
        return None
    for band in _EXPERIENCE_BANDS:
        if band[0] == level.strip().lower():
            return band
    return None


def _profile_completeness(profile: Profile | None, has_resume: bool, has_career_goal: bool) -> int:
    """Deterministic, documented completeness score — every input is a
    real field the candidate filled in (or didn't); nothing here is
    estimated. 6 equally-weighted signals: location, qualification,
    skills, preferred roles, resume on file, career preferences set."""
    signals = [
        bool(profile and profile.location),
        bool(profile and profile.highest_qualification),
        bool(profile and profile.skills),
        bool(profile and profile.preferred_roles),
        has_resume,
        has_career_goal,
    ]
    return round(100 * sum(signals) / len(signals))


def _candidate_skill_set(db: Session, profile: Profile | None, resume: Resume | None) -> set[str]:
    from app.services.career import tokens as split_tokens

    raw: list[str] = []
    if profile and profile.skills:
        raw.extend(split_tokens(profile.skills))
    if resume and resume.skills_detected:
        import json

        try:
            parsed = json.loads(resume.skills_detected)
            raw.extend(parsed if isinstance(parsed, list) else [])
        except (ValueError, TypeError):
            raw.extend(s.strip() for s in resume.skills_detected.split(",") if s.strip())
    return set(normalize_skills(db, raw))


@dataclass
class _CandidateRow:
    user: User
    profile: Profile | None
    career: CareerPreference | None
    resume: Resume | None
    applicants: list[Applicant]  # this recruiter's applicant rows for this candidate (may be empty)
    skills: set[str]
    completeness: int
    last_seen_at: datetime | None


def _load_candidate_rows(db: Session, recruiter: User, candidate_ids: set[int]) -> list[_CandidateRow]:
    if not candidate_ids:
        return []
    owner_ids = team_owner_ids(db, recruiter)
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(candidate_ids), User.role == "candidate"))}
    profiles = {p.user_id: p for p in db.scalars(select(Profile).where(Profile.user_id.in_(candidate_ids)))}
    careers = {c.user_id: c for c in db.scalars(select(CareerPreference).where(CareerPreference.user_id.in_(candidate_ids)))}
    resumes = {r.user_id: r for r in db.scalars(select(Resume).where(Resume.user_id.in_(candidate_ids)))}
    my_applicants: dict[int, list[Applicant]] = {}
    for a in db.scalars(
        select(Applicant).join(Job, Job.id == Applicant.job_id).where(
            Job.owner_user_id.in_(owner_ids), Applicant.user_id.in_(candidate_ids)
        )
    ):
        my_applicants.setdefault(a.user_id, []).append(a)
    last_seen: dict[int, datetime] = {}
    for uid, seen in db.execute(
        select(UserSession.user_id, UserSession.last_seen_at).where(UserSession.user_id.in_(candidate_ids))
    ):
        if uid not in last_seen or seen > last_seen[uid]:
            last_seen[uid] = seen

    rows = []
    for uid, user in users.items():
        profile = profiles.get(uid)
        resume = resumes.get(uid)
        rows.append(
            _CandidateRow(
                user=user,
                profile=profile,
                career=careers.get(uid),
                resume=resume,
                applicants=my_applicants.get(uid, []),
                skills=_candidate_skill_set(db, profile, resume),
                completeness=_profile_completeness(profile, resume is not None, careers.get(uid) is not None),
                last_seen_at=last_seen.get(uid),
            )
        )
    return rows


def _candidate_card(row: _CandidateRow) -> dict:
    """Only authorized, already-stored fields (spec section 12) — no
    exact address (none exists in this schema; ``Profile.location`` is
    already city/region-level free text, never a street address), no
    password/auth data, no other recruiter's private notes."""
    latest_applicant = max(row.applicants, key=lambda a: a.created_at, default=None)
    return {
        "id": row.user.id,
        "full_name": row.user.full_name,
        "headline": row.career.target_role if row.career else None,
        "top_skills": sorted(row.skills)[:12],
        "experience_level": row.career.experience_level if row.career else None,
        "location": row.profile.location if row.profile else None,
        "education": row.profile.highest_qualification if row.profile else None,
        "graduation_year": row.profile.graduation_year if row.profile else None,
        "has_resume": row.resume is not None,
        "profile_completeness": row.completeness,
        "last_active_at": row.last_seen_at,
        "applications": [
            {"applicant_id": a.id, "job_id": a.job_id, "status": a.status, "pipeline_stage": a.pipeline_stage, "applied_at": a.created_at}
            for a in sorted(row.applicants, key=lambda a: a.created_at, reverse=True)
        ],
        "discoverable_via": (
            "application" if row.applicants else "opted_in"
        ),
        "actions": {
            # "Shortlist" (spec section 18) only exists for a candidate
            # who already has an Applicant row for one of this
            # recruiter's jobs — it reuses the existing V16/V18.2
            # PATCH /recruiter/applicants/{id}/stage endpoint rather
            # than inventing a second pipeline-entry mechanism for an
            # opted-in-but-not-applied candidate, which the spec
            # explicitly defers to V24.3.
            "can_shortlist": latest_applicant is not None,
            "shortlist_applicant_id": latest_applicant.id if latest_applicant else None,
            "can_view_application": latest_applicant is not None,
        },
    }


@router.get("/candidates")
def search_candidates(
    q: str | None = Query(default=None, max_length=200, description="Free-text: name, skills, headline, location"),
    skills: list[str] | None = Query(default=None),
    skills_mode: str = Query(default="any", pattern="^(any|all)$"),
    min_experience_years: float | None = Query(default=None, ge=0, le=60),
    max_experience_years: float | None = Query(default=None, ge=0, le=60),
    location: str | None = Query(default=None, max_length=120),
    education: str | None = Query(default=None, max_length=160),
    application_status: str | None = Query(default=None, max_length=30),
    resume_available: bool | None = Query(default=None),
    min_profile_completeness: int | None = Query(default=None, ge=0, le=100),
    # Allow-listed sort fields only (spec section 22) — never an
    # arbitrary column name from the request.
    sort_by: str = Query(default="profile_completeness", pattern="^(profile_completeness|experience|recently_active|name)$"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    """The main candidate-discovery endpoint (spec sections 2-8; also
    covers the "search" endpoint listed separately in section 26 —
    kept as one route with a ``q`` param rather than a duplicate,
    same reasoning as V24.1's job-list enrichment).

    Every filter here runs against ``_authorized_candidate_ids``'s
    result, never the full ``users`` table — see that function's
    docstring for why this can never become a full-table scan (spec
    sections 2, 21)."""
    candidate_ids = _authorized_candidate_ids(db, recruiter)
    rows = _load_candidate_rows(db, recruiter, candidate_ids)

    if q:
        needle = normalize_text(q)
        terms = needle.split(" ")

        def _matches_q(row: _CandidateRow) -> bool:
            haystack = normalize_text(
                " ".join(
                    filter(
                        None,
                        [
                            row.user.full_name,
                            row.career.target_role if row.career else None,
                            row.profile.location if row.profile else None,
                            row.profile.highest_qualification if row.profile else None,
                            " ".join(row.skills),
                        ],
                    )
                )
            )
            return all(t in haystack for t in terms)

        rows = [r for r in rows if _matches_q(r)]

    if skills:
        wanted = set(normalize_skills(db, skills))
        if wanted:
            if skills_mode == "all":
                rows = [r for r in rows if wanted.issubset(r.skills)]
            else:
                rows = [r for r in rows if wanted & r.skills]

    if location:
        loc_needle = normalize_location(location)
        rows = [
            r for r in rows
            if r.profile and loc_needle and loc_needle in normalize_location(r.profile.location)
        ]

    if education:
        edu_needle = normalize_text(education)
        rows = [
            r for r in rows
            if r.profile and r.profile.highest_qualification and edu_needle in normalize_text(r.profile.highest_qualification)
        ]

    if application_status:
        rows = [r for r in rows if any(a.status == application_status for a in r.applicants)]

    if resume_available is not None:
        rows = [r for r in rows if (r.resume is not None) == resume_available]

    if min_profile_completeness is not None:
        rows = [r for r in rows if r.completeness >= min_profile_completeness]

    if min_experience_years is not None or max_experience_years is not None:
        lo = min_experience_years if min_experience_years is not None else 0
        hi = max_experience_years if max_experience_years is not None else 999

        def _band_overlaps(row: _CandidateRow) -> bool:
            band = _experience_band(row.career.experience_level if row.career else None)
            if band is None:
                return False  # unknown experience is excluded, never guessed
            _, band_lo, band_hi = band
            return band_lo <= hi and band_hi >= lo

        rows = [r for r in rows if _band_overlaps(r)]

    reverse = sort_dir == "desc"
    if sort_by == "experience":
        rows.sort(key=lambda r: _EXPERIENCE_RANK.get((r.career.experience_level or "").lower(), -1), reverse=reverse)
    elif sort_by == "recently_active":
        rows.sort(key=lambda r: r.last_seen_at or datetime.min, reverse=reverse)
    elif sort_by == "name":
        rows.sort(key=lambda r: (r.user.full_name or "").lower(), reverse=reverse)
    else:
        rows.sort(key=lambda r: r.completeness, reverse=reverse)

    total = len(rows)
    start = (page - 1) * page_size
    page_rows = rows[start : start + page_size]
    return {"items": [_candidate_card(r) for r in page_rows], "total": total, "page": page, "page_size": page_size}


@router.get("/candidates/{candidate_id}")
def candidate_detail(candidate_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Full authorized detail view (spec section 13). Deliberately
    excludes: password/auth fields, exact address (doesn't exist in
    this schema), any other recruiter's ``ApplicantNote`` rows (notes
    are scoped to the applicant relationship, not exposed here at
    all — a recruiter without an application relationship to this
    candidate sees no notes; a recruiter *with* one still only sees
    their own team's notes via the existing
    ``GET /recruiter/applicants/{id}`` endpoint, unchanged)."""
    ids = _authorized_candidate_ids(db, recruiter)
    if candidate_id not in ids:
        raise HTTPException(404, "Candidate not found")
    rows = _load_candidate_rows(db, recruiter, {candidate_id})
    if not rows:
        raise HTTPException(404, "Candidate not found")
    row = rows[0]
    card = _candidate_card(row)
    card["resume"] = (
        {
            "original_filename": row.resume.original_filename,
            "uploaded_at": row.resume.uploaded_at,
            "extracted_text": row.resume.extracted_text,
        }
        if row.resume
        else None
    )
    card["preferred_roles"] = row.profile.preferred_roles if row.profile else None
    card["preferred_locations"] = row.profile.preferred_locations if row.profile else None
    card["career_goal"] = row.career.career_goal if row.career else None
    log_audit(db, action="view_candidate_profile", entity_type="user", entity_id=str(candidate_id))
    if row.resume:
        log_audit(db, action="access_candidate_resume", entity_type="resume", entity_id=str(candidate_id))
    db.commit()
    return card


def _title_match(row: _CandidateRow, job: Job) -> rec_matching.ComponentScore:
    wanted = normalize_text(job.title)
    candidates_text = normalize_text(
        " ".join(filter(None, [row.career.target_role if row.career else None] + (
            (row.profile.preferred_roles.split(",") if row.profile and row.profile.preferred_roles else [])
        )))
    )
    if not candidates_text:
        return rec_matching.ComponentScore(False, None, "No target role/preferred role on file to compare")
    overlap = bool(set(wanted.split(" ")) & set(candidates_text.split(" ")))
    return rec_matching.ComponentScore(
        True, 80 if overlap else 30,
        f"Candidate's target/preferred role {'overlaps with' if overlap else 'does not clearly overlap with'} '{job.title}'",
    )


_RECRUITER_MATCH_WEIGHTS = {"skill": 0.40, "experience": 0.20, "education": 0.15, "location": 0.15, "title": 0.10}


def _recruiter_match_score(match: rec_matching.MatchResult, title: rec_matching.ComponentScore) -> tuple[int, list[str]]:
    """Composes a recruiter-facing 0-100 score from a subset of the
    existing, deterministic MatchResult components (spec section 10) —
    career_goal/work_mode/salary/recency/behavior/deadline_urgency
    (candidate-recommendation-specific components) are intentionally
    excluded, since a recruiter judging a candidate doesn't care how
    recently the job was posted or the candidate's own salary
    preference relative to it. Weight redistribution mirrors
    app.recommendations.scoring's rule: an unavailable component's
    weight is redistributed across the available ones, never treated
    as zero."""
    components = {"skill": match.skill, "experience": match.experience, "education": match.education, "location": match.location, "title": title}
    available = {k: v for k, v in components.items() if v.available and v.score is not None}
    if not available:
        return 0, ["No comparable signals on file for this candidate yet"]
    total_weight = sum(_RECRUITER_MATCH_WEIGHTS[k] for k in available) or 1.0
    overall = round(sum(available[k].score * (_RECRUITER_MATCH_WEIGHTS[k] / total_weight) for k in available))

    reasons: list[str] = []
    if match.skill.available:
        if match.matched_skills:
            reasons.append(f"+ {len(match.matched_skills)}/{len(match.matched_skills) + len(match.missing_skills)} required/preferred skill(s) matched")
        if match.missing_skills:
            reasons.append(f"- Missing: {', '.join(match.missing_skills[:5])}")
    for key in ("experience", "education", "location"):
        comp = components[key]
        if comp.available:
            reasons.append(("+ " if (comp.score or 0) >= 60 else "- ") + comp.reason)
    if title.available:
        reasons.append(("+ " if (title.score or 0) >= 60 else "- ") + title.reason)
    return min(100, max(0, overall)), reasons


@router.get("/jobs/{job_id}/candidate-matches")
def job_candidate_matches(
    job_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    """"Find candidates for this job" (spec section 9). Reuses the
    V21.3/21.4 recommendation engine's own feature extraction/matching
    (``app.recommendations.candidate_features``/``job_features``/
    ``matching`` — the exact same code the candidate-facing job
    recommender uses in the other direction) rather than building a
    second scoring engine. See ``_recruiter_match_score`` for how the
    10-component ``MatchResult`` is narrowed to the subset that's
    meaningful for a recruiter judging a candidate."""
    owner_ids = team_owner_ids(db, recruiter)
    job = db.scalar(select(Job).where(Job.id == job_id, Job.owner_user_id.in_(owner_ids)))
    if job is None:
        raise HTTPException(404, "Job not found")

    candidate_ids = _authorized_candidate_ids(db, recruiter, job_id=job_id)
    truncated = len(candidate_ids) > MAX_CANDIDATES_TO_SCORE
    scored_ids = set(list(candidate_ids)[:MAX_CANDIDATES_TO_SCORE])
    rows = _load_candidate_rows(db, recruiter, scored_ids)
    job_feat = jf.build(job)

    results = []
    for row in rows:
        candidate_feat = cf.build(db, row.user.id)
        match = rec_matching.compute(candidate_feat, job, job_feat, behavior=None)
        title = _title_match(row, job)
        score, reasons = _recruiter_match_score(match, title)
        card = _candidate_card(row)
        card["match_score"] = score
        card["match_reasons"] = reasons
        results.append(card)

    results.sort(key=lambda c: c["match_score"], reverse=True)
    total = len(results)
    start = (page - 1) * page_size
    return {
        "items": results[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "truncated": truncated,  # true only if the authorized pool exceeded the safety cap
    }


_EXPERIENCE_QUERY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*years?", re.IGNORECASE)
_LOCATION_QUERY_RE = re.compile(r"\b(?:in|near|at|from)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})")


class NaturalLanguageParseIn(BaseModel):
    query: str = Field(min_length=2, max_length=500)


@router.post("/candidate-search/parse")
def parse_candidate_search(payload: NaturalLanguageParseIn, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Converts free text into the *same* structured filters
    ``GET /recruiter/candidates`` already accepts — deterministic,
    regex/catalog-based parsing only (spec sections 23-24): no LLM
    call is made in this version. This is a documented, honest scope
    decision (see docs/V24_2_CANDIDATE_DISCOVERY.md "AI usage"), not a
    stand-in for one — candidate discovery already works fully without
    it (section 23's actual requirement), and the client always has a
    safe fallback: pass the raw query back as ``q`` if ``parsed`` is
    false or the extracted filters look too sparse to be useful. This
    endpoint never constructs or executes SQL from the input — it only
    ever produces a JSON filter object that the caller then passes,
    unchanged, to the same validated/allow-listed query parameters
    ``search_candidates`` above already enforces."""
    text = payload.query

    experience_match = _EXPERIENCE_QUERY_RE.search(text)
    min_experience_years = float(experience_match.group(1)) if experience_match else None

    location_match = _LOCATION_QUERY_RE.search(text)
    location = location_match.group(1).strip() if location_match else None

    # Skill extraction: try 1-3 word windows against the real Skill
    # catalog (exact/alias match only — same engine as everywhere else
    # in this codebase; see app.skill_intelligence.normalization's
    # module docstring on why this never fuzzy-matches or invents a
    # skill). Windows already claimed by a longer match are skipped so
    # "Spring Boot" isn't also reported as a spurious "Spring".
    words = re.findall(r"[A-Za-z][A-Za-z0-9+.#]*", text)
    candidates: list[tuple[int, int, str]] = []  # (start, end, phrase)
    for size in (3, 2, 1):
        for i in range(len(words) - size + 1):
            candidates.append((i, i + size, " ".join(words[i : i + size])))
    resolved, _unrecognized = resolve_many(db, [c[2] for c in candidates])
    resolved_texts = {r.input_text.lower() for r in resolved}
    claimed: set[int] = set()
    skills: list[str] = []
    seen_canonical: set[str] = set()
    for start, end, phrase in sorted(candidates, key=lambda c: c[0] - c[1]):  # longest windows first
        if phrase.lower() not in resolved_texts:
            continue
        if claimed & set(range(start, end)):
            continue
        match = next((r for r in resolved if r.input_text.lower() == phrase.lower()), None)
        if match and match.skill.canonical_name not in seen_canonical:
            skills.append(match.skill.display_name)  # human-facing name; dedupe below is on the canonical key
            seen_canonical.add(match.skill.canonical_name)
            claimed.update(range(start, end))

    parsed = bool(skills or min_experience_years is not None or location)
    filters = {
        "skills": skills or None,
        "min_experience_years": min_experience_years,
        "location": location,
    }
    return {
        "parsed": parsed,
        "filters": filters,
        "fallback_q": None if parsed else text,
        "note": (
            "Deterministic keyword/catalog parsing only — no AI call was made. "
            "If this looks incomplete, search with the raw text using `q` instead."
        ),
    }
