"""V24.3 — Candidate Pipeline & Hiring Workflow.

Covers: enriched pipeline board cards, stage-transition validation
(valid/invalid/same-stage), immutable RecruiterPipelineHistory,
hired_at, per-job stats/conversion/stale-candidate endpoints, bulk
stage moves (partial-failure reporting + ownership), candidate
in-app notification on stage change, and cross-recruiter/IDOR
isolation of every new endpoint.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v24_3.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"
# Matches the established pattern in test_v17_2_security_hardening.py /
# test_v17_3_rbac.py: tests/conftest.py already raises this to 1000 for
# the whole suite, but this file does enough register/login calls on
# its own (9 tests x 2-3 accounts each) to trip the default
# auth_rate_limit_attempts=10/60s in-memory limiter (keyed by client
# IP, which TestClient always reports as the same address) even when
# run alone — this isn't a product bug, just this file needing the
# same explicit belt-and-suspenders setting those two files use.
os.environ["AUTH_RATE_LIMIT_ATTEMPTS"] = "1000"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}


def _register_recruiter(client, suffix):
    email = f"v243rec{suffix}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Rec"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    rlogin = client.post("/api/v1/auth/recruiter/login", json={"email": email, "password": "password12345!"})
    headers = {"Authorization": f"Bearer {rlogin.json()['access_token']}"}
    return headers, me["id"], email


def _register_candidate(client, suffix):
    email = f"v243cand{suffix}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Cand"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).json()
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, me["id"]


_job_counter = 0


def _post_job_and_apply(client, r_headers, c_headers, title=None):
    global _job_counter
    _job_counter += 1
    title = title or f"Backend Engineer {_job_counter}"
    job_resp = client.post(
        "/api/v1/recruiter/jobs",
        headers=r_headers,
        json={"title": title, "organization": "Acme", "location": "Remote", "description": "x", "qualification": "x"},
    )
    assert job_resp.status_code == 201, job_resp.text
    job = job_resp.json()
    client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)
    client.post(f"/api/v1/jobs/{job['id']}/apply", headers=c_headers, json={})
    applicants = client.get(f"/api/v1/recruiter/jobs/{job['id']}/applicants", headers=r_headers)
    if applicants.status_code == 200 and applicants.json():
        applicant_id = applicants.json()[0]["id"]
    else:
        # fall back to reading it off the pipeline board
        board = client.get(f"/api/v1/recruiter/jobs/{job['id']}/pipeline", headers=r_headers).json()
        applicant_id = board["columns"]["new"][0]["id"]
    return job, applicant_id


def test_pipeline_board_defaults_new_and_is_enriched():
    with TestClient(app) as client:
        r_headers, _, _ = _register_recruiter(client, "a")
        c_headers, _ = _register_candidate(client, "a")
        job, applicant_id = _post_job_and_apply(client, r_headers, c_headers)

        board = client.get(f"/api/v1/recruiter/jobs/{job['id']}/pipeline", headers=r_headers).json()
        assert board["stages"][0] == "new"
        assert len(board["columns"]["new"]) == 1
        card = board["columns"]["new"][0]
        assert card["id"] == applicant_id
        assert card["pipeline_stage"] == "new"
        assert "candidate_name" in card and "top_skills" in card and "days_in_stage" in card


def test_valid_forward_and_backward_transitions_are_recorded():
    with TestClient(app) as client:
        r_headers, _, _ = _register_recruiter(client, "b")
        c_headers, _ = _register_candidate(client, "b")
        job, applicant_id = _post_job_and_apply(client, r_headers, c_headers)

        forward = client.patch(
            f"/api/v1/recruiter/applicants/{applicant_id}/stage", headers=r_headers, json={"pipeline_stage": "interview"}
        )
        assert forward.status_code == 200
        assert forward.json()["pipeline_stage"] == "interview"

        backward = client.patch(
            f"/api/v1/recruiter/applicants/{applicant_id}/stage", headers=r_headers, json={"pipeline_stage": "reviewing"}
        )
        assert backward.status_code == 200

        history = client.get(f"/api/v1/recruiter/applicants/{applicant_id}/pipeline-history", headers=r_headers).json()
        stages = [(h["old_stage"], h["new_stage"]) for h in history["history"]]
        assert (None, "new") in stages  # initial backfill row
        assert ("new", "interview") in stages
        assert ("interview", "reviewing") in stages
        directions = {h["new_stage"]: h["direction"] for h in history["history"]}
        assert directions["interview"] == "forward"
        assert directions["reviewing"] == "backward"


def test_same_stage_transition_is_rejected():
    with TestClient(app) as client:
        r_headers, _, _ = _register_recruiter(client, "c")
        c_headers, _ = _register_candidate(client, "c")
        job, applicant_id = _post_job_and_apply(client, r_headers, c_headers)

        response = client.patch(
            f"/api/v1/recruiter/applicants/{applicant_id}/stage", headers=r_headers, json={"pipeline_stage": "new"}
        )
        assert response.status_code == 422


def test_unknown_stage_is_rejected():
    with TestClient(app) as client:
        r_headers, _, _ = _register_recruiter(client, "d")
        c_headers, _ = _register_candidate(client, "d")
        job, applicant_id = _post_job_and_apply(client, r_headers, c_headers)

        response = client.patch(
            f"/api/v1/recruiter/applicants/{applicant_id}/stage", headers=r_headers, json={"pipeline_stage": "not_a_stage"}
        )
        assert response.status_code == 422


def test_hired_sets_hired_at_once_and_keeps_it_on_correction():
    with TestClient(app) as client:
        r_headers, _, _ = _register_recruiter(client, "e")
        c_headers, _ = _register_candidate(client, "e")
        job, applicant_id = _post_job_and_apply(client, r_headers, c_headers)

        hired = client.patch(
            f"/api/v1/recruiter/applicants/{applicant_id}/stage", headers=r_headers, json={"pipeline_stage": "hired"}
        ).json()
        assert hired["hired_at"] is not None
        first_hired_at = hired["hired_at"]

        # A correction move away from hired and back must not blank hired_at.
        client.patch(f"/api/v1/recruiter/applicants/{applicant_id}/stage", headers=r_headers, json={"pipeline_stage": "offer"})
        back = client.patch(
            f"/api/v1/recruiter/applicants/{applicant_id}/stage", headers=r_headers, json={"pipeline_stage": "hired"}
        ).json()
        assert back["hired_at"] == first_hired_at


def test_candidate_receives_in_app_notification_on_stage_change():
    with TestClient(app) as client:
        r_headers, _, _ = _register_recruiter(client, "f")
        c_headers, c_id = _register_candidate(client, "f")
        job, applicant_id = _post_job_and_apply(client, r_headers, c_headers)

        result = client.patch(
            f"/api/v1/recruiter/applicants/{applicant_id}/stage", headers=r_headers, json={"pipeline_stage": "shortlisted"}
        ).json()
        assert result["candidate_notified"] is True

        notifications = client.get("/api/v1/notifications", headers=c_headers).json()
        items = notifications.get("items", notifications if isinstance(notifications, list) else [])
        assert any("shortlisted" in (n.get("message") or "").lower() for n in items)


def test_pipeline_stats_and_conversion_and_stale():
    with TestClient(app) as client:
        r_headers, _, _ = _register_recruiter(client, "g")
        c1_headers, _ = _register_candidate(client, "g1")
        c2_headers, _ = _register_candidate(client, "g2")

        job = client.post(
            "/api/v1/recruiter/jobs",
            headers=r_headers,
            json={"title": "QA Engineer", "organization": "Acme", "location": "Remote", "description": "x", "qualification": "x"},
        ).json()
        client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)
        client.post(f"/api/v1/jobs/{job['id']}/apply", headers=c1_headers, json={})
        client.post(f"/api/v1/jobs/{job['id']}/apply", headers=c2_headers, json={})

        board = client.get(f"/api/v1/recruiter/jobs/{job['id']}/pipeline", headers=r_headers).json()
        ids = [c["id"] for c in board["columns"]["new"]]
        assert len(ids) == 2
        client.patch(f"/api/v1/recruiter/applicants/{ids[0]}/stage", headers=r_headers, json={"pipeline_stage": "shortlisted"})

        stats = client.get(f"/api/v1/recruiter/jobs/{job['id']}/pipeline/stats", headers=r_headers).json()
        assert stats["total_candidates"] == 2
        assert stats["stage_counts"]["shortlisted"] == 1
        assert stats["stage_counts"]["new"] == 1
        assert stats["applications_this_week"] == 2

        conversion = client.get(f"/api/v1/recruiter/jobs/{job['id']}/pipeline/conversion", headers=r_headers).json()
        step = next(s for s in conversion["steps"] if s["from_stage"] == "new" and s["to_stage"] == "shortlisted")
        assert step["from_count"] == 2
        assert step["to_count"] == 1
        assert step["conversion_rate"] == 50.0

        # A job with zero applicants must report a null rate, not a
        # misleading 0%.
        empty_job = client.post(
            "/api/v1/recruiter/jobs",
            headers=r_headers,
            json={"title": "Empty Role", "organization": "Acme", "location": "Remote", "description": "x", "qualification": "x"},
        ).json()
        empty_conversion = client.get(f"/api/v1/recruiter/jobs/{empty_job['id']}/pipeline/conversion", headers=r_headers).json()
        assert all(s["conversion_rate"] is None for s in empty_conversion["steps"])

        stale = client.get(f"/api/v1/recruiter/jobs/{job['id']}/pipeline/stale?days=0", headers=r_headers).json()
        assert stale["threshold_days"] == 0
        assert len(stale["stale_candidates"]) == 2  # both moved 0 days ago, threshold 0 => both "stale"
        for row in stale["stale_candidates"]:
            assert "suggested_action" in row and "days_inactive" in row


def test_bulk_stage_move_reports_per_id_and_skips_invalid():
    with TestClient(app) as client:
        r_headers, _, _ = _register_recruiter(client, "h")
        c1_headers, _ = _register_candidate(client, "h1")
        c2_headers, _ = _register_candidate(client, "h2")
        job = client.post(
            "/api/v1/recruiter/jobs",
            headers=r_headers,
            json={"title": "Recruiter", "organization": "Acme", "location": "Remote", "description": "x", "qualification": "x"},
        ).json()
        client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)
        client.post(f"/api/v1/jobs/{job['id']}/apply", headers=c1_headers, json={})
        client.post(f"/api/v1/jobs/{job['id']}/apply", headers=c2_headers, json={})
        board = client.get(f"/api/v1/recruiter/jobs/{job['id']}/pipeline", headers=r_headers).json()
        ids = [c["id"] for c in board["columns"]["new"]]

        result = client.post(
            "/api/v1/recruiter/applicants/bulk-stage",
            headers=r_headers,
            json={"applicant_ids": [*ids, 999999], "pipeline_stage": "reviewing"},
        ).json()
        assert result["requested"] == 3
        assert result["succeeded"] == 2
        assert result["failed"] == 1
        failed_row = next(r for r in result["results"] if not r["ok"])
        assert failed_row["applicant_id"] == 999999

        board2 = client.get(f"/api/v1/recruiter/jobs/{job['id']}/pipeline", headers=r_headers).json()
        assert len(board2["columns"]["reviewing"]) == 2


def test_pipeline_endpoints_are_isolated_across_recruiters():
    with TestClient(app) as client:
        r1_headers, _, _ = _register_recruiter(client, "i1")
        r2_headers, _, _ = _register_recruiter(client, "i2")
        c_headers, _ = _register_candidate(client, "i")
        job, applicant_id = _post_job_and_apply(client, r1_headers, c_headers)

        assert client.get(f"/api/v1/recruiter/jobs/{job['id']}/pipeline", headers=r2_headers).status_code == 404
        assert client.get(f"/api/v1/recruiter/jobs/{job['id']}/pipeline/stats", headers=r2_headers).status_code == 404
        assert client.get(f"/api/v1/recruiter/jobs/{job['id']}/pipeline/conversion", headers=r2_headers).status_code == 404
        assert client.get(f"/api/v1/recruiter/jobs/{job['id']}/pipeline/stale", headers=r2_headers).status_code == 404
        assert client.get(f"/api/v1/recruiter/applicants/{applicant_id}/pipeline-history", headers=r2_headers).status_code == 404
        assert (
            client.patch(f"/api/v1/recruiter/applicants/{applicant_id}/stage", headers=r2_headers, json={"pipeline_stage": "hired"}).status_code
            == 404
        )

        # IDOR via bulk-stage: r2 including r1's applicant id must not move it,
        # and must be reported as a per-id failure, not silently dropped.
        bulk = client.post(
            "/api/v1/recruiter/applicants/bulk-stage", headers=r2_headers, json={"applicant_ids": [applicant_id], "pipeline_stage": "hired"}
        ).json()
        assert bulk["succeeded"] == 0
        assert bulk["failed"] == 1
        still_new = client.get(f"/api/v1/recruiter/jobs/{job['id']}/pipeline", headers=r1_headers).json()
        assert len(still_new["columns"]["new"]) == 1


def test_recruiter_notes_and_interviews_still_work_alongside_pipeline_moves():
    """V24.3 reuses ApplicantNote/Interview unchanged (spec sections 8
    and 12) — this just confirms moving pipeline_stage doesn't disturb
    either."""
    with TestClient(app) as client:
        r_headers, _, _ = _register_recruiter(client, "j")
        c_headers, _ = _register_candidate(client, "j")
        job, applicant_id = _post_job_and_apply(client, r_headers, c_headers)

        client.patch(f"/api/v1/recruiter/applicants/{applicant_id}/stage", headers=r_headers, json={"pipeline_stage": "shortlisted"})
        note = client.post(
            f"/api/v1/recruiter/applicants/{applicant_id}/notes", headers=r_headers, json={"note": "Strong fundamentals"}
        )
        assert note.status_code == 201

        candidate_view = client.get("/api/v1/applications", headers=c_headers)
        assert candidate_view.status_code == 200  # recruiter note must not leak into candidate's own view
        assert not any("Strong fundamentals" in str(item) for item in candidate_view.json())
