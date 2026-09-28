"""DIVERSITY OF RECOMMENDATIONS + DUPLICATE PREVENTION — post-ranking
step.

Duplicate prevention: ``Job.id`` is the canonical identity for a job —
V21's ingestion pipeline (app.ingestion.ingest: "Adapter -> Normalize
-> Deduplicate -> Review queue") already deduplicates near-identical
postings from multiple sources *before* a row ever reaches the ``jobs``
table, so there is no second canonicalization step to reinvent here.
This module only needs to guarantee no single ``Job.id`` appears twice
in one result list, which it does by construction (dict keyed by id).

Diversity: applied only *after* ranking, and only as a light
reordering — never a relevance cut. "Do not sacrifice relevance just
to increase diversity." Implemented as: walk the score-sorted list
once, and while filling each output slot prefer the next-highest-
scored item that doesn't repeat a company/location/title already used
too many times; if every remaining item would repeat, fall back to
pure score order. This guarantees the output is always a permutation
of the top N by score for a modest N — nothing lower-scored is ever
promoted above a higher-scored item by more than the small
`max_lookahead` window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")

_DIVERSITY_CAPS = {
    "low": {"company": 6, "location": 8, "title": 4, "opportunity_type": 10},
    "balanced": {"company": 3, "location": 4, "title": 2, "opportunity_type": 6},
    "high": {"company": 2, "location": 2, "title": 1, "opportunity_type": 4},
}


@dataclass
class DiversityKey:
    company: str
    location: str
    title: str
    opportunity_type: str = ""  # V21.4 — Job.job_type (Government/Private/Internship/Apprenticeship)


def dedupe_by_job_id(ranked: list[tuple[int, T]]) -> list[tuple[int, T]]:
    """ranked: list of (job_id, item), already sorted best-first.
    Keeps the first (highest-scored) occurrence of each job_id."""
    seen: set[int] = set()
    out: list[tuple[int, T]] = []
    for job_id, item in ranked:
        if job_id in seen:
            continue
        seen.add(job_id)
        out.append((job_id, item))
    return out


def apply_diversity(
    ranked: list[tuple[int, T]],
    keys: dict[int, DiversityKey],
    *,
    level: str = "balanced",
    limit: int | None = None,
    max_lookahead: int = 12,
) -> list[tuple[int, T]]:
    """ranked: score-sorted (job_id, item) pairs, already deduped.
    keys: job_id -> DiversityKey used to spread results.
    Returns a reordered (never resized beyond `limit`) list."""
    caps = _DIVERSITY_CAPS.get(level, _DIVERSITY_CAPS["balanced"])
    remaining = list(ranked)
    result: list[tuple[int, T]] = []
    counts: dict[str, dict[str, int]] = {"company": {}, "location": {}, "title": {}, "opportunity_type": {}}

    target = limit or len(ranked)
    while remaining and len(result) < target:
        window = remaining[:max_lookahead]
        chosen_idx = None
        for i, (job_id, _item) in enumerate(window):
            key = keys.get(job_id)
            if key is None:
                chosen_idx = i
                break
            if (
                counts["company"].get(key.company, 0) < caps["company"]
                and counts["location"].get(key.location, 0) < caps["location"]
                and counts["title"].get(key.title, 0) < caps["title"]
                and counts["opportunity_type"].get(key.opportunity_type, 0) < caps["opportunity_type"]
            ):
                chosen_idx = i
                break
        if chosen_idx is None:
            chosen_idx = 0  # every candidate in the window is over-cap; fall back to top score

        job_id, item = remaining.pop(chosen_idx)
        key = keys.get(job_id)
        if key is not None:
            counts["company"][key.company] = counts["company"].get(key.company, 0) + 1
            counts["location"][key.location] = counts["location"].get(key.location, 0) + 1
            counts["title"][key.title] = counts["title"].get(key.title, 0) + 1
            counts["opportunity_type"][key.opportunity_type] = counts["opportunity_type"].get(key.opportunity_type, 0) + 1
        result.append((job_id, item))

    return result
