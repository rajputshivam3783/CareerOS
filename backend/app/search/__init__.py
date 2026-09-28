"""V21.1 — Unified Search Infrastructure.

Centralized search for CareerOS. Every entity type that needs to be
searchable (jobs — government/private/internship/apprenticeship —,
companies, government organizations, skills, learning resources) goes
through this one package rather than each feature area growing its
own search logic. See SEARCH_ARCHITECTURE.md for the full design.

Deliberately does NOT duplicate the existing Job / GovernmentOrganization
/ Organization / Skill / LearningResource models — those stay the
single source of truth. This package builds a derived, denormalized
*index* (``SearchIndexDocument``, see app.search.models) from them,
the same relationship a real Elasticsearch/OpenSearch index would have
to its source-of-truth database if/when V21.2+ swaps the provider.
"""
