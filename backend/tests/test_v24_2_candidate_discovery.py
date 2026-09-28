"""V24.2 — Advanced Candidate Discovery & Search.

Covers: the core privacy model (applied vs. opted-in vs. neither),
skill AND/OR filtering with the Java/JavaScript disambiguation the
spec explicitly calls out, cross-recruiter isolation/IDOR on both the
list and detail endpoints, allow-listed sort fields (unsafe filter
protection), job-specific candidate-matches scoring/reasons, and the
natural-language parser's deterministic, SQL-free behavior.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v24_2.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}


def _register_recruiter(client, suffix):
    email = f"v242rec{suffix}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Rec"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    rlogin = client.post("/api/v1/auth/recruiter/login", json={"email": email, "password": "password12345!"})
    return {"Authorization": f"Bearer {rlogin.json()['access_token']}"}


def _register_candidate(client, suffix, *, full_name="Cand", skills="", location="", searchable=False):
    email = f"v242cand{suffix}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": full_name},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()
    client.put(
        "/api/v1/profile",
        headers=headers,
        json={"skills": skills, "location": location, "highest_qualification": "B.Tech", "candidate_searchable": searchable},
    )
    return headers, me["id"]


def _publish_job(client, r_headers, title="Backend Engineer"):
    job = client.post(
        "/api/v1/recruiter/jobs",
        headers=r_headers,
        json={"title": title, "organization": "Acme", "location": "Remote", "description": "x", "qualification": "x"},
    ).json()
    client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)
    return job


def test_candidate_visible_only_via_application_or_opt_in():
    with TestClient(app) as client:
        r_headers = _register_recruiter(client, "a")
        job = _publish_job(client, r_headers, "Backend Engineer A")

        applied_headers, applied_id = _register_candidate(client, "applied_a", skills="Java, SQL")
        client.post(f"/api/v1/jobs/{job['id']}/apply", headers=applied_headers, json={})

        opted_in_headers, opted_in_id = _register_candidate(client, "optin_a", skills="Java", searchable=True)
        _private_headers, private_id = _register_candidate(client, "private_a", skills="Java", searchable=False)

        listing = client.get("/api/v1/recruiter/candidates?page_size=50", headers=r_headers).json()
        ids = {c["id"] for c in listing["items"]}
        assert applied_id in ids
        assert opted_in_id in ids
        assert private_id not in ids


def test_skill_filter_disambiguates_java_and_javascript():
    with TestClient(app) as client:
        r_headers = _register_recruiter(client, "b")
        _java_headers, java_id = _register_candidate(client, "java_b", skills="Java, SQL", searchable=True)
        _js_headers, js_id = _register_candidate(client, "js_b", skills="JavaScript", searchable=True)

        result = client.get("/api/v1/recruiter/candidates?skills=Java&page_size=50", headers=r_headers).json()
        ids = {c["id"] for c in result["items"]}
        assert java_id in ids
        assert js_id not in ids


def test_skill_filter_all_vs_any():
    with TestClient(app) as client:
        r_headers = _register_recruiter(client, "c")
        _both_headers, both_id = _register_candidate(client, "both_c", skills="Java, Spring Boot", searchable=True)
        _one_headers, one_id = _register_candidate(client, "one_c", skills="Java", searchable=True)

        all_mode = client.get(
            "/api/v1/recruiter/candidates?skills=Java&skills=Spring+Boot&skills_mode=all&page_size=50", headers=r_headers
        ).json()
        all_ids = {c["id"] for c in all_mode["items"]}
        assert both_id in all_ids
        assert one_id not in all_ids

        any_mode = client.get(
            "/api/v1/recruiter/candidates?skills=Java&skills=Spring+Boot&skills_mode=any&page_size=50", headers=r_headers
        ).json()
        any_ids = {c["id"] for c in any_mode["items"]}
        assert both_id in any_ids
        assert one_id in any_ids


def test_location_filter():
    with TestClient(app) as client:
        r_headers = _register_recruiter(client, "d")
        _blr_headers, blr_id = _register_candidate(client, "blr_d", skills="Java", location="Bangalore", searchable=True)
        _del_headers, del_id = _register_candidate(client, "del_d", skills="Java", location="Delhi", searchable=True)

        result = client.get("/api/v1/recruiter/candidates?location=Bangalore&page_size=50", headers=r_headers).json()
        ids = {c["id"] for c in result["items"]}
        assert blr_id in ids
        assert del_id not in ids


def test_sort_by_rejects_unlisted_field():
    with TestClient(app) as client:
        r_headers = _register_recruiter(client, "e")
        response = client.get("/api/v1/recruiter/candidates?sort_by=users.password_hash", headers=r_headers)
        assert response.status_code == 422


def test_cross_recruiter_isolation_and_idor_on_detail():
    with TestClient(app) as client:
        r1_headers = _register_recruiter(client, "f1")
        r2_headers = _register_recruiter(client, "f2")
        job = _publish_job(client, r1_headers, "R1 Job")

        applied_headers, applied_id = _register_candidate(client, "applied_f", skills="Java")
        client.post(f"/api/v1/jobs/{job['id']}/apply", headers=applied_headers, json={})

        r2_listing = client.get("/api/v1/recruiter/candidates?page_size=50", headers=r2_headers).json()
        assert all(c["id"] != applied_id for c in r2_listing["items"])

        forbidden_detail = client.get(f"/api/v1/recruiter/candidates/{applied_id}", headers=r2_headers)
        assert forbidden_detail.status_code == 404

        allowed_detail = client.get(f"/api/v1/recruiter/candidates/{applied_id}", headers=r1_headers)
        assert allowed_detail.status_code == 200
        assert allowed_detail.json()["id"] == applied_id


def test_job_candidate_matches_scores_and_explains():
    with TestClient(app) as client:
        r_headers = _register_recruiter(client, "g")
        job = client.post(
            "/api/v1/recruiter/jobs",
            headers=r_headers,
            json={
                "title": "Java Backend Engineer", "organization": "Acme", "location": "Remote",
                "description": "Build APIs with Java and SQL.", "qualification": "x",
                "skills": ["Java", "SQL"],
            },
        ).json()
        client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)

        applicant_headers, applicant_id = _register_candidate(client, "match_g", skills="Java, SQL")
        client.post(f"/api/v1/jobs/{job['id']}/apply", headers=applicant_headers, json={})

        matches = client.get(f"/api/v1/recruiter/jobs/{job['id']}/candidate-matches", headers=r_headers).json()
        row = next(c for c in matches["items"] if c["id"] == applicant_id)
        assert 0 <= row["match_score"] <= 100
        assert isinstance(row["match_reasons"], list) and row["match_reasons"]


def test_job_candidate_matches_isolated_by_ownership():
    with TestClient(app) as client:
        r1_headers = _register_recruiter(client, "h1")
        r2_headers = _register_recruiter(client, "h2")
        job = _publish_job(client, r1_headers, "R1 Only Job")
        forbidden = client.get(f"/api/v1/recruiter/jobs/{job['id']}/candidate-matches", headers=r2_headers)
        assert forbidden.status_code == 404


def test_natural_language_parse_is_deterministic_and_never_executes_sql():
    with TestClient(app) as client:
        r_headers = _register_recruiter(client, "i")
        response = client.post(
            "/api/v1/recruiter/candidate-search/parse",
            headers=r_headers,
            json={"query": "Find Java backend developers with 3+ years experience in Bangalore"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["parsed"] is True
        assert "Java" in body["filters"]["skills"]
        assert body["filters"]["min_experience_years"] == 3.0
        assert body["filters"]["location"] == "Bangalore"

        # A garbage/injection-style query never blows up and never
        # produces anything but the same safe JSON filter shape —
        # there is no code path from this input to a SQL statement.
        injection = client.post(
            "/api/v1/recruiter/candidate-search/parse",
            headers=r_headers,
            json={"query": "'; DROP TABLE users; --"},
        )
        assert injection.status_code == 200
        assert injection.json()["parsed"] is False
        assert injection.json()["fallback_q"]


def test_candidate_search_requires_recruiter_role():
    with TestClient(app) as client:
        _candidate_headers, _candidate_id = _register_candidate(client, "nonrecruiter")
        response = client.get("/api/v1/recruiter/candidates", headers=_candidate_headers)
        assert response.status_code in (401, 403)
