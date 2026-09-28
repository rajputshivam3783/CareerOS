"""V21.1 — SEARCH PROVIDER abstraction.

``SearchProvider`` is the interface app.search.service.SearchService
talks to. ``DatabaseSearchProvider`` is the only implementation today,
querying ``search_index_documents`` directly (exact/prefix/token/
phrase matching via SQL, case-insensitive, with lightweight typo
tolerance — see ``_typo_tolerant_terms``).

Per the spec: "Do NOT introduce Elasticsearch/OpenSearch solely for
the sake of the feature if the repository does not need it yet." This
repository doesn't yet have the query volume to justify that
operational cost. What it does need — and gets — is a real interface
boundary: SearchService and the API layer only ever call
``SearchProvider`` methods, never raw SQLAlchemy against
SearchIndexDocument directly, so a V21.2+
ElasticsearchSearchProvider/OpenSearchSearchProvider/etc. is a new
class implementing this interface, not a rewrite of
service.py/search.py.
"""

from __future__ import annotations

import base64
import json as _json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.search.document import EntityType
from app.search.models import SearchIndexDocument
from app.search.normalization import normalize_text, tokenize
from app.search.permissions import SearchActor, apply_visibility
from app.search.ranking import score_document


@dataclass
class SearchFilters:
    entity_types: list[EntityType] | None = None
    location: str | None = None
    organization: str | None = None
    category: str | None = None
    job_type: str | None = None
    employment_type: str | None = None
    work_mode: str | None = None
    experience: str | None = None
    education: str | None = None
    skills: list[str] | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    status: str | None = None
    posted_after: date | None = None
    deadline_before: date | None = None


@dataclass
class SearchPage:
    page: int = 1
    page_size: int = 20
    cursor: str | None = None


@dataclass
class ScoredDocument:
    document: SearchIndexDocument
    score: float
    factors: dict[str, float]


@dataclass
class SearchResult:
    items: list[ScoredDocument]
    total_count: int
    page: int
    page_size: int
    facets: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    next_cursor: str | None = None


# PAGINATION — cursor support. A V21.1 cursor is a base64 token
# encoding just enough to resume a *specific, already-computed* sorted
# result list at the item right after the last one the caller saw:
# the sort mode (so a cursor minted under "newest" can't silently be
# replayed under "salary") and the (entity_type, entity_id) of that
# last item.
#
# What this buys over page/offset: if a new document is inserted at
# the very top of the result order between two requests (a fresh job
# posted while someone is paging through "newest"), offset pagination
# silently reshows/skips items — a cursor doesn't, because "resume
# after this specific document" doesn't shift when unrelated rows are
# inserted elsewhere in the ordering.
#
# What this does NOT do: bypass the _CANDIDATE_CAP below, or turn
# "relevance" sort into a true DB-level keyset seek. Every sort mode
# in V21.1 re-derives its full ordering from the same bounded
# candidate set on every request (see search() below) — a cursor just
# changes *where in that freshly-computed list* the response starts,
# not how the list is produced. That's a real, honest constraint of
# staying on a database-backed provider rather than a dedicated search
# engine — see SEARCH_ARCHITECTURE.md.


def encode_cursor(sort: str, entity_type: str, entity_id: int) -> str:
    payload = _json.dumps({"sort": sort, "et": entity_type, "id": entity_id})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(token: str) -> dict | None:
    try:
        payload = base64.urlsafe_b64decode(token.encode()).decode()
        data = _json.loads(payload)
        if not isinstance(data, dict) or "sort" not in data or "et" not in data or "id" not in data:
            return None
        return data
    except Exception:
        # An invalid/tampered/stale cursor is never a 500 — treat it
        # like "no cursor" (start from the beginning) rather than
        # erroring, since a cursor crossing a reindex or an app
        # restart is an expected, recoverable case, not a bug.
        return None


# A short, curated set of single-character-edit typo classes for the
# most commonly mistyped tech/job terms — NOT a general fuzzy-matching
# model (the spec asks for "typo-tolerant search where practical", not
# a spell-checker). Extending this list is a one-line, reviewable
# change with a known, bounded effect, unlike edit-distance matching
# against the whole vocabulary which can silently surface unrelated
# results for a short query.
_TYPO_TOLERANT_EQUIVALENTS: dict[str, list[str]] = {
    "python": ["pyhton", "phyton"],
    "javascript": ["javascrip", "javascript"],
    "manager": ["managr", "mananger"],
    "developer": ["devloper", "developr"],
    "engineer": ["enginer", "engeneer"],
    "government": ["goverment", "govenment"],
    "recruitment": ["recruitement", "recruitmnet"],
}
_TYPO_LOOKUP: dict[str, str] = {
    variant: canon for canon, variants in _TYPO_TOLERANT_EQUIVALENTS.items() for variant in variants
}


