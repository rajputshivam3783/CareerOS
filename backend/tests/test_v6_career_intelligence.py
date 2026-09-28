"""Unit tests for V6 semantic search ranking and the Career AI
narration fallback (no API key configured -> template summary)."""

from types import SimpleNamespace

from app.services.career_ai import generate_advice
from app.services.semantic_search import rank_by_similarity


def make_job(**overrides):
    defaults = dict(
        id=1,
        title="Backend Software Engineer",
        organization="Test Org",
        department=None,
        job_type="Private",
        description="Build and maintain Python and FastAPI backend services.",
        qualification="Bachelor's in Computer Science",
        category=None,
        selection_process=None,
        industry="Technology",
        location="India",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_semantic_search_ranks_relevant_job_higher():
    backend_job = make_job(
        id=1, title="Backend Engineer", description="Python, FastAPI, PostgreSQL, REST APIs."
    )
    design_job = make_job(
        id=2, title="Graphic Designer", description="Adobe Photoshop, Illustrator, branding, print design."
    )

    results = rank_by_similarity("looking for a python backend developer role", [backend_job, design_job])

    assert results[0]["job"].id == 1
    assert results[0]["score"] >= results[1]["score"]


def test_semantic_search_handles_empty_inputs_gracefully():
    assert rank_by_similarity("python", []) == []
    assert rank_by_similarity("   ", [make_job()]) == []


def test_career_ai_falls_back_to_template_without_api_key():
    job = make_job()
    eligibility_result = {"eligible": True, "reasons": ["Qualification matches"]}
    match_result = {"score": 82, "matched_skills": ["python", "sql"]}
    skill_gap_result = {"learn": ["docker", "kubernetes"]}

    result = generate_advice(job, None, eligibility_result, match_result, skill_gap_result)

    assert result["source"] == "template"
    assert "82" in result["advice"]
    assert "docker" in result["advice"]
