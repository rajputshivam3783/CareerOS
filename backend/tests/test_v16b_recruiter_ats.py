"""V16 — recruiter ATS: reject reasons, candidate notes, interview
scheduling, and offer letters."""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v16b.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}


def _setup_job_and_applicant(client, suffix):
    recruiter_email = f"v16rec{suffix}@example.com"
    candidate_email = f"v16cand{suffix}@example.com"

    client.post("/api/v1/auth/register", json={"email": recruiter_email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Rec"})
    rlogin = client.post("/api/v1/auth/login", json={"email": recruiter_email, "password": "password12345!"})
    rme = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {rlogin.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{rme['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    rlogin = client.post("/api/v1/auth/recruiter/login", json={"email": recruiter_email, "password": "password12345!"})
    r_headers = {"Authorization": f"Bearer {rlogin.json()['access_token']}"}

    client.post("/api/v1/auth/register", json={"email": candidate_email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Cand"})
    clogin = client.post("/api/v1/auth/login", json={"email": candidate_email, "password": "password12345!"})
    c_headers = {"Authorization": f"Bearer {clogin.json()['access_token']}"}

    job = client.post(
        "/api/v1/recruiter/jobs",
        headers=r_headers,
        json={"title": f"Engineer {suffix}", "organization": "Acme", "location": "Remote", "description": "x", "qualification": "x"},
    ).json()
    client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)

    apply = client.post(f"/api/v1/jobs/{job['id']}/apply", headers=c_headers, json={})
    applicant_id = apply.json()["id"]

    return r_headers, c_headers, job["id"], applicant_id


def test_rejecting_without_reason_is_rejected_by_api():
    with TestClient(app) as client:
        r_headers, _, _, applicant_id = _setup_job_and_applicant(client, "a")
        response = client.patch(
            f"/api/v1/recruiter/applicants/{applicant_id}", headers=r_headers, json={"status": "rejected"}
        )
        assert response.status_code == 422


def test_reject_with_reason_is_visible_to_candidate():
    with TestClient(app) as client:
        r_headers, c_headers, _, applicant_id = _setup_job_and_applicant(client, "b")
        update = client.patch(
            f"/api/v1/recruiter/applicants/{applicant_id}",
            headers=r_headers,
            json={"status": "rejected", "reject_reason": "Not enough experience"},
        )
        assert update.status_code == 200
        assert update.json()["reject_reason"] == "Not enough experience"

        mine = client.get("/api/v1/my-submissions", headers=c_headers).json()
        assert mine[0]["reject_reason"] == "Not enough experience"


def test_applicant_notes_are_private_to_recruiter():
    with TestClient(app) as client:
        r_headers, c_headers, _, applicant_id = _setup_job_and_applicant(client, "c")
        note = client.post(
            f"/api/v1/recruiter/applicants/{applicant_id}/notes", headers=r_headers, json={"note": "Strong candidate"}
        )
        assert note.status_code == 201
        notes = client.get(f"/api/v1/recruiter/applicants/{applicant_id}/notes", headers=r_headers)
        assert notes.status_code == 200
        assert notes.json()[0]["note"] == "Strong candidate"


def test_interview_scheduling_updates_status_and_is_visible_to_candidate():
    with TestClient(app) as client:
        r_headers, c_headers, _, applicant_id = _setup_job_and_applicant(client, "d")
        interview = client.post(
            f"/api/v1/recruiter/applicants/{applicant_id}/interviews",
            headers=r_headers,
            json={"round_name": "Screen", "mode": "phone", "scheduled_at": "2026-09-01T10:00:00"},
        )
        assert interview.status_code == 201

        # applicant status moved to "interview" as a side effect
        pipeline = client.get(
            f"/api/v1/recruiter/jobs/{client.get('/api/v1/recruiter/jobs', headers=r_headers).json()[0]['id']}/applicants",
            headers=r_headers,
        ).json()
        assert pipeline[0]["status"] == "interview"

        mine = client.get(f"/api/v1/my-submissions/{applicant_id}/interviews", headers=c_headers)
        assert mine.status_code == 200
        assert mine.json()[0]["round_name"] == "Screen"


def test_offer_letter_lifecycle():
    with TestClient(app) as client:
        r_headers, c_headers, _, applicant_id = _setup_job_and_applicant(client, "e")

        draft = client.post(
            f"/api/v1/recruiter/applicants/{applicant_id}/offer",
            headers=r_headers,
            json={"position_title": "Senior Engineer", "salary": "12 LPA", "start_date": "2026-09-01"},
        )
        assert draft.status_code == 201
        assert draft.json()["status"] == "draft"

        # A candidate can't see a draft offer.
        hidden = client.get(f"/api/v1/my-submissions/{applicant_id}/offer", headers=c_headers)
        assert hidden.status_code == 404

        sent = client.post(f"/api/v1/recruiter/applicants/{applicant_id}/offer/send", headers=r_headers)
        assert sent.status_code == 200
        assert sent.json()["status"] == "sent"

        visible = client.get(f"/api/v1/my-submissions/{applicant_id}/offer", headers=c_headers)
        assert visible.status_code == 200
        assert "Senior Engineer" in visible.json()["letter_text"]

        accept = client.post(
            f"/api/v1/my-submissions/{applicant_id}/offer/respond", headers=c_headers, json={"accept": True}
        )
        assert accept.status_code == 200
        assert accept.json()["status"] == "accepted"

        # Can't respond twice.
        again = client.post(
            f"/api/v1/my-submissions/{applicant_id}/offer/respond", headers=c_headers, json={"accept": False}
        )
        assert again.status_code == 409
