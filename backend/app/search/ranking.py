"""V21.1 — SEARCH RELEVANCE. A deterministic baseline ranking: every
factor below is a plain, explainable computation over the query and
one SearchIndexDocument row — no learned weights, no AI-generated
score (the spec is explicit: "Do NOT use arbitrary AI-generated
scores. Every ranking factor must be explainable."). See
SEARCH_RELEVANCE.md for the factor table and weights, kept in sync
with WEIGHTS below.

This does not replace app.services.semantic_search's V6 TF-IDF
similarity ranking — that remains available for callers that
specifically want cosine-similarity-based job ranking (e.g. "find
jobs similar to this description"). This module is the general
keyword/filter search ranking used by the unified Search Service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.search.models import SearchIndexDocument
from app.search.normalization import normalize_text, tokenize

# Weights sum to 1.0 purely as a convention for readability — scores
# are relative (used only to sort, never shown as an absolute
# percentage to the user), so the sum isn't load-bearing.
WEIGHTS = {
    "exact_title_match": 0.30,
    "phrase_match": 0.15,
    "skill_match": 0.20,
    "organization_match": 0.10,
    "location_match": 0.10,
    "token_coverage": 0.10,
    "recency": 0.03,
    "entity_quality": 0.02,
}

_RECENCY_HALF_LIFE_DAYS = 30


@dataclass
class RankingExplanation:
    total_score: float
    factors: dict[str, float] = field(default_factory=dict)


def _recency_score(doc: SearchIndexDocument) -> float:
    reference = doc.posted_date or (doc.indexed_at.date() if doc.indexed_at else None)
    if not reference:
        return 0.0
    if isinstance(reference, datetime):
        reference = reference.date()
    age_days = max((date.today() - reference).days, 0)
    # Exponential decay, halving every _RECENCY_HALF_LIFE_DAYS days —
    # a 0-day-old posting scores 1.0, a 30-day-old one ~0.5, etc.
    return 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)


def score_document(query: str, doc: SearchIndexDocument) -> RankingExplanation:
    """Score one document against a (possibly empty) query. An empty
    query relies entirely on recency + entity_quality (i.e. "browse,
    newest/best-quality first"), matching how the SORTING requirement
    treats "Relevance" with no query text."""
    query_norm = normalize_text(query)
    query_tokens = tokenize(query)

    title_norm = normalize_text(doc.title)
    factors: dict[str, float] = {}

    factors["exact_title_match"] = 1.0 if query_norm and query_norm == title_norm else 0.0
    factors["phrase_match"] = 1.0 if query_norm and query_norm in (doc.search_text or "") else 0.0

    skills = (doc.skills_text or "").split(",") if doc.skills_text else []
    skills_norm = {normalize_text(s) for s in skills if s}
    if query_tokens:
        factors["skill_match"] = len(set(query_tokens) & skills_norm) / len(query_tokens)
    else:
        factors["skill_match"] = 0.0

    org_norm = normalize_text(doc.organization)
    factors["organization_match"] = (
        1.0 if query_norm and org_norm and (query_norm in org_norm or org_norm in query_norm) else 0.0
    )

    loc_norm = normalize_text(doc.location)
    factors["location_match"] = (
        1.0 if query_norm and loc_norm and (query_norm in loc_norm or loc_norm in query_norm) else 0.0
    )

    if query_tokens:
        doc_tokens = set((doc.search_text or "").split(" "))
        factors["token_coverage"] = len(set(query_tokens) & doc_tokens) / len(query_tokens)
    else:
        factors["token_coverage"] = 0.0

    factors["recency"] = _recency_score(doc)
    factors["entity_quality"] = max(0.0, min(1.0, doc.quality_score or 0.0))

    total = sum(WEIGHTS[name] * value for name, value in factors.items())
    return RankingExplanation(total_score=round(total, 6), factors=factors)
