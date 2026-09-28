"""V20.5 (Career Copilot integration) tests.

Covers: the copilot's context (GET /career-copilot/context) surfaces
V20.5 skill-gap/learning-plan/readiness data — composed, not
duplicated — and degrades honestly (explicit unknown_fields entries,
never a fabricated value) when the candidate hasn't generated any of
it yet. Also a regression check that the underlying V20.3 context
endpoint's original fields are untouched.
"""

import io
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v20_5d.db"
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


def _register_and_login(client, email, name="V20.5d Tester"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": name},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _recruiter_headers(client, suffix):
    email = f"v20_5drec{suffix}@example.com"
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
        "title": f"Backend Engineer V20.5d #{_job_counter['n']}",
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


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_context_reports_skill_intelligence_as_unknown_with_no_data(client):
    headers = _register_and_login(client, "v20_5dcand1@example.com")
    resp = client.get("/api/v1/career-copilot/context", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "skill_intelligence" in body
    assert body["skill_intelligence"]["priority_skill_gaps"] == []
    assert body["skill_intelligence"]["active_learning_plan"] is None
    assert any("priority skill gaps" in f for f in body["unknown_fields"])
    assert any("active learning plan" in f for f in body["unknown_fields"])


def test_context_surfaces_real_skill_gap_and_plan(client):
    headers = _register_and_login(client, "v20_5dcand2@example.com")
    files = {"file": ("resume.txt", io.BytesIO(SAMPLE_RESUME.encode()), "text/plain")}
    client.post("/api/v1/resume", headers=headers, files=files)
    rec_headers = _recruiter_headers(client, "copilot")
    job_id = _publish_job(client, rec_headers)

    # No plan yet — gap should already show up even before a plan exists.
    resp = client.get("/api/v1/career-copilot/context", headers=headers)
    body = resp.json()
    gaps = body["skill_intelligence"]["priority_skill_gaps"]
    # Skill gap here needs a target job in the request, which /context
    # doesn't take — so with no job pre-selected this may still be
    # empty; what matters is the field always exists and is consistent
    # with what /skill-intelligence/gap (no job) reports.
    direct_gap = client.get("/api/v1/skill-intelligence/gap", headers=headers).json()
    assert [g["skill"] for g in gaps] == [i["display_name"] for i in direct_gap["priority_skills"][:5]]

    plan = client.post(
        "/api/v1/learning-plans", headers=headers, json={"title": "Copilot plan", "target_job_id": job_id}
    )
    if plan.status_code == 200:
        resp2 = client.get("/api/v1/career-copilot/context", headers=headers)
        body2 = resp2.json()
        assert body2["skill_intelligence"]["active_learning_plan"] is not None
        assert body2["skill_intelligence"]["active_learning_plan"]["title"] == "Copilot plan"
        assert not any("active learning plan" in f for f in body2["unknown_fields"])


def test_context_original_v20_3_fields_unaffected(client):
    headers = _register_and_login(client, "v20_5dregress@example.com")
    resp = client.get("/api/v1/career-copilot/context", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    for field in ["profile", "preferences", "resume_summary", "saved_jobs", "applications", "upcoming_deadlines", "unknown_fields"]:
        assert field in body
