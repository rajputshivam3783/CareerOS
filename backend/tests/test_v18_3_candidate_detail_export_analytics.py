"""V18.3 — recruiter candidate detail view, applicant CSV export, and
recruiter analytics. Builds entirely on V9/V16/V18.2 data already on
Applicant/Interview/OfferLetter/Resume; adds no new tables."""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v18_3.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}
PW = "password12345!"


def _setup_job_and_applicant(client, suffix):
    recruiter_email = f"v183rec{suffix}@example.com"
    candidate_email = f"v183cand{suffix}@example.com"

    client.post("/api/v1/auth/register", json={"email": recruiter_email, "password": PW, "password_confirm": PW, "full_name": "Rec"})
    rlogin = client.post("/api/v1/auth/login", json={"email": recruiter_email, "password": PW})
    rme = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {rlogin.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{rme['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    rlogin = client.post("/api/v1/auth/recruiter/login", json={"email": recruiter_email, "password": PW})
    r_headers = {"Authorization": f"Bearer {rlogin.json()['access_token']}"}

    client.post("/api/v1/auth/register", json={"email": candidate_email, "password": PW, "password_confirm": PW, "full_name": "Cand One"})
    clogin = client.post("/api/v1/auth/login", json={"email": candidate_email, "password": PW})
    c_headers = {"Authorization": f"Bearer {clogin.json()['access_token']}"}

    job = client.post(
        "/api/v1/recruiter/jobs",
        headers=r_headers,
        json={"title": f"Engineer {suffix}", "organization": "Acme", "location": "Remote", "description": "x", "qualification": "x"},
    ).json()
    client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)

    apply = client.post(f"/api/v1/jobs/{job['id']}/apply", headers=c_headers, json={"cover_note": "Excited to apply"})
    applicant_id = apply.json()["id"]

    return r_headers, c_headers, job["id"], applicant_id


def test_candidate_detail_bundles_notes_interviews_offer():
    with TestClient(app) as client:
        r_headers, _, _, applicant_id = _setup_job_and_applicant(client, "a")

        client.post(f"/api/v1/recruiter/applicants/{applicant_id}/notes", headers=r_headers, json={"note": "Strong resume"})
        client.post(
            f"/api/v1/recruiter/applicants/{applicant_id}/interviews",
            headers=r_headers,
            json={"round_name": "Screen", "mode": "phone", "scheduled_at": "2026-09-01T10:00:00"},
        )
        client.post(
            f"/api/v1/recruiter/applicants/{applicant_id}/offer",
            headers=r_headers,
            json={"position_title": "Senior Engineer", "salary": "12 LPA"},
        )

        detail = client.get(f"/api/v1/recruiter/applicants/{applicant_id}", headers=r_headers)
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["candidate_email"] == "v183canda@example.com"
        assert body["cover_note"] == "Excited to apply"
        assert len(body["notes"]) == 1
        assert body["notes"][0]["note"] == "Strong resume"
        assert len(body["interviews"]) == 1
        assert body["offer"]["position_title"] == "Senior Engineer"
        assert body["resume"] is None  # candidate never uploaded one
        assert any(e["type"] == "applied" for e in body["timeline"])
        assert any(e["type"] == "note" for e in body["timeline"])
        assert any(e["type"] == "interview_scheduled" for e in body["timeline"])
        assert any(e["type"] == "offer" for e in body["timeline"])


def test_candidate_detail_is_owner_scoped():
    with TestClient(app) as client:
        _, _, _, applicant_id = _setup_job_and_applicant(client, "b")
        # A second, unrelated recruiter must not be able to view this applicant.
        other_email = "v183recother@example.com"
        client.post("/api/v1/auth/register", json={"email": other_email, "password": PW, "password_confirm": PW, "full_name": "Other"})
        olog = client.post("/api/v1/auth/login", json={"email": other_email, "password": PW})
        ome = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {olog.json()['access_token']}"}).json()
        client.post(f"/api/v1/admin/users/{ome['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
        olog = client.post("/api/v1/auth/recruiter/login", json={"email": other_email, "password": PW})
        o_headers = {"Authorization": f"Bearer {olog.json()['access_token']}"}

        response = client.get(f"/api/v1/recruiter/applicants/{applicant_id}", headers=o_headers)
        assert response.status_code == 404


def test_applicants_csv_export():
    with TestClient(app) as client:
        r_headers, _, job_id, applicant_id = _setup_job_and_applicant(client, "c")
        response = client.get(f"/api/v1/recruiter/jobs/{job_id}/applicants/export", headers=r_headers)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]
        text = response.text
        assert "Candidate email" in text.splitlines()[0]
        assert "v183candc@example.com" in text


def test_recruiter_analytics_reflects_pipeline_and_offers():
    with TestClient(app) as client:
        r_headers, _, job_id, applicant_id = _setup_job_and_applicant(client, "d")

        baseline = client.get("/api/v1/recruiter/analytics", headers=r_headers).json()
        assert baseline["total_applicants"] == 1
        # V24.3 renamed the V18.2 pipeline_stage vocabulary
        # (applied -> new, accepted -> hired; see PIPELINE_STAGES's
        # docstring in app.core.constants) — analytics behavior itself
        # is unchanged.
        assert baseline["pipeline"]["new"] == 1
        assert baseline["offers_sent"] == 0

        client.post(
            f"/api/v1/recruiter/applicants/{applicant_id}/offer",
            headers=r_headers,
            json={"position_title": "Senior Engineer", "salary": "12 LPA"},
        )
        client.post(f"/api/v1/recruiter/applicants/{applicant_id}/offer/send", headers=r_headers)

        after = client.get("/api/v1/recruiter/analytics", headers=r_headers).json()
        assert after["offers_sent"] == 1
        assert after["offer_acceptance_rate_pct"] == 0.0

        moved = client.patch(
            f"/api/v1/recruiter/applicants/{applicant_id}/stage", headers=r_headers, json={"pipeline_stage": "hired"}
        )
        assert moved.status_code == 200

        final = client.get("/api/v1/recruiter/analytics", headers=r_headers).json()
        assert final["pipeline"]["hired"] == 1
        assert final["conversion_pct"]["hired"] == 100.0
