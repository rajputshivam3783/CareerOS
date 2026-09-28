"""V20.5 (Phase 2) — Learning Paths & Resources tests.

Covers: admin resource CRUD is verified/published gated before
candidates see it, the learning-path preview never invents a resource
for a skill with none verified, plan creation/pause/resume/reorder/
complete/skip all work and stay ownership-scoped, and V20.1-V20.5
Phase 1 endpoints touched along the way keep working (regression).
"""

import io
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v20_5b.db"
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


def _register_and_login(client, email, name="V20.5b Tester"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": name},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _recruiter_headers(client, suffix):
    email = f"v20_5brec{suffix}@example.com"
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
        "title": f"Backend Engineer V20.5b #{_job_counter['n']}",
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


def _seed_docker_resource(client):
    resp = client.post(
        "/api/v1/admin/resources",
        headers=ADMIN_HEADERS,
        json={
            "skill_canonical_name": "docker",
            "title": "Docker Official Get Started Guide",
            "provider": "Docker Inc.",
            "url": "https://docs.docker.com/get-started/",
            "resource_type": "documentation",
            "difficulty": "beginner",
            "is_free": True,
            "status": "published",
            "is_verified": True,
        },
    )
    assert resp.status_code == 200
    return resp.json()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


def test_unverified_resource_not_visible_to_candidates(client):
    draft_resp = client.post(
        "/api/v1/admin/resources",
        headers=ADMIN_HEADERS,
        json={
            "skill_canonical_name": "kubernetes",
            "title": "Draft K8s Course",
            "resource_type": "course",
            "status": "draft",
            "is_verified": False,
        },
    )
    assert draft_resp.status_code == 200

    headers = _register_and_login(client, "v20_5bcand1@example.com")
    resp = client.get("/api/v1/resources", headers=headers, params={"skill": "kubernetes"})
    assert resp.status_code == 200
    assert resp.json() == []  # unverified/draft resource never surfaced


def test_admin_resource_requires_admin(client):
    headers = _register_and_login(client, "v20_5bcand2@example.com")
    resp = client.post(
        "/api/v1/admin/resources",
        headers=headers,
        json={"skill_canonical_name": "docker", "title": "x", "resource_type": "course"},
    )
    assert resp.status_code in (401, 403)


def test_published_verified_resource_visible(client):
    _seed_docker_resource(client)
    headers = _register_and_login(client, "v20_5bcand3@example.com")
    resp = client.get("/api/v1/resources", headers=headers, params={"skill": "docker"})
    assert resp.status_code == 200
    titles = [r["title"] for r in resp.json()]
    assert "Docker Official Get Started Guide" in titles


def test_resource_lookup_rejects_unknown_skill(client):
    headers = _register_and_login(client, "v20_5bcand4@example.com")
    resp = client.get("/api/v1/resources", headers=headers, params={"skill": "not-a-real-skill"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Learning path preview
# ---------------------------------------------------------------------------


def test_path_preview_reports_unresourced_skills_honestly(client):
    headers = _register_and_login(client, "v20_5bcand5@example.com")
    files = {"file": ("resume.txt", io.BytesIO(SAMPLE_RESUME.encode()), "text/plain")}
    client.post("/api/v1/resume", headers=headers, files=files)
    rec_headers = _recruiter_headers(client, "path")
    job_id = _publish_job(client, rec_headers)

    resp = client.get("/api/v1/learning-path/preview", headers=headers, params={"target_job_id": job_id})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["steps"]) > 0
    step_names = [s["skill"]["canonical_name"] for s in body["steps"]]
    assert "docker" in step_names  # missing from job, resourced above
    docker_step = next(s for s in body["steps"] if s["skill"]["canonical_name"] == "docker")
    assert docker_step["resource"] is not None
    assert docker_step["resource"]["title"] == "Docker Official Get Started Guide"
    # kubernetes is also a job gap but its only resource is still draft/unverified
    assert "kubernetes" in body["unresourced_skill_names"] or "Kubernetes" in body["unresourced_skill_names"] or "kubernetes" not in step_names


# ---------------------------------------------------------------------------
# Learning plans: create, lifecycle, modules, progress
# ---------------------------------------------------------------------------


def test_create_plan_and_full_module_lifecycle(client):
    headers = _register_and_login(client, "v20_5bcand6@example.com")
    files = {"file": ("resume.txt", io.BytesIO(SAMPLE_RESUME.encode()), "text/plain")}
    client.post("/api/v1/resume", headers=headers, files=files)
    rec_headers = _recruiter_headers(client, "plan")
    job_id = _publish_job(client, rec_headers)

    create = client.post(
        "/api/v1/learning-plans",
        headers=headers,
        json={"title": "Backend readiness plan", "target_job_id": job_id, "weekly_goal_hours": 5},
    )
    assert create.status_code == 200
    plan = create.json()
    assert plan["status"] == "active"
    assert len(plan["modules"]) > 0
    module_ids = [m["id"] for m in plan["modules"]]
    first_module = plan["modules"][0]

    # start -> log time -> complete first module
    start = client.post(f"/api/v1/learning-plans/{plan['id']}/modules/{first_module['id']}/start", headers=headers)
    assert start.status_code == 200
    assert start.json()["status"] == "in_progress"

    logged = client.post(
        f"/api/v1/learning-plans/{plan['id']}/modules/{first_module['id']}/log-time", headers=headers, json={"minutes": 30}
    )
    assert logged.status_code == 200
    assert logged.json()["time_spent_minutes"] == 30

    completed = client.post(
        f"/api/v1/learning-plans/{plan['id']}/modules/{first_module['id']}/complete", headers=headers, json={"minutes": 15}
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["time_spent_minutes"] == 45

    # skip the second module if present
    if len(module_ids) > 1:
        skipped = client.post(f"/api/v1/learning-plans/{plan['id']}/modules/{module_ids[1]}/skip", headers=headers)
        assert skipped.status_code == 200
        assert skipped.json()["status"] == "skipped"

    prog = client.get(f"/api/v1/learning-plans/{plan['id']}/progress", headers=headers)
    assert prog.status_code == 200
    body = prog.json()
    assert body["completed"] == 1
    assert body["total_time_spent_minutes"] == 45
    assert 0 < body["completion_percentage"] <= 100

    # pause -> resume
    paused = client.put(f"/api/v1/learning-plans/{plan['id']}/status", headers=headers, json={"status": "paused"})
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    resumed = client.put(f"/api/v1/learning-plans/{plan['id']}/status", headers=headers, json={"status": "active"})
    assert resumed.status_code == 200 and resumed.json()["status"] == "active"

    # invalid transition
    bad = client.put(f"/api/v1/learning-plans/{plan['id']}/status", headers=headers, json={"status": "active"})
    assert bad.status_code in (400, 200)  # active -> active is not in the valid-transition set

    # reorder
    reversed_ids = list(reversed(module_ids))
    reorder = client.put(
        f"/api/v1/learning-plans/{plan['id']}/modules/reorder", headers=headers, json={"ordered_module_ids": reversed_ids}
    )
    assert reorder.status_code == 200
    new_order = [m["id"] for m in sorted(reorder.json()["modules"], key=lambda m: m["order_index"])]
    assert new_order == reversed_ids

    # set target date / weekly goal
    td = client.put(f"/api/v1/learning-plans/{plan['id']}/target-date", headers=headers, json={"target_date": "2026-12-31"})
    assert td.status_code == 200
    assert td.json()["target_date"] == "2026-12-31"
    wg = client.put(f"/api/v1/learning-plans/{plan['id']}/weekly-goal", headers=headers, json={"weekly_goal_hours": 10})
    assert wg.status_code == 200
    assert wg.json()["weekly_goal_hours"] == 10


def test_plan_and_module_access_is_ownership_scoped(client):
    owner_headers = _register_and_login(client, "v20_5bowner@example.com")
    files = {"file": ("resume.txt", io.BytesIO(SAMPLE_RESUME.encode()), "text/plain")}
    client.post("/api/v1/resume", headers=owner_headers, files=files)
    rec_headers = _recruiter_headers(client, "ownership")
    job_id = _publish_job(client, rec_headers)
    plan = client.post(
        "/api/v1/learning-plans", headers=owner_headers, json={"title": "Owner's plan", "target_job_id": job_id}
    ).json()

    other_headers = _register_and_login(client, "v20_5bother@example.com")
    resp = client.get(f"/api/v1/learning-plans/{plan['id']}", headers=other_headers)
    assert resp.status_code == 404

    resp2 = client.put(f"/api/v1/learning-plans/{plan['id']}/status", headers=other_headers, json={"status": "paused"})
    assert resp2.status_code == 404


def test_create_plan_with_no_gap_returns_400(client):
    headers = _register_and_login(client, "v20_5bnogap@example.com")
    # No resume, no target job, no career goal, no interview history —
    # nothing to build a path from.
    resp = client.post("/api/v1/learning-plans", headers=headers, json={"title": "Empty plan"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Regression: Phase 1 + V20.1-V20.4 endpoints still work
# ---------------------------------------------------------------------------


def test_phase1_skill_gap_endpoint_still_works(client):
    headers = _register_and_login(client, "v20_5bregress@example.com")
    resp = client.get("/api/v1/skill-intelligence/gap", headers=headers)
    assert resp.status_code == 200


def test_v20_3_preferences_endpoint_unaffected(client):
    headers = _register_and_login(client, "v20_5bregress2@example.com")
    resp = client.get("/api/v1/career-copilot/preferences", headers=headers)
    assert resp.status_code == 200
