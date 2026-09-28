"""V21.1 — Unified Search Infrastructure: persisted tables.

Two additive tables, neither of which touches or duplicates an
existing model:

``SearchIndexDocument`` — the search index itself. One row per
searchable entity (Job, GovernmentOrganization, Organization, Skill,
LearningResource), denormalized into a common shape so one query
engine can search across all of them. It is a *derived cache* built
by app.search.indexer from the real source-of-truth tables, never
the other way around — deleting every row here and calling
``reindex_all`` reconstructs it byte-for-byte from source data.

``SearchQueryLog`` — lightweight search analytics (V21.1 SEARCH
ANALYTICS requirement). Stores the query, filters, entity type,
result count and latency for later analysis (e.g. no-result-query
review). Deliberately does not store which user ran the query for
anonymous searches, and stores only the actor's role for
authenticated ones, since a full free-text search history per user is
sensitive data the spec didn't ask for ("Do not store sensitive query
data unnecessarily").
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SearchIndexDocument(Base):
    __tablename__ = "search_index_documents"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", name="uq_search_doc_entity"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    # See app.search.document.EntityType for the closed set of values.
    entity_type: Mapped[str] = mapped_column(String(30), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)

    title: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    organization: Mapped[str | None] = mapped_column(String(220), nullable=True, index=True)
    location: Mapped[str | None] = mapped_column(String(220), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # Only populated for JOB-family entity types (JOB / GOVERNMENT_RECRUITMENT
    # / INTERNSHIP / APPRENTICESHIP) — mirrors Job.job_type so a filter on
    # "job type" works without a join back to the jobs table.
    job_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    employment_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    work_mode: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    experience_required: Mapped[str | None] = mapped_column(String(120), nullable=True)
    education: Mapped[str | None] = mapped_column(String(220), nullable=True)
    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    ad_number: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    # Comma-joined, normalized (lowercase, alias-resolved) skill names —
    # see app.search.normalization.normalize_skills.
    skills_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)

    posted_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    # Normalized lifecycle status ("published" is the only value every
    # public search result has — see app.search.permissions).
    status: Mapped[str] = mapped_column(String(30), default="published", index=True)

    # public: visible to anyone. private: visible only to owner_user_id
    # (+ admins). restricted: visible to authenticated candidates but
    # not anonymous visitors (reserved for future use; unused in V21.1).
    visibility: Mapped[str] = mapped_column(String(20), default="public", index=True)
    owner_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    source: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Deterministic, explainable "entity quality" ranking input (e.g.
    # verified=1.0/unverified=0.0 for a Job; is_verified for a
    # LearningResource) — see app.search.ranking.
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)

    # JSON-encoded bag of entity-specific extras the API response wants
    # to pass through (e.g. a Job's apply_url) without widening this
    # table's fixed columns for a single entity type's needs.
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Normalized, whitespace/punctuation-collapsed, lowercased
    # concatenation of every searchable field, used for token / prefix
    # / phrase matching by the database-backed provider. See
    # app.search.normalization.build_search_text.
    search_text: Mapped[str] = mapped_column(Text, default="")

    indexed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SearchQueryLog(Base):
    __tablename__ = "search_query_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    query: Mapped[str] = mapped_column(String(500), default="")
    entity_types: Mapped[str | None] = mapped_column(String(300), nullable=True)  # comma-joined
    filters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    had_results: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "anonymous"/"candidate"/... — no user id
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class RecentSearch(Base):
    """V21.2 — per-user RECENT SEARCHES. Deliberately a separate table
    from SearchQueryLog above, not a repurposing of it: SearchQueryLog
    is intentionally anonymous (see its own docstring), while this is
    an explicit, user-owned feature the person can view/reuse/delete/
    clear (SEARCH HISTORY PRIVACY) — never surfaced to anyone but its
    owner and never to admins beyond aggregate operational data (which
    this table isn't used for at all).

    One row per distinct (user, normalized query + filters + entity
    types) combination — repeating an identical search moves its
    ``created_at`` up rather than creating a duplicate row, matching
    ordinary "recent searches" UX (see
    app.search.recent_searches.record). Capped per user at
    ``MAX_PER_USER`` in the service layer, not by a DB constraint."""

    __tablename__ = "recent_searches"
    __table_args__ = (UniqueConstraint("user_id", "search_key", name="uq_recent_search_user_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    query: Mapped[str] = mapped_column(String(500), default="")
    entity_types: Mapped[str | None] = mapped_column(String(300), nullable=True)  # comma-joined
    filters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Deterministic hash of (query, entity_types, filters) used only
    # for the uniqueness/upsert check above — never displayed.
    search_key: Mapped[str] = mapped_column(String(64), index=True)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
