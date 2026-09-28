"""V21.1 — normalization used before text ever reaches the index or a
query. Everything here is deterministic string processing — no AI
call, nothing fuzzy beyond simple token overlap, so results stay
explainable (SEARCH_RELEVANCE.md).

Reuses the existing V20.5 Skill Intelligence alias catalog
(app.skill_intelligence.normalization) for skill-name normalization
rather than inventing a second alias table, per the spec's "reuse V20
Skill Intelligence" instruction.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.skill_intelligence.normalization import resolve_many

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCTUATION_RE = re.compile(r"[^\w\s]")

# Common job-title variants -> a single canonical token, so "Sr." and
# "Senior" (etc.) match each other. Intentionally small and curated —
# adding an entry here is a one-line, reviewable change, unlike a
# fuzzy-matching model that could silently start conflating unrelated
# titles.
TITLE_VARIANT_ALIASES: dict[str, str] = {
    "sr": "senior",
    "sr.": "senior",
    "jr": "junior",
    "jr.": "junior",
    "swe": "software engineer",
    "sde": "software development engineer",
    "mgr": "manager",
    "asst": "assistant",
    "govt": "government",
}

# Common government/organization abbreviations -> full form.
ORGANIZATION_ALIASES: dict[str, str] = {
    "ssc": "staff selection commission",
    "upsc": "union public service commission",
    "ibps": "institute of banking personnel selection",
    "rrb": "railway recruitment board",
    "psu": "public sector undertaking",
}

# Common location aliases (abbreviation/short form -> canonical name).
LOCATION_ALIASES: dict[str, str] = {
    "blr": "bangalore",
    "bengaluru": "bangalore",
    "bom": "mumbai",
    "del": "delhi",
    "new delhi": "delhi",
    "hyd": "hyderabad",
    "wfh": "remote",
    "work from home": "remote",
}


def normalize_whitespace(value: str | None) -> str:
    if not value:
        return ""
    return _WHITESPACE_RE.sub(" ", value).strip()


def strip_punctuation(value: str | None) -> str:
    if not value:
        return ""
    return _PUNCTUATION_RE.sub(" ", value)


def normalize_text(value: str | None) -> str:
    """Lowercase, punctuation-stripped, whitespace-collapsed form used
    for both indexing and query parsing so the two sides compare on
    equal terms."""
    if not value:
        return ""
    return normalize_whitespace(strip_punctuation(value.lower()))


def _apply_alias_map(normalized_value: str, aliases: dict[str, str]) -> str:
    tokens = normalized_value.split(" ")
    mapped = [aliases.get(tok, tok) for tok in tokens]
    return normalize_whitespace(" ".join(mapped))


def normalize_title(value: str | None) -> str:
    return _apply_alias_map(normalize_text(value), TITLE_VARIANT_ALIASES)


def normalize_organization(value: str | None) -> str:
    return _apply_alias_map(normalize_text(value), ORGANIZATION_ALIASES)


def normalize_location(value: str | None) -> str:
    normalized = normalize_text(value)
    return LOCATION_ALIASES.get(normalized, normalized)


def normalize_skills(db: Session, raw_skills: list[str]) -> list[str]:
    """Resolve free-text skill names against the V20.5 Skill catalog
    (canonical name + alias table) where possible; a name with no
    catalog match is kept, lowercased and trimmed, rather than
    dropped, so search doesn't silently lose an entity's skill tag
    just because it hasn't been added to the catalog yet."""
    if not raw_skills:
        return []
    resolved, unrecognized = resolve_many(db, raw_skills)
    names = [r.skill.canonical_name.lower() for r in resolved]
    names.extend(normalize_text(u) for u in unrecognized if normalize_text(u))
    # De-duplicate, keep order stable.
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def build_search_text(*fields: str | None) -> str:
    """Concatenate arbitrary searchable fields into the single
    normalized blob stored on SearchIndexDocument.search_text, used
    for token/prefix/phrase matching by the database-backed
    provider."""
    parts = [normalize_text(f) for f in fields if f]
    return normalize_whitespace(" ".join(parts))


def tokenize(query: str) -> list[str]:
    return [t for t in normalize_text(query).split(" ") if t]