def _typo_tolerant_terms(token: str) -> list[str]:
    corrected = _TYPO_LOOKUP.get(token)
    return [token, corrected] if corrected else [token]


class SearchProvider(ABC):
    @abstractmethod
    def search(
        self, db: Session, *, query: str, filters: SearchFilters, actor: SearchActor, page: SearchPage, sort: str
    ) -> SearchResult: ...

    @abstractmethod
    def autocomplete(
        self, db: Session, *, prefix: str, entity_types: list[EntityType] | None, actor: SearchActor, limit: int
    ) -> list[str]: ...

    @abstractmethod
    def autocomplete_grouped(
        self, db: Session, *, prefix: str, actor: SearchActor, limit_per_group: int
    ) -> dict[str, list[str]]: ...

    @abstractmethod
    def facets(
        self, db: Session, *, facet_fields: list[str], filters: SearchFilters, actor: SearchActor
    ) -> dict[str, list[tuple[str, int]]]: ...


class DatabaseSearchProvider(SearchProvider):
    """Provider backed directly by the application's own database
    (SQLite in dev, PostgreSQL in production — see app/db/session.py).
    Uses ``ilike`` for case-insensitive substring/prefix/phrase
    matching against the pre-normalized ``search_text`` column, and
    scores/re-ranks the (bounded, filtered) candidate set in Python
    via app.search.ranking — the candidate set is capped well below
    "the whole table" by the SQL filters below before ranking ever
    runs, so this stays fast without a dedicated search engine.
    """

    _CANDIDATE_CAP = 500

    def _base_query(self, filters: SearchFilters, actor: SearchActor) -> Select:
        stmt = select(SearchIndexDocument)
        stmt = apply_visibility(stmt, actor)

        # V21.2 RESULT QUALITY fix: "Never display expired opportunities
        # as active." A job stays status="published" until its owning
        # recruiter explicitly closes/archives it — nothing previously
        # stopped a listing whose deadline had already passed from
        # appearing indistinguishable from an active one. Applied
        # unconditionally (not just when deadline_before is used) since
        # this is a baseline quality guarantee, not an opt-in filter.
        # Non-job entities have deadline=NULL and are unaffected.
        stmt = stmt.where(or_(SearchIndexDocument.deadline.is_(None), SearchIndexDocument.deadline >= date.today()))

        if filters.entity_types:
            stmt = stmt.where(SearchIndexDocument.entity_type.in_([e.value for e in filters.entity_types]))
        if filters.location:
            stmt = stmt.where(SearchIndexDocument.location.ilike(f"%{filters.location}%"))
        if filters.organization:
            stmt = stmt.where(SearchIndexDocument.organization.ilike(f"%{filters.organization}%"))
        if filters.category:
            stmt = stmt.where(SearchIndexDocument.category.ilike(f"%{filters.category}%"))
        if filters.job_type:
            stmt = stmt.where(SearchIndexDocument.job_type.ilike(filters.job_type))
        if filters.employment_type:
            stmt = stmt.where(SearchIndexDocument.employment_type.ilike(filters.employment_type))
        if filters.work_mode:
            stmt = stmt.where(SearchIndexDocument.work_mode.ilike(filters.work_mode))
        if filters.experience:
            stmt = stmt.where(SearchIndexDocument.experience_required.ilike(f"%{filters.experience}%"))
        if filters.education:
            stmt = stmt.where(SearchIndexDocument.education.ilike(f"%{filters.education}%"))
        if filters.skills:
            for skill in filters.skills:
                stmt = stmt.where(SearchIndexDocument.skills_text.ilike(f"%{normalize_text(skill)}%"))
        if filters.salary_min is not None:
            stmt = stmt.where(
                (SearchIndexDocument.salary_max.is_(None)) | (SearchIndexDocument.salary_max >= filters.salary_min)
            )
        if filters.salary_max is not None:
            stmt = stmt.where(
                (SearchIndexDocument.salary_min.is_(None)) | (SearchIndexDocument.salary_min <= filters.salary_max)
            )
        if filters.status:
            stmt = stmt.where(SearchIndexDocument.status == filters.status)
        if filters.posted_after:
            stmt = stmt.where(SearchIndexDocument.posted_date >= filters.posted_after)
        if filters.deadline_before:
            stmt = stmt.where(SearchIndexDocument.deadline <= filters.deadline_before)
        return stmt

    def _apply_query_text(self, stmt: Select, query: str) -> Select:
        tokens = tokenize(query)
        if not tokens:
            return stmt
        from sqlalchemy import or_

        for token in tokens:
            variants = _typo_tolerant_terms(token)
            stmt = stmt.where(or_(*[SearchIndexDocument.search_text.ilike(f"%{v}%") for v in variants]))
        return stmt

    def search(
        self, db: Session, *, query: str, filters: SearchFilters, actor: SearchActor, page: SearchPage, sort: str
    ) -> SearchResult:
        stmt = self._base_query(filters, actor)
        stmt = self._apply_query_text(stmt, query)

        # Bound the candidate set before scoring in Python. Deterministic
        # ordering (id desc = newest-inserted first) so the cap is stable
        # across calls rather than depending on unspecified row order.
        candidates = list(db.scalars(stmt.order_by(SearchIndexDocument.id.desc()).limit(self._CANDIDATE_CAP)).all())
        total_count = len(candidates)
        if total_count == self._CANDIDATE_CAP:
            # The cap was hit — get an accurate total via COUNT(*) instead
            # of reporting the cap itself as the total.
            count_stmt = self._apply_query_text(self._base_query(filters, actor), query)
            total_count = db.scalar(select(func.count()).select_from(count_stmt.subquery())) or total_count

        scored = [ScoredDocument(document=d, score=(s := score_document(query, d)).total_score, factors=s.factors) for d in candidates]

        if sort == "newest":
            scored.sort(key=lambda sd: sd.document.posted_date or date.min, reverse=True)
        elif sort == "oldest":
            scored.sort(key=lambda sd: sd.document.posted_date or date.max)
        elif sort == "deadline":
            scored.sort(key=lambda sd: sd.document.deadline or date.max)
        elif sort == "salary" or sort == "salary_desc":
            scored.sort(key=lambda sd: sd.document.salary_max or 0.0, reverse=True)
        elif sort == "salary_asc":
            # V21.2 SORTING: "Salary Low to High" — a job with no
            # salary data at all sorts last here (float('inf')),
            # matching the existing "no data = ranked last, never
            # fabricated" posture rather than sorting it first as if
            # it paid nothing.
            scored.sort(key=lambda sd: sd.document.salary_min if sd.document.salary_min is not None else float("inf"))
        else:  # "relevance" (default)
            scored.sort(key=lambda sd: sd.score, reverse=True)

        # PAGINATION — cursor takes precedence over page/offset when
        # both are given. See encode_cursor/decode_cursor's docstring
        # above for exactly what a cursor guarantees and what it
        # doesn't.
        start = (page.page - 1) * page.page_size
        report_page = page.page
        if page.cursor:
            decoded = decode_cursor(page.cursor)
            if decoded and decoded.get("sort") == sort:
                resume_after = next(
                    (
                        i
                        for i, sd in enumerate(scored)
                        if sd.document.entity_type == decoded["et"] and sd.document.entity_id == decoded["id"]
                    ),
                    None,
                )
                # If the cursor's item fell out of the current candidate
                # set (deleted, or pushed past _CANDIDATE_CAP by newer
                # inserts), resume from the top rather than erroring —
                # an expected, recoverable case, not a bug.
                start = resume_after + 1 if resume_after is not None else 0
            report_page = 1  # page number isn't meaningful once cursoring; caller should rely on next_cursor

        page_items = scored[start : start + page.page_size]
        next_cursor = None
        if page_items and (start + page.page_size) < len(scored):
            last = page_items[-1].document
            next_cursor = encode_cursor(sort, last.entity_type, last.entity_id)

        return SearchResult(
            items=page_items,
            total_count=total_count,
            page=report_page,
            page_size=page.page_size,
            next_cursor=next_cursor,
        )

    def autocomplete(
        self, db: Session, *, prefix: str, entity_types: list[EntityType] | None, actor: SearchActor, limit: int
    ) -> list[str]:
        prefix_norm = normalize_text(prefix)
        if not prefix_norm:
            return []

        stmt = select(SearchIndexDocument.title).distinct()
        stmt = apply_visibility(stmt, actor)
        if entity_types:
            stmt = stmt.where(SearchIndexDocument.entity_type.in_([e.value for e in entity_types]))
        stmt = stmt.where(SearchIndexDocument.title.ilike(f"{prefix}%")).limit(limit * 3)

        titles = [t for t in db.scalars(stmt).all() if t]
        # Re-rank by shortest-first (closer to what the person is
        # typing) after the DB does the prefix filtering, and dedupe
        # case-insensitively.
        seen: set[str] = set()
        ordered: list[str] = []
        for title in sorted(titles, key=len):
            key = title.lower()
            if key not in seen:
                seen.add(key)
                ordered.append(title)
            if len(ordered) >= limit:
                break
        return ordered

    def autocomplete_grouped(
        self, db: Session, *, prefix: str, actor: SearchActor, limit_per_group: int
    ) -> dict[str, list[str]]:
        """V21.2 — AUTOCOMPLETE 'Group suggestions by type'. Reuses the
        exact same title-prefix-match machinery as ``autocomplete``
        above (no separate index, no separate query engine) — the
        grouping key is simply which ``entity_type`` each matched
        title belongs to, since a SearchIndexDocument's ``title``
        already means "job title" for a job-family row, "company
        name" for a COMPANY row, "organization name" for an
        ORGANIZATION row, and "skill name" for a SKILL row. A separate
        ``locations`` group additionally comes from the ``location``
        column (a title-prefix match wouldn't find a location match).
        Unauthorized/private entities never appear here — the same
        ``apply_visibility`` used by every other search codepath is
        applied to every query in this method."""

        prefix_norm = normalize_text(prefix)
        if not prefix_norm:
            return {}

        def _title_group(entity_types: list[EntityType]) -> list[str]:
            stmt = select(SearchIndexDocument.title).distinct()
            stmt = apply_visibility(stmt, actor)
            stmt = stmt.where(SearchIndexDocument.entity_type.in_([e.value for e in entity_types]))
            stmt = stmt.where(SearchIndexDocument.title.ilike(f"{prefix}%")).limit(limit_per_group * 3)
            titles = sorted({t for t in db.scalars(stmt).all() if t}, key=len)
            return titles[:limit_per_group]

        job_titles = _title_group([EntityType.JOB, EntityType.GOVERNMENT_RECRUITMENT, EntityType.INTERNSHIP, EntityType.APPRENTICESHIP])
        companies = _title_group([EntityType.COMPANY])
        organizations = _title_group([EntityType.ORGANIZATION])
        skills = _title_group([EntityType.SKILL])

        loc_stmt = select(SearchIndexDocument.location).distinct()
        loc_stmt = apply_visibility(loc_stmt, actor)
        loc_stmt = loc_stmt.where(SearchIndexDocument.location.is_not(None))
        loc_stmt = loc_stmt.where(SearchIndexDocument.location.ilike(f"{prefix}%")).limit(limit_per_group * 3)
        locations = sorted({loc for loc in db.scalars(loc_stmt).all() if loc}, key=len)[:limit_per_group]

        groups = {
            "job_titles": job_titles,
            "companies": companies,
            "organizations": organizations,
            "skills": skills,
            "locations": locations,
        }
        return {k: v for k, v in groups.items() if v}

    def facets(
        self, db: Session, *, facet_fields: list[str], filters: SearchFilters, actor: SearchActor
    ) -> dict[str, list[tuple[str, int]]]:
        field_map = {
            "job_type": SearchIndexDocument.job_type,
            "location": SearchIndexDocument.location,
            "organization": SearchIndexDocument.organization,
            "category": SearchIndexDocument.category,
            "experience": SearchIndexDocument.experience_required,
            "entity_type": SearchIndexDocument.entity_type,
        }
        results: dict[str, list[tuple[str, int]]] = {}
        for facet in facet_fields:
            column = field_map.get(facet)
            if column is None:
                continue
            stmt = self._base_query(filters, actor)
            stmt = stmt.where(column.is_not(None)).group_by(column).with_only_columns(column, func.count())
            rows = db.execute(stmt.order_by(func.count().desc()).limit(20)).all()
            results[facet] = [(row[0], row[1]) for row in rows]
        return results
