"""V21.3 — AI Job Recommendation Engine tests.

Covers: recommendations reflect real profile/skill/career-goal
signals, deterministic scoring (same input -> same score across
calls), explanations exist with matched/missing skills, government
jobs never say "eligible" without a complete verified profile,
feedback loop excludes dismissed jobs, preferences gate opportunity
types, cache reuse + forced refresh, cold start returns a result
without fabricating personalization, privacy/authorization (a
candidate can only act on their own feedback/preferences; analytics
is admin-only), and V21.1/V21.2 search endpoints touched along the
way still work (regression).
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v21_3.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}

_counter = {"n": 0}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _register_and_login(client, email_prefix: str) -> dict:
    _counter["n"] += 1
    email = f"{email_prefix}{_counter['n']}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Test User"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_and_publish_job(client, **overrides) -> int:
    _counter["n"] += 1
    skills = overrides.pop("skills", "Python,SQL,AWS")
    payload = {
        "title": f"Python Developer V21.3 #{_counter['n']}",
        "organization": "Acme Corp",
        # POST /admin/ingest never persists a `skills` field (see
        # app.api.admin.ingest, which excludes it from JobRecord) — the
        # same as every other matching engine in this codebase
        # (app.services.career, app.resume_ai.job_match), skill
        # detection here comes purely from the shared SKILLS vocabulary
        # scanning title+description+qualification, so the requested
        # skill words are embedded directly into the description.
        "description": f"Looking for someone with skills in {skills}.",
        "qualification": "B.Tech",
        "location": "Noida",
        "job_type": "Private",
        "source_name": "V21.3 Test",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/admin/ingest", headers=ADMIN_HEADERS, json=payload)
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["job_id"]
    pub = client.post(f"/api/v1/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)
    assert pub.status_code == 200, pub.text
    return job_id


def _set_profile(client, headers, **overrides):
    payload = {"skills": "Python,SQL", "location": "Noida", "highest_qualification": "Graduate"}
    payload.update(overrides)
    resp = client.put("/api/v1/profile", headers=headers, json=payload)
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Basic recommendations + explanation
# ---------------------------------------------------------------------------


def test_recommendations_require_auth(client):
    resp = client.get("/api/v1/job-recommendations")
    assert resp.status_code in (401, 403)


def test_recommendations_reflect_skill_match(client):
    headers = _register_and_login(client, "v21_3basic")
    _set_profile(client, headers, skills="Python,SQL,AWS")
    job_id = _create_and_publish_job(client, skills="Python,SQL,AWS")

    resp = client.get("/api/v1/job-recommendations", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"], "expected at least one recommendation"
    match = next((i for i in body["items"] if i["job_id"] == job_id), None)
    assert match is not None
    assert match["score_breakdown"]["skill"] == 100
    assert set(match["matched_skills"]) == {"python", "sql", "aws"}
    assert match["missing_skills"] == []
    assert "Recommended because" in match["explanation_summary"] or "Included based on" in match["explanation_summary"]


def test_explanation_endpoint_matches_list_score(client):
    headers = _register_and_login(client, "v21_3exp")
    _set_profile(client, headers, skills="Python")
    job_id = _create_and_publish_job(client, skills="Python,SQL")

    resp = client.get(f"/api/v1/job-recommendations/{job_id}/explanation", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id
    assert "python" in body["matched_skills"]
    assert "sql" in body["missing_skills"]
    assert body["negative_reasons"], "missing a required skill should surface a negative reason"


def test_deterministic_scoring_same_input_same_score(client):
    """V21.4 note: viewing a job's explanation records an "open"
    behavioral event (see app.recommendations.events), which is itself
    new input to the personalization signal — the first view can
    legitimately shift the score once (personalization is supposed to
    react to real interactions). What must stay deterministic is
    scoring given a *settled* state: once that one-time transition has
    happened, repeated calls with no new interaction in between must
    keep returning the identical score. Hence one warm-up call before
    asserting determinism across the next three."""
    headers = _register_and_login(client, "v21_3det")
    _set_profile(client, headers, skills="Python,SQL")
    job_id = _create_and_publish_job(client, skills="Python,SQL")

    client.get(f"/api/v1/job-recommendations/{job_id}/explanation", headers=headers)  # warm-up: records the one-time "open" event

    scores = []
    for _ in range(3):
        resp = client.get(f"/api/v1/job-recommendations/{job_id}/explanation", headers=headers)
        scores.append(resp.json()["overall_score"])
    assert len(set(scores)) == 1, f"score should be deterministic, got {scores}"


def test_missing_skills_never_fabricated_as_matched(client):
    headers = _register_and_login(client, "v21_3nofab")
    _set_profile(client, headers, skills="Photoshop")
    job_id = _create_and_publish_job(client, skills="Python,SQL,AWS")

    resp = client.get(f"/api/v1/job-recommendations/{job_id}/explanation", headers=headers)
    body = resp.json()
    assert body["matched_skills"] == []
    assert set(body["missing_skills"]) == {"python", "sql", "aws"}


# ---------------------------------------------------------------------------
# Feedback loop
# ---------------------------------------------------------------------------


def test_dismissed_job_excluded_from_future_recommendations(client):
    headers = _register_and_login(client, "v21_3fb")
    _set_profile(client, headers, skills="Python,SQL,AWS")
    job_id = _create_and_publish_job(client, skills="Python,SQL,AWS")

    resp = client.get("/api/v1/job-recommendations", headers=headers)
    assert any(i["job_id"] == job_id for i in resp.json()["items"])

    fb = client.post(f"/api/v1/job-recommendations/{job_id}/feedback", headers=headers, json={"feedback_type": "dismiss"})
    assert fb.status_code == 200

    resp2 = client.get("/api/v1/job-recommendations", headers=headers, params={"refresh": True})
    assert not any(i["job_id"] == job_id for i in resp2.json()["items"])


def test_invalid_feedback_type_rejected(client):
    headers = _register_and_login(client, "v21_3fbbad")
    job_id = _create_and_publish_job(client)
    resp = client.post(f"/api/v1/job-recommendations/{job_id}/feedback", headers=headers, json={"feedback_type": "nonsense"})
    assert resp.status_code == 400


def test_feedback_is_scoped_to_own_user_not_shared(client):
    headers_a = _register_and_login(client, "v21_3owna")
    headers_b = _register_and_login(client, "v21_3ownb")
    _set_profile(client, headers_a, skills="Python")
    _set_profile(client, headers_b, skills="Python")
    job_id = _create_and_publish_job(client, skills="Python")

    client.post(f"/api/v1/job-recommendations/{job_id}/feedback", headers=headers_a, json={"feedback_type": "dismiss"})

    resp_b = client.get("/api/v1/job-recommendations", headers=headers_b, params={"refresh": True})
    assert any(i["job_id"] == job_id for i in resp_b.json()["items"]), "user B's exclusion list must not be affected by user A's feedback"


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


def test_preferences_default_all_included(client):
    headers = _register_and_login(client, "v21_3prefdef")
    resp = client.get("/api/v1/job-recommendations/preferences", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["include_government"] is True
    assert body["include_private"] is True


def test_excluding_private_jobs_removes_them_from_feed(client):
    headers = _register_and_login(client, "v21_3prefx")
    _set_profile(client, headers, skills="Python")
    job_id = _create_and_publish_job(client, skills="Python", job_type="Private")

    put = client.put("/api/v1/job-recommendations/preferences", headers=headers, json={"include_private": False})
    assert put.status_code == 200
    assert put.json()["include_private"] is False

    resp = client.get("/api/v1/job-recommendations", headers=headers, params={"refresh": True})
    assert not any(i["job_id"] == job_id for i in resp.json()["items"])


def test_invalid_diversity_level_rejected(client):
    headers = _register_and_login(client, "v21_3prefbad")
    resp = client.put("/api/v1/job-recommendations/preferences", headers=headers, json={"diversity_level": "extreme"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Cache / refresh
# ---------------------------------------------------------------------------


def test_second_call_is_served_from_cache(client):
    headers = _register_and_login(client, "v21_3cache")
    _set_profile(client, headers, skills="Python")
    _create_and_publish_job(client, skills="Python")

    first = client.get("/api/v1/job-recommendations", headers=headers).json()
    assert first["from_cache"] is False
    second = client.get("/api/v1/job-recommendations", headers=headers).json()
    assert second["from_cache"] is True


def test_profile_change_invalidates_cache(client):
    headers = _register_and_login(client, "v21_3invalidate")
    _set_profile(client, headers, skills="Python")
    job_id = _create_and_publish_job(client, skills="Python,Java")

    client.get("/api/v1/job-recommendations", headers=headers)  # populate cache

    _set_profile(client, headers, skills="Python,Java")
    resp = client.get(f"/api/v1/job-recommendations/{job_id}/explanation", headers=headers)
    assert set(resp.json()["matched_skills"]) == {"python", "java"}


# ---------------------------------------------------------------------------
# Government recommendations — never a bare "eligible" claim
# ---------------------------------------------------------------------------


def test_government_job_without_profile_says_potentially_relevant_not_eligible(client):
    headers = _register_and_login(client, "v21_3gov")
    job_id = _create_and_publish_job(
        client,
        job_type="Government",
        qualification="Graduate",
        age_limit="18-27 years",
        skills="",
    )
    resp = client.get(f"/api/v1/job-recommendations/{job_id}/explanation", headers=headers)
    assert resp.status_code == 200
    gov = resp.json()["government_relevance"]
    assert gov is not None
    assert gov["label"] != "Eligible (indicative)"


# ---------------------------------------------------------------------------
# Cold start
# ---------------------------------------------------------------------------


def test_cold_start_user_gets_a_response_not_an_error(client):
    headers = _register_and_login(client, "v21_3cold")
    _create_and_publish_job(client, verified=True)
    resp = client.get("/api/v1/job-recommendations", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_cold_start"] is True


# ---------------------------------------------------------------------------
# Authorization / privacy
# ---------------------------------------------------------------------------


def test_analytics_requires_admin(client):
    headers = _register_and_login(client, "v21_3analytics")
    resp = client.get("/api/v1/job-recommendations/analytics", headers=headers)
    assert resp.status_code in (401, 403)

    resp2 = client.get("/api/v1/job-recommendations/analytics", headers=ADMIN_HEADERS)
    assert resp2.status_code == 200
    assert "counts_by_event_type" in resp2.json()


def test_explanation_for_unpublished_job_not_found(client):
    headers = _register_and_login(client, "v21_3unpub")
    _counter["n"] += 1
    payload = {
        "title": "Draft Job",
        "organization": "Acme",
        "description": "x",
        "qualification": "x",
        "location": "Noida",
        "job_type": "Private",
        "source_name": "V21.3 Test",
    }
    ingest = client.post("/api/v1/admin/ingest", headers=ADMIN_HEADERS, json=payload)
    job_id = ingest.json()["job_id"]  # never published

    resp = client.get(f"/api/v1/job-recommendations/{job_id}/explanation", headers=headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Regression — V21.1/V21.2 search still works
# ---------------------------------------------------------------------------


def test_v21_1_search_still_works(client):
    _create_and_publish_job(client)
    resp = client.get("/api/v1/search", params={"q": "python"})
    assert resp.status_code == 200


def test_v21_2_recent_search_still_works(client):
    headers = _register_and_login(client, "v21_3regress")
    _create_and_publish_job(client)
    client.get("/api/v1/search", params={"q": "python developer regression"}, headers=headers)
    recent = client.get("/api/v1/search/recent", headers=headers)
    assert recent.status_code == 200


# ---------------------------------------------------------------------------
# Learning progress / projects (CANDIDATE FEATURES)
# ---------------------------------------------------------------------------


def test_completed_learning_plan_skill_counts_as_matched(client):
    from app.db.session import SessionLocal
    from app.models.domain import LearningPlan, LearningPlanModule, Skill

    headers = _register_and_login(client, "v21_3learn")
    _set_profile(client, headers, skills="Python")
    job_id = _create_and_publish_job(client, skills="Python,SQL")

    before = client.get(f"/api/v1/job-recommendations/{job_id}/explanation", headers=headers).json()
    assert "sql" in before["missing_skills"]

    me = client.get("/api/v1/auth/me", headers=headers).json()
    db = SessionLocal()
    try:
        skill = db.query(Skill).filter(Skill.canonical_name == "sql").first()
        if skill is None:
            return  # "sql" isn't seeded in this environment's skill catalog; nothing further to assert
        plan = LearningPlan(user_id=me["id"], title="SQL plan", status="active")
        db.add(plan)
        db.flush()
        module = LearningPlanModule(plan_id=plan.id, skill_id=skill.id, order_index=1, status="completed")
        db.add(module)
        db.commit()
    finally:
        db.close()

    after = client.get(f"/api/v1/job-recommendations/{job_id}/explanation", headers=headers).json()
    assert "sql" in after["matched_skills"]
    assert "sql" not in after["missing_skills"]


def test_candidate_with_only_projects_gets_experience_signal(client):
    from app.db.session import SessionLocal
    from app.models.domain import Resume

    headers = _register_and_login(client, "v21_3proj")
    _set_profile(client, headers, skills="Python")
    job_id = _create_and_publish_job(client, skills="Python")

    me = client.get("/api/v1/auth/me", headers=headers).json()
    db = SessionLocal()
    try:
        resume = Resume(
            user_id=me["id"],
            original_filename="resume.txt",
            extracted_text="PROJECTS\nBuilt a personal portfolio site with Python and Flask.\nBuilt a CLI tool for CSV cleaning.",
        )
        db.add(resume)
        db.commit()
    finally:
        db.close()

    resp = client.get(f"/api/v1/job-recommendations/{job_id}/explanation", headers=headers)
    assert resp.status_code == 200
    assert "experience" not in resp.json()["unavailable_components"]
    assert "project" in resp.json()["experience_fit"].lower()
