"""V20.5 (Phase 4) — Learning Streak, Government Integration,
Structured Project Briefs, Career Roadmap tests.

Covers: a plan's streak increments on consecutive days and resets on a
gap, a Government-type target job surfaces verified ExamPrepResource
links and tags gap items with a government-specific signal (never
fabricating eligibility/syllabus), a project resource's structured
brief fields flow through to practice recommendations, the career
roadmap endpoint returns the full spec stage sequence grounded in real
data, and Phase 1-3 + V20.3/V19.1 endpoints touched along the way keep
working (regression).
"""

import io
import os
from datetime import date, timedelta

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v20_5e.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.domain import ExamPrepResource, Job, LearningPlan  # noqa: E402

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


def _register_and_login(client, email, name="V20.5e Tester"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": name},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _recruiter_headers(client, suffix):
    email = f"v20_5erec{suffix}@example.com"
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
        "title": f"Backend Engineer V20.5e #{_job_counter['n']}",
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


def _make_government_job(client, suffix):
    """Ingest a Government-type job, then attach skills + a verified
    ExamPrepResource directly via the DB (POST /admin/ingest doesn't
    accept `skills`, matching every other V19.1 test's pattern of
    reaching into the DB for what the HTTP layer doesn't expose)."""

    resp = client.post(
        "/api/v1/admin/ingest",
        headers=ADMIN_HEADERS,
        json={
            "title": f"Test Recruitment {suffix}",
            "organization": "Staff Selection Commission",
            "job_type": "Government",
            "source_reference": f"v20-5e-src-{suffix}",
            "qualification": "Graduate in any discipline",
        },
    )
    job_id = resp.json()["job_id"]
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        job.skills = "Python, SQL, Excel"
        db.add(
            ExamPrepResource(
                job_id=job_id, organization="Staff Selection Commission", exam_name="Test Recruitment",
                resource_type="syllabus", title="Official Syllabus PDF", url="https://ssc.gov.example/syllabus.pdf",
            )
        )
        db.commit()
    finally:
        db.close()
    return job_id


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Learning streak
# ---------------------------------------------------------------------------


def test_streak_increments_and_resets(client):
    headers = _register_and_login(client, "v20_5estreak@example.com")
    files = {"file": ("resume.txt", io.BytesIO(SAMPLE_RESUME.encode()), "text/plain")}
    client.post("/api/v1/resume", headers=headers, files=files)
    rec_headers = _recruiter_headers(client, "streak")
    job_id = _publish_job(client, rec_headers)

    plan = client.post(
        "/api/v1/learning-plans", headers=headers, json={"title": "Streak plan", "target_job_id": job_id}
    ).json()
    module_id = plan["modules"][0]["id"]

    started = client.post(f"/api/v1/learning-plans/{plan['id']}/modules/{module_id}/start", headers=headers)
    assert started.status_code == 200

    got = client.get(f"/api/v1/learning-plans/{plan['id']}", headers=headers).json()
    assert got["current_streak_days"] == 1
    assert got["longest_streak_days"] == 1

    # simulate a second consecutive day of activity by backdating
    # last_activity_date directly, then logging time again "today"
    db = SessionLocal()
    try:
        row = db.get(LearningPlan, plan["id"])
        row.last_activity_date = date.today() - timedelta(days=1)
        db.commit()
    finally:
        db.close()

    logged = client.post(f"/api/v1/learning-plans/{plan['id']}/modules/{module_id}/log-time", headers=headers, json={"minutes": 20})
    assert logged.status_code == 200
    got2 = client.get(f"/api/v1/learning-plans/{plan['id']}", headers=headers).json()
    assert got2["current_streak_days"] == 2
    assert got2["longest_streak_days"] == 2

    # simulate a missed day (gap of 2 days) -> streak resets to 1
    db = SessionLocal()
    try:
        row = db.get(LearningPlan, plan["id"])
        row.last_activity_date = date.today() - timedelta(days=3)
        db.commit()
    finally:
        db.close()
    client.post(f"/api/v1/learning-plans/{plan['id']}/modules/{module_id}/log-time", headers=headers, json={"minutes": 5})
    got3 = client.get(f"/api/v1/learning-plans/{plan['id']}", headers=headers).json()
    assert got3["current_streak_days"] == 1
    assert got3["longest_streak_days"] == 2  # longest is preserved despite the reset

    prog = client.get(f"/api/v1/learning-plans/{plan['id']}/progress", headers=headers).json()
    assert prog["current_streak_days"] == 1
    assert prog["longest_streak_days"] == 2


def test_streak_does_not_double_count_same_day(client):
    headers = _register_and_login(client, "v20_5estreak2@example.com")
    files = {"file": ("resume.txt", io.BytesIO(SAMPLE_RESUME.encode()), "text/plain")}
    client.post("/api/v1/resume", headers=headers, files=files)
    rec_headers = _recruiter_headers(client, "streak2")
    job_id = _publish_job(client, rec_headers)
    plan = client.post("/api/v1/learning-plans", headers=headers, json={"title": "p", "target_job_id": job_id}).json()
    m1, m2 = plan["modules"][0]["id"], plan["modules"][min(1, len(plan["modules"]) - 1)]["id"]
    client.post(f"/api/v1/learning-plans/{plan['id']}/modules/{m1}/start", headers=headers)
    client.post(f"/api/v1/learning-plans/{plan['id']}/modules/{m2}/log-time", headers=headers, json={"minutes": 10})
    got = client.get(f"/api/v1/learning-plans/{plan['id']}", headers=headers).json()
    assert got["current_streak_days"] == 1


# ---------------------------------------------------------------------------
# Government integration
# ---------------------------------------------------------------------------


def test_government_job_surfaces_verified_exam_resources(client):
    headers = _register_and_login(client, "v20_5egov1@example.com")
    files = {"file": ("resume.txt", io.BytesIO(SAMPLE_RESUME.encode()), "text/plain")}
    client.post("/api/v1/resume", headers=headers, files=files)
    job_id = _make_government_job(client, "gap")

    resp = client.get("/api/v1/skill-intelligence/gap", headers=headers, params={"target_job_id": job_id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_government_target"] is True
    assert "government_exam_target" in body["signals_used"]
    assert len(body["verified_exam_resources"]) == 1
    assert body["verified_exam_resources"][0]["title"] == "Official Syllabus PDF"
    assert body["verified_exam_resources"][0]["resource_type"] == "syllabus"

    excel_item = next(
        (i for i in body["priority_skills"] + body["recommended_skills"] if i["canonical_name"] == "excel"), None
    )
    if excel_item:
        assert "government_exam_requirement" in excel_item["source_signals"]


def test_non_government_job_reports_no_exam_resources(client):
    headers = _register_and_login(client, "v20_5egov2@example.com")
    rec_headers = _recruiter_headers(client, "gov2")
    job_id = _publish_job(client, rec_headers)
    resp = client.get("/api/v1/skill-intelligence/gap", headers=headers, params={"target_job_id": job_id})
    body = resp.json()
    assert body["is_government_target"] is False
    assert body["verified_exam_resources"] == []


# ---------------------------------------------------------------------------
# Structured project briefs
# ---------------------------------------------------------------------------


def test_project_resource_structured_fields_flow_to_practice(client):
    create = client.post(
        "/api/v1/admin/resources",
        headers=ADMIN_HEADERS,
        json={
            "skill_canonical_name": "kubernetes",
            "title": "Deploy a 3-tier app on Kubernetes",
            "resource_type": "project",
            "status": "published",
            "is_verified": True,
            "objective": "Demonstrate hands-on container orchestration skills.",
            "requirements": "A running Kubernetes cluster (minikube is fine); Docker installed.",
            "expected_output": "A publicly reachable 3-tier app (frontend/backend/db) running as separate deployments.",
            "evaluation_criteria": "All three tiers running as separate pods; a Service exposing the frontend; a documented README.",
        },
    )
    assert create.status_code == 200
    resource = create.json()
    assert resource["objective"].startswith("Demonstrate")
    assert resource["evaluation_criteria"] is not None

    headers = _register_and_login(client, "v20_5eproject@example.com")
    files = {"file": ("resume.txt", io.BytesIO(SAMPLE_RESUME.encode()), "text/plain")}
    client.post("/api/v1/resume", headers=headers, files=files)
    rec_headers = _recruiter_headers(client, "project")
    job_id = _publish_job(client, rec_headers)

    resp = client.get("/api/v1/practice-recommendations", headers=headers, params={"target_job_id": job_id})
    assert resp.status_code == 200
    projects = [r for r in resp.json() if r["recommendation_type"] == "projects" and r["skill"]["canonical_name"] == "kubernetes"]
    assert len(projects) == 1
    assert projects[0]["project"] is not None
    assert projects[0]["project"]["title"] == "Deploy a 3-tier app on Kubernetes"
    assert projects[0]["project"]["objective"].startswith("Demonstrate")
    assert projects[0]["project"]["requirements"] is not None
    assert projects[0]["project"]["expected_output"] is not None
    assert projects[0]["project"]["evaluation_criteria"] is not None


# ---------------------------------------------------------------------------
# Career roadmap
# ---------------------------------------------------------------------------


def test_career_roadmap_full_stage_sequence(client):
    headers = _register_and_login(client, "v20_5eroadmap@example.com")
    files = {"file": ("resume.txt", io.BytesIO(SAMPLE_RESUME.encode()), "text/plain")}
    client.post("/api/v1/resume", headers=headers, files=files)
    rec_headers = _recruiter_headers(client, "roadmap")
    job_id = _publish_job(client, rec_headers)

    resp = client.get("/api/v1/career-roadmap", headers=headers, params={"target_job_id": job_id})
    assert resp.status_code == 200
    body = resp.json()
    stage_names = [s["stage"] for s in body["stages"]]
    assert stage_names == [
        "Goal", "Required Skills", "Current Level", "Skill Gaps", "Prerequisites",
        "Learning Modules", "Practice", "Assessment", "Project", "Interview Preparation", "Target Role",
    ]
    assert isinstance(body["goal"], str) and len(body["goal"]) > 0
    required_stage = next(s for s in body["stages"] if s["stage"] == "Required Skills")
    assert len(required_stage["items"]) > 0


def test_career_roadmap_no_data_still_returns_all_stages(client):
    headers = _register_and_login(client, "v20_5eroadmap2@example.com")
    resp = client.get("/api/v1/career-roadmap", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()["stages"]) == 11


# ---------------------------------------------------------------------------
# Regression: Phase 1-3 + V20.3/V19.1 endpoints still work
# ---------------------------------------------------------------------------


def test_phase1_gap_endpoint_still_works_without_government_fields_breaking_it(client):
    headers = _register_and_login(client, "v20_5eregress1@example.com")
    resp = client.get("/api/v1/skill-intelligence/gap", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_government_target"] is False


def test_phase3_readiness_endpoint_unaffected(client):
    headers = _register_and_login(client, "v20_5eregress2@example.com")
    resp = client.get("/api/v1/career-readiness", headers=headers)
    assert resp.status_code == 200


def test_v20_3_preferences_endpoint_unaffected(client):
    headers = _register_and_login(client, "v20_5eregress3@example.com")
    resp = client.get("/api/v1/career-copilot/preferences", headers=headers)
    assert resp.status_code == 200


def test_v19_1_organizations_endpoint_unaffected(client):
    resp = client.get("/api/v1/government/organizations")
    assert resp.status_code == 200
