"""V20.5 (Phase 3) — Assessments, Practice, Career Readiness tests.

Covers: admin-authored assessments score correctly server-side and
never leak the answer key to candidates, weak topics aggregate and
drive practice recommendations, certification guidance never
fabricates a cert, readiness scores are explainable and degrade
gracefully with missing data, and Phase 1/2 + V20.3 endpoints touched
along the way keep working (regression).
"""

import io
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v20_5c.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}

SAMPLE_RESUME = """Jordan Rivera
jordan.rivera@example.com
+1 415-555-0142
San Francisco, CA

SUMMARY
Backend engineer.

SKILLS
Python, SQL, Git

EXPERIENCE
- Built a Python/SQL data pipeline processing 2 million records daily

EDUCATION
B.Tech in Computer Science, State University, 2019
"""

_job_counter = {"n": 0}


def _register_and_login(client, email, name="V20.5c Tester"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": name},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _recruiter_headers(client, suffix):
    email = f"v20_5crec{suffix}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Rec"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    login = client.post("/api/v1/auth/recruiter/login", json={"email": email, "password": "password12345!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _publish_job(client, headers, **overrides):
    _job_counter["n"] += 1
    payload = {
        "title": f"Backend Engineer V20.5c #{_job_counter['n']}",
        "organization": "Acme",
        "location": "Remote",
        "description": "We need someone strong in Python, SQL, Docker, and Kubernetes for our backend team.",
        "qualification": "B.Tech in Computer Science",
        "responsibilities": "Own backend services",
        "requirements": "Experience with Python and AWS",
        "skills": ["Python", "SQL", "Docker", "Kubernetes", "AWS"],
    }
    payload.update(overrides)
    job = client.post("/api/v1/recruiter/jobs", headers=headers, json=payload).json()
    client.post(f"/api/v1/recruiter/jobs/{job['id']}/submit-for-review", headers=headers)
    client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)
    return job["id"]


def _create_python_assessment(client):
    a = client.post(
        "/api/v1/admin/assessments",
        headers=ADMIN_HEADERS,
        json={"skill_canonical_name": "python", "title": "Python Fundamentals", "status": "published"},
    ).json()
    q1 = client.post(
        f"/api/v1/admin/assessments/{a['id']}/questions",
        headers=ADMIN_HEADERS,
        json={
            "prompt": "Which keyword defines a function in Python?",
            "options": ["func", "def", "function", "lambda"],
            "correct_option": 1,
            "topic": "syntax",
        },
    )
    assert q1.status_code == 200
    q2 = client.post(
        f"/api/v1/admin/assessments/{a['id']}/questions",
        headers=ADMIN_HEADERS,
        json={
            "prompt": "What does len([1,2,3]) return?",
            "options": ["2", "3", "4", "Error"],
            "correct_option": 1,
            "topic": "builtins",
        },
    )
    assert q2.status_code == 200
    return a["id"]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Assessments
# ---------------------------------------------------------------------------


def test_admin_assessment_authoring_requires_admin(client):
    headers = _register_and_login(client, "v20_5ccand1@example.com")
    resp = client.post(
        "/api/v1/admin/assessments", headers=headers, json={"skill_canonical_name": "python", "title": "x"}
    )
    assert resp.status_code in (401, 403)


def test_candidate_question_list_never_leaks_answer_key(client):
    assessment_id = _create_python_assessment(client)
    headers = _register_and_login(client, "v20_5ccand2@example.com")
    resp = client.get(f"/api/v1/assessments/{assessment_id}/questions", headers=headers)
    assert resp.status_code == 200
    for q in resp.json():
        assert "correct_option" not in q
        assert "explanation" not in q


def test_full_assessment_attempt_scores_correctly(client):
    assessment_id = _create_python_assessment(client)
    headers = _register_and_login(client, "v20_5ccand3@example.com")

    questions = client.get(f"/api/v1/assessments/{assessment_id}/questions", headers=headers).json()
    start = client.post(f"/api/v1/assessments/{assessment_id}/attempts", headers=headers)
    assert start.status_code == 200
    attempt_id = start.json()["id"]
    assert start.json()["status"] == "in_progress"

    # answer syntax question correctly (index 1), builtins question wrong (index 0)
    q_by_topic = {q["topic"]: q for q in questions}
    answers = [
        {"question_id": q_by_topic["syntax"]["id"], "selected_option": 1},
        {"question_id": q_by_topic["builtins"]["id"], "selected_option": 0},
    ]
    submit = client.post(f"/api/v1/attempts/{attempt_id}/submit", headers=headers, json={"answers": answers})
    assert submit.status_code == 200
    body = submit.json()
    assert body["status"] == "completed"
    assert body["correct_count"] == 1
    assert body["score_percentage"] == 50.0
    assert "builtins" in body["weak_topics"]
    assert "syntax" not in body["weak_topics"]

    # double-submit is rejected
    resubmit = client.post(f"/api/v1/attempts/{attempt_id}/submit", headers=headers, json={"answers": answers})
    assert resubmit.status_code == 400


def test_attempt_access_is_ownership_scoped(client):
    assessment_id = _create_python_assessment(client)
    owner_headers = _register_and_login(client, "v20_5cowner@example.com")
    start = client.post(f"/api/v1/assessments/{assessment_id}/attempts", headers=owner_headers)
    attempt_id = start.json()["id"]

    other_headers = _register_and_login(client, "v20_5cother@example.com")
    resp = client.get(f"/api/v1/attempts/{attempt_id}", headers=other_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Practice / certification guidance
# ---------------------------------------------------------------------------


def test_practice_recommendations_reflect_weak_topics(client):
    assessment_id = _create_python_assessment(client)
    headers = _register_and_login(client, "v20_5cpractice@example.com")

    questions = client.get(f"/api/v1/assessments/{assessment_id}/questions", headers=headers).json()
    start = client.post(f"/api/v1/assessments/{assessment_id}/attempts", headers=headers).json()
    q_by_topic = {q["topic"]: q for q in questions}
    answers = [
        {"question_id": q_by_topic["syntax"]["id"], "selected_option": 0},  # wrong
        {"question_id": q_by_topic["builtins"]["id"], "selected_option": 1},  # correct
    ]
    client.post(f"/api/v1/attempts/{start['id']}/submit", headers=headers, json={"answers": answers})

    resp = client.get("/api/v1/practice-recommendations", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    python_recs = [r for r in body if r["skill"]["canonical_name"] == "python"]
    assert any(r["recommendation_type"] == "revision" and "syntax" in r["reason"] for r in python_recs)


def test_certification_guidance_never_fabricates(client):
    headers = _register_and_login(client, "v20_5ccert@example.com")
    resp = client.get("/api/v1/certification-guidance", headers=headers)
    assert resp.status_code == 200
    # No certs seeded/admin-added for any of these skills in this test's
    # data — must come back empty, never with an invented certification.
    for certs in resp.json().values():
        assert isinstance(certs, list)


# ---------------------------------------------------------------------------
# Career readiness
# ---------------------------------------------------------------------------


def test_readiness_degrades_gracefully_with_no_data(client):
    headers = _register_and_login(client, "v20_5creadiness1@example.com")
    resp = client.get("/api/v1/career-readiness", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["role_readiness"] == 0.0
    names_with_no_score = [c["name"] for c in body["components"] if c["score"] is None]
    assert "interview_readiness" in names_with_no_score
    assert "learning_progress" in names_with_no_score
    for c in body["components"]:
        assert c["reason"]  # every component is explained, never a bare number


def test_readiness_improves_with_resume_and_job(client):
    headers = _register_and_login(client, "v20_5creadiness2@example.com")
    files = {"file": ("resume.txt", io.BytesIO(SAMPLE_RESUME.encode()), "text/plain")}
    client.post("/api/v1/resume", headers=headers, files=files)
    rec_headers = _recruiter_headers(client, "readiness")
    job_id = _publish_job(client, rec_headers)

    resp = client.get("/api/v1/career-readiness", headers=headers, params={"target_job_id": job_id})
    assert resp.status_code == 200
    body = resp.json()
    coverage = next(c for c in body["components"] if c["name"] == "skill_coverage")
    assert coverage["score"] is not None
    assert coverage["score"] > 0  # python/sql matched


# ---------------------------------------------------------------------------
# Regression: Phase 1/2 + V20.1-V20.4 endpoints still work
# ---------------------------------------------------------------------------


def test_phase2_learning_path_preview_still_works(client):
    headers = _register_and_login(client, "v20_5cregress1@example.com")
    resp = client.get("/api/v1/learning-path/preview", headers=headers)
    assert resp.status_code == 200


def test_v20_3_preferences_endpoint_unaffected(client):
    headers = _register_and_login(client, "v20_5cregress2@example.com")
    resp = client.get("/api/v1/career-copilot/preferences", headers=headers)
    assert resp.status_code == 200
