"""V21.3 — AI Job Recommendation Engine.

Centralized recommendation service, built entirely on top of existing
V21.1/V21.2 search infrastructure and V20.x AI engines (Resume
Intelligence, Skill Intelligence, Career Copilot). See
RECOMMENDATION_ARCHITECTURE.md for the full pipeline:

    Candidate Data -> Candidate Feature Builder -> Job Feature Builder
    -> Candidate-Job Matching -> Recommendation Scoring -> Ranking
    -> Explainable Recommendations

Nothing outside this package should compute a recommendation score or
build a "Jobs For You" list directly — app.recommendations.service is
the one entry point, matching the precedent set by
app.search.service.run_search for V21.1.

Core ranking is 100% deterministic (no LLM, no embeddings required) —
see RECOMMENDATION_SCORING.md. Every score is explainable via
app.recommendations.explanations.
"""
