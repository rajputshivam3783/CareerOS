"""V21.1 — SEARCH PERMISSIONS. Search must never return more than the
existing RBAC (app.core.rbac) already lets the requesting actor see.
This module is the single place that turns "who is asking" into a SQL
predicate over ``search_index_documents`` — every query the provider
runs goes through ``visibility_clause`` first, so there's exactly one
place to audit for a permission leak rather than one per entity type.

Actors, and what they see (SEARCH_PERMISSIONS.md has the full table):

- Anonymous / candidate: ``visibility == "public"`` rows only.
- Recruiter: the above, plus their own ``owner_user_id`` rows
  regardless of visibility (their own draft/review postings and
  unpublished company profile).
- Admin / super_admin: everything — admins already see unpublished
  jobs via the existing moderation queue (app/api/admin.py), so search
  matching that is additive, not a new exposure.

SKILL documents are always public (there's no private skill in the
catalog), so they're excluded from the visibility filter entirely.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, or_

from app.core.security import ADMIN_ROLES
from app.models.domain import User
from app.search.document import EntityType
from app.search.models import SearchIndexDocument


@dataclass
class SearchActor:
    """Normalized view of "who is searching" — built once per request
    (see app.search.service) from the optional current_user dependency,
    so the rest of the search stack never has to think about JWTs."""

    user_id: int | None
    role: str  # "anonymous" / "candidate" / "recruiter" / "admin" / "super_admin"

    @classmethod
    def anonymous(cls) -> "SearchActor":
        return cls(user_id=None, role="anonymous")

    @classmethod
    def from_user(cls, user: User | None) -> "SearchActor":
        if user is None:
            return cls.anonymous()
        return cls(user_id=user.id, role=user.role)

    @property
    def is_admin(self) -> bool:
        return self.role in ADMIN_ROLES


def apply_visibility(stmt: Select, actor: SearchActor) -> Select:
    """Narrow a SearchIndexDocument select to what `actor` is allowed
    to see. Always-safe default: if in doubt, this only ever *removes*
    rows relative to an unfiltered query — never adds any."""
    if actor.is_admin:
        return stmt

    public_or_own = SearchIndexDocument.visibility == "public"
    if actor.user_id is not None:
        public_or_own = or_(public_or_own, SearchIndexDocument.owner_user_id == actor.user_id)

    # SKILL rows have no owner/visibility distinction worth enforcing —
    # always public — but the clause above already covers them since
    # every SKILL document is indexed with visibility="public".
    return stmt.where(public_or_own)


def allowed_entity_types(actor: SearchActor, requested: list[EntityType] | None) -> list[EntityType]:
    """V21.1 keeps every entity type visible to every actor (subject to
    the row-level visibility_clause above) — there is currently no
    entity type reserved for a specific role (e.g. a future
    CANDIDATE-profile-search entity would be recruiter/admin-only).
    Centralizing the check here means adding that restriction later is
    a one-line change in this function, not a hunt through the API
    layer."""
    if requested:
        return requested
    return list(EntityType)
