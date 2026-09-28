"""V18.2 — recruiter ATS job management: draft mode, submit-for-review,
clone, close/reopen, archive, wizard fields, and the Kanban pipeline."""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v18_2.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}


def _recruiter_headers(client, suffix):
    email = f"v18_2rec{suffix}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Rec"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    login = client.post("/api/v1/auth/recruiter/login", json={"email": email, "password": "password12345!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


_job_counter = {"n": 0}


def _job_payload(**overrides):
    _job_counter["n"] += 1
    payload = {
        "title": f"Backend Engineer #{_job_counter['n']}",
        "organization": "Acme",
        "location": "Remote",
        "description": "Build things",
        "qualification": "B.Tech",
        "responsibilities": "Own the payments service",
        "requirements": "5+ years Python",
        "skills": ["Python", "SQL", "  ", "Python"],
        "benefits": "Health insurance",
        "screening_questions": ["Are you authorized to work in India?", ""],
    }
    payload.update(overrides)
    return payload


def test_draft_job_is_not_in_admin_review_queue():
    with TestClient(app) as client:
        headers = _recruiter_headers(client, "a")
        job = client.post(
            "/api/v1/recruiter/jobs", headers=headers, json=_job_payload(save_as_draft=True)
        ).json()
        assert job["status"] == "draft"

        review_queue = client.get("/api/v1/admin/review", headers=ADMIN_HEADERS).json()
        assert all(j["id"] != job["id"] for j in review_queue)

        mine = client.get(f"/api/v1/recruiter/jobs/{job['id']}", headers=headers).json()
        assert mine["skills"] and "Python" in mine["skills"]


def test_submit_for_review_moves_draft_into_queue_then_admin_can_publish():
    with TestClient(app) as client:
        headers = _recruiter_headers(client, "b")
        job = client.post(
            "/api/v1/recruiter/jobs", headers=headers, json=_job_payload(save_as_draft=True)
        ).json()

        # Can't publish/close a draft directly.
        assert client.post(f"/api/v1/recruiter/jobs/{job['id']}/close", headers=headers).status_code == 409

        submitted = client.post(f"/api/v1/recruiter/jobs/{job['id']}/submit-for-review", headers=headers)
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "review"

        review_queue = client.get("/api/v1/admin/review", headers=ADMIN_HEADERS).json()
        assert any(j["id"] == job["id"] for j in review_queue)

        publish = client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)
        assert publish.status_code == 200


def test_close_and_reopen_lifecycle():
    with TestClient(app) as client:
        headers = _recruiter_headers(client, "c")
        job = client.post("/api/v1/recruiter/jobs", headers=headers, json=_job_payload()).json()
        client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)

        closed = client.post(f"/api/v1/recruiter/jobs/{job['id']}/close", headers=headers)
        assert closed.status_code == 200
        assert closed.json()["status"] == "closed"

        reopened = client.post(f"/api/v1/recruiter/jobs/{job['id']}/reopen", headers=headers)
        assert reopened.status_code == 200
        assert reopened.json()["status"] == "published"


def test_archive_is_one_way():
    with TestClient(app) as client:
        headers = _recruiter_headers(client, "d")
        job = client.post("/api/v1/recruiter/jobs", headers=headers, json=_job_payload()).json()

        archived = client.post(f"/api/v1/recruiter/jobs/{job['id']}/archive", headers=headers)
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"

        again = client.post(f"/api/v1/recruiter/jobs/{job['id']}/archive", headers=headers)
        assert again.status_code == 409


def test_clone_job_copies_wizard_fields_as_new_draft():
    with TestClient(app) as client:
        headers = _recruiter_headers(client, "e")
        job = client.post("/api/v1/recruiter/jobs", headers=headers, json=_job_payload()).json()

        clone = client.post(f"/api/v1/recruiter/jobs/{job['id']}/clone", headers=headers)
        assert clone.status_code == 201
        cloned = clone.json()
        assert cloned["status"] == "draft"
        assert cloned["id"] != job["id"]
        assert cloned["title"].startswith("Backend Engineer")
        assert cloned["benefits"] == "Health insurance"


def test_kanban_pipeline_and_stage_move():
    with TestClient(app) as client:
        r_headers = _recruiter_headers(client, "f")
        job = client.post("/api/v1/recruiter/jobs", headers=r_headers, json=_job_payload()).json()
        client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)

        candidate_email = "v18_2cand@example.com"
        client.post(
            "/api/v1/auth/register",
            json={"email": candidate_email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Cand"},
        )
        clogin = client.post("/api/v1/auth/login", json={"email": candidate_email, "password": "password12345!"})
        c_headers = {"Authorization": f"Bearer {clogin.json()['access_token']}"}
        apply = client.post(f"/api/v1/jobs/{job['id']}/apply", headers=c_headers, json={})
        applicant_id = apply.json()["id"]

        pipeline = client.get(f"/api/v1/recruiter/jobs/{job['id']}/pipeline", headers=r_headers).json()
        # V24.3 renamed the V18.2 stage vocabulary to match the
        # canonical hiring-workflow names (applied -> new,
        # technical_round -> assessment; see PIPELINE_STAGES's
        # docstring in app.core.constants) — the board/move-stage
        # *behavior* this test exercises is otherwise unchanged.
        assert applicant_id in [c["id"] for c in pipeline["columns"]["new"]]

        moved = client.patch(
            f"/api/v1/recruiter/applicants/{applicant_id}/stage",
            headers=r_headers,
            json={"pipeline_stage": "assessment"},
        )
        assert moved.status_code == 200
        assert moved.json()["pipeline_stage"] == "assessment"

        pipeline = client.get(f"/api/v1/recruiter/jobs/{job['id']}/pipeline", headers=r_headers).json()
        assert applicant_id in [c["id"] for c in pipeline["columns"]["assessment"]]
        assert applicant_id not in [c["id"] for c in pipeline["columns"]["new"]]

        bad = client.patch(
            f"/api/v1/recruiter/applicants/{applicant_id}/stage",
            headers=r_headers,
            json={"pipeline_stage": "not-a-real-stage"},
        )
        assert bad.status_code == 422


def test_recruiter_cannot_touch_another_recruiters_job():
    with TestClient(app) as client:
        owner_headers = _recruiter_headers(client, "g")
        other_headers = _recruiter_headers(client, "h")
        job = client.post("/api/v1/recruiter/jobs", headers=owner_headers, json=_job_payload()).json()

        assert client.post(f"/api/v1/recruiter/jobs/{job['id']}/clone", headers=other_headers).status_code == 404
        assert client.post(f"/api/v1/recruiter/jobs/{job['id']}/archive", headers=other_headers).status_code == 404
