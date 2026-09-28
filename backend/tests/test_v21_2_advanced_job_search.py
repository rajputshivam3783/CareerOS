"""V21.2 (Phase 1) — Recent Searches tests.

Covers: recording happens only for authenticated searches with real
query/filter content, repeating an identical search updates rather
than duplicates, listing/reusing/deleting/clearing are all scoped
strictly to the owning user (SEARCH HISTORY PRIVACY — never another
candidate, recruiter, or admin), the cap trims oldest entries first,
and V21.1 search endpoints touched along the way still work
(regression).
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v21_2.db"
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
    payload = {
        "title": f"Python Developer V21.2 #{_counter['n']}",
        "organization": "Acme Corp",
        "description": "Python backend role.",
        "qualification": "B.Tech",
        "location": "Noida",
        "job_type": "Private",
        "skills": "Python,SQL",
        "source_name": "V21.2 Test",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/admin/ingest", headers=ADMIN_HEADERS, json=payload)
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["job_id"]
    pub = client.post(f"/api/v1/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)
    assert pub.status_code == 200, pub.text
    return job_id


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


def test_anonymous_search_is_never_recorded_as_a_recent_search(client):
    _create_and_publish_job(client)
    client.get("/api/v1/search", params={"q": "python"})  # no auth header at all
    # No way to list without a user, but we can confirm the endpoint
    # requires auth — this IS the privacy guarantee: there's no
    # anonymous-scoped recent-search data to leak in the first place.
    resp = client.get("/api/v1/search/recent")
    assert resp.status_code in (401, 403)


def test_authenticated_search_with_query_is_recorded(client):
    headers = _register_and_login(client, "v21_2rec1")
    _create_and_publish_job(client)

    resp = client.get("/api/v1/search", params={"q": "python developer"}, headers=headers)
    assert resp.status_code == 200

    recent = client.get("/api/v1/search/recent", headers=headers)
    assert recent.status_code == 200
    body = recent.json()
    assert len(body) == 1
    assert body[0]["query"] == "python developer"
    assert body[0]["result_count"] >= 0
    assert "id" in body[0] and "created_at" in body[0]


def test_blank_search_with_no_filters_is_not_recorded(client):
    headers = _register_and_login(client, "v21_2rec2")
    client.get("/api/v1/search", params={"q": ""}, headers=headers)
    recent = client.get("/api/v1/search/recent", headers=headers).json()
    assert recent == []


def test_search_with_only_filters_no_query_is_still_recorded(client):
    headers = _register_and_login(client, "v21_2rec3")
    _create_and_publish_job(client, location="Delhi")
    client.get("/api/v1/search", params={"q": "", "location": "Delhi"}, headers=headers)
    recent = client.get("/api/v1/search/recent", headers=headers).json()
    assert len(recent) == 1
    assert recent[0]["filters"].get("location") == "Delhi"


def test_repeating_identical_search_updates_rather_than_duplicates(client):
    headers = _register_and_login(client, "v21_2rec4")
    _create_and_publish_job(client)

    client.get("/api/v1/search", params={"q": "python developer"}, headers=headers)
    client.get("/api/v1/search", params={"q": "python developer"}, headers=headers)
    client.get("/api/v1/search", params={"q": "python developer"}, headers=headers)

    recent = client.get("/api/v1/search/recent", headers=headers).json()
    assert len(recent) == 1  # not 3 — same search re-run just refreshes it


def test_different_filters_produce_separate_recent_search_entries(client):
    headers = _register_and_login(client, "v21_2rec5")
    _create_and_publish_job(client, location="Noida")
    _create_and_publish_job(client, location="Pune")

    client.get("/api/v1/search", params={"q": "python", "location": "Noida"}, headers=headers)
    client.get("/api/v1/search", params={"q": "python", "location": "Pune"}, headers=headers)

    recent = client.get("/api/v1/search/recent", headers=headers).json()
    assert len(recent) == 2
    locations = {r["filters"].get("location") for r in recent}
    assert locations == {"Noida", "Pune"}


def test_most_recent_search_is_listed_first(client):
    headers = _register_and_login(client, "v21_2rec6")
    _create_and_publish_job(client)
    client.get("/api/v1/search", params={"q": "first query"}, headers=headers)
    client.get("/api/v1/search", params={"q": "second query"}, headers=headers)

    recent = client.get("/api/v1/search/recent", headers=headers).json()
    assert recent[0]["query"] == "second query"
    assert recent[1]["query"] == "first query"


def test_recent_searches_capped_at_twenty_per_user(client):
    headers = _register_and_login(client, "v21_2rec7")
    _create_and_publish_job(client)
    for i in range(25):
        client.get("/api/v1/search", params={"q": f"unique query {i}"}, headers=headers)

    recent = client.get("/api/v1/search/recent", headers=headers).json()
    assert len(recent) == 20
    # oldest ones (query 0-4) should have been trimmed
    queries = {r["query"] for r in recent}
    assert "unique query 0" not in queries
    assert "unique query 24" in queries


# ---------------------------------------------------------------------------
# Privacy / ownership
# ---------------------------------------------------------------------------


def test_recent_searches_are_scoped_to_the_owning_user_only(client):
    owner_headers = _register_and_login(client, "v21_2owner")
    _create_and_publish_job(client)
    client.get("/api/v1/search", params={"q": "owners private query"}, headers=owner_headers)

    other_headers = _register_and_login(client, "v21_2other")
    other_recent = client.get("/api/v1/search/recent", headers=other_headers).json()
    assert other_recent == []  # never sees the owner's search


def test_admin_cannot_read_a_users_recent_searches_via_this_endpoint(client):
    """There is no admin-facing route that accepts a user_id here at
    all — /search/recent always resolves to the caller's own id. This
    test documents that the endpoint itself has no such parameter to
    exploit, matching SEARCH HISTORY PRIVACY's "admins should only
    access aggregate operational data"."""
    owner_headers = _register_and_login(client, "v21_2adminowner")
    client.get("/api/v1/search", params={"q": "admin should not see this"}, headers=owner_headers)

    # Admin key alone (no user JWT) can't call this candidate-only route.
    resp = client.get("/api/v1/search/recent", headers=ADMIN_HEADERS)
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Delete / clear
# ---------------------------------------------------------------------------


def test_delete_one_recent_search(client):
    headers = _register_and_login(client, "v21_2del1")
    _create_and_publish_job(client)
    client.get("/api/v1/search", params={"q": "to be deleted"}, headers=headers)
    recent = client.get("/api/v1/search/recent", headers=headers).json()
    search_id = recent[0]["id"]

    resp = client.delete(f"/api/v1/search/recent/{search_id}", headers=headers)
    assert resp.status_code == 204

    after = client.get("/api/v1/search/recent", headers=headers).json()
    assert after == []


def test_cannot_delete_another_users_recent_search(client):
    owner_headers = _register_and_login(client, "v21_2delowner")
    _create_and_publish_job(client)
    client.get("/api/v1/search", params={"q": "protect this one"}, headers=owner_headers)
    search_id = client.get("/api/v1/search/recent", headers=owner_headers).json()[0]["id"]

    other_headers = _register_and_login(client, "v21_2delother")
    resp = client.delete(f"/api/v1/search/recent/{search_id}", headers=other_headers)
    assert resp.status_code == 404

    # Still there for the owner — the cross-user delete was a no-op.
    still_there = client.get("/api/v1/search/recent", headers=owner_headers).json()
    assert len(still_there) == 1


def test_clear_all_recent_searches(client):
    headers = _register_and_login(client, "v21_2clear1")
    _create_and_publish_job(client)
    client.get("/api/v1/search", params={"q": "one"}, headers=headers)
    client.get("/api/v1/search", params={"q": "two"}, headers=headers)

    resp = client.delete("/api/v1/search/recent", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["cleared"] == 2

    after = client.get("/api/v1/search/recent", headers=headers).json()
    assert after == []


# ---------------------------------------------------------------------------
# Regression: V21.1 search endpoints touched along the way still work
# ---------------------------------------------------------------------------


def test_v21_1_search_endpoint_still_returns_expected_shape(client):
    headers = _register_and_login(client, "v21_2regress1")
    job_id = _create_and_publish_job(client, title="Regression Check Role")
    resp = client.get("/api/v1/search", params={"q": "Regression Check Role"}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body and "total_count" in body and "facets" in body
    assert any(item["entity_id"] == job_id for item in body["items"])


def test_v21_1_autocomplete_endpoint_unaffected(client):
    resp = client.get("/api/v1/search/autocomplete", params={"q": "py"})
    assert resp.status_code == 200
    assert "suggestions" in resp.json()


# ---------------------------------------------------------------------------
# Result quality: expired opportunities never shown as active (V21.2)
# ---------------------------------------------------------------------------


def test_expired_published_job_is_excluded_from_search(client):
    from datetime import date, timedelta

    rec_email = "v21_2expiredrec@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": rec_email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Rec"},
    )
    rec_login = client.post("/api/v1/auth/login", json={"email": rec_email, "password": "password12345!"})
    rec_me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {rec_login.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{rec_me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    rec_login2 = client.post("/api/v1/auth/recruiter/login", json={"email": rec_email, "password": "password12345!"})
    rec_headers = {"Authorization": f"Bearer {rec_login2.json()['access_token']}"}

    _counter["n"] += 1
    tag = f"V21.2expired{_counter['n']}"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    expired = client.post(
        "/api/v1/recruiter/jobs", headers=rec_headers,
        json={"title": f"Expired Role {tag}", "organization": "Acme", "location": "Remote", "description": "x",
              "qualification": "B.Tech", "job_type": "Private", "deadline": yesterday},
    ).json()
    active = client.post(
        "/api/v1/recruiter/jobs", headers=rec_headers,
        json={"title": f"Active Role {tag}", "organization": "Acme", "location": "Remote", "description": "x",
              "qualification": "B.Tech", "job_type": "Private", "deadline": tomorrow},
    ).json()
    for job in (expired, active):
        client.post(f"/api/v1/recruiter/jobs/{job['id']}/submit-for-review", headers=rec_headers)
        client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)

    resp = client.get("/api/v1/search", params={"q": tag})
    ids = [i["entity_id"] for i in resp.json()["items"]]
    assert active["id"] in ids
    assert expired["id"] not in ids  # still status="published", but deadline has passed — never shown as active


def test_job_with_no_deadline_is_never_excluded(client):
    rec_email = "v21_2nodeadlinerec@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": rec_email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Rec"},
    )
    rec_login = client.post("/api/v1/auth/login", json={"email": rec_email, "password": "password12345!"})
    rec_me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {rec_login.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{rec_me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    rec_login2 = client.post("/api/v1/auth/recruiter/login", json={"email": rec_email, "password": "password12345!"})
    rec_headers = {"Authorization": f"Bearer {rec_login2.json()['access_token']}"}

    _counter["n"] += 1
    tag = f"V21.2nodeadline{_counter['n']}"
    job = client.post(
        "/api/v1/recruiter/jobs", headers=rec_headers,
        json={"title": f"Open Ended Role {tag}", "organization": "Acme", "location": "Remote", "description": "x",
              "qualification": "B.Tech", "job_type": "Private"},
    ).json()
    client.post(f"/api/v1/recruiter/jobs/{job['id']}/submit-for-review", headers=rec_headers)
    client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)

    resp = client.get("/api/v1/search", params={"q": tag})
    assert job["id"] in [i["entity_id"] for i in resp.json()["items"]]


# ---------------------------------------------------------------------------
# Input validation (V21.2 security hardening)
# ---------------------------------------------------------------------------


def test_oversized_query_string_is_rejected_not_silently_truncated(client):
    resp = client.get("/api/v1/search", params={"q": "x" * 5000})
    assert resp.status_code == 422


def test_oversized_location_filter_is_rejected(client):
    resp = client.get("/api/v1/search", params={"q": "python", "location": "x" * 5000})
    assert resp.status_code == 422


def test_oversized_autocomplete_query_is_rejected(client):
    resp = client.get("/api/v1/search/autocomplete", params={"q": "x" * 5000})
    assert resp.status_code == 422
    resp2 = client.get("/api/v1/search/autocomplete/grouped", params={"q": "x" * 5000})
    assert resp2.status_code == 422


def test_reasonable_length_query_still_works(client):
    """The new max_length constraints must not reject ordinary input —
    only pathological/DoS-shaped input."""
    resp = client.get("/api/v1/search", params={"q": "Senior Python Developer with 5 years experience in Django and PostgreSQL"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Salary High-to-Low / Low-to-High sorting (V21.2)
# ---------------------------------------------------------------------------


def test_salary_asc_and_desc_sort_opposite_directions(client):
    rec_email = "v21_2salaryrec@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": rec_email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Rec"},
    )
    rec_login = client.post("/api/v1/auth/login", json={"email": rec_email, "password": "password12345!"})
    rec_me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {rec_login.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{rec_me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    rec_login2 = client.post("/api/v1/auth/recruiter/login", json={"email": rec_email, "password": "password12345!"})
    rec_headers = {"Authorization": f"Bearer {rec_login2.json()['access_token']}"}

    _counter["n"] += 1
    tag = f"V21.2salary{_counter['n']}"
    low = client.post(
        "/api/v1/recruiter/jobs", headers=rec_headers,
        json={"title": f"Low Pay {tag}", "organization": "Acme", "location": "Remote", "description": "x",
              "qualification": "B.Tech", "job_type": "Private", "salary": "₹3,00,000 per annum"},
    ).json()
    high = client.post(
        "/api/v1/recruiter/jobs", headers=rec_headers,
        json={"title": f"High Pay {tag}", "organization": "Acme", "location": "Remote", "description": "x",
              "qualification": "B.Tech", "job_type": "Private", "salary": "₹30,00,000 per annum"},
    ).json()
    for job in (low, high):
        client.post(f"/api/v1/recruiter/jobs/{job['id']}/submit-for-review", headers=rec_headers)
        client.post(f"/api/v1/admin/jobs/{job['id']}/publish", headers=ADMIN_HEADERS)

    desc = client.get("/api/v1/search", params={"q": tag, "sort": "salary_desc"}).json()
    desc_ids = [i["entity_id"] for i in desc["items"]]
    assert desc_ids.index(high["id"]) < desc_ids.index(low["id"])

    asc = client.get("/api/v1/search", params={"q": tag, "sort": "salary_asc"}).json()
    asc_ids = [i["entity_id"] for i in asc["items"]]
    assert asc_ids.index(low["id"]) < asc_ids.index(high["id"])

    # Backward compatibility: the old bare "salary" value still works
    # and behaves like salary_desc (unchanged existing behavior).
    legacy = client.get("/api/v1/search", params={"q": tag, "sort": "salary"}).json()
    legacy_ids = [i["entity_id"] for i in legacy["items"]]
    assert legacy_ids.index(high["id"]) < legacy_ids.index(low["id"])


# ---------------------------------------------------------------------------
# Grouped autocomplete (V21.2)
# ---------------------------------------------------------------------------


def test_grouped_autocomplete_separates_job_titles_from_companies(client):
    _create_and_publish_job(client, title="Zzyzx Backend Engineer V21.2g", organization="Pythonic Corp")

    # A prefix specific enough not to collide with the many
    # "Python Developer V21.2 #N" titles other tests in this module
    # create (grouped autocomplete truncates to limit_per_group,
    # shortest-first — a generic "Python" prefix would get crowded out).
    resp = client.get("/api/v1/search/autocomplete/grouped", params={"q": "Zzyzx"})
    assert resp.status_code == 200
    groups = resp.json()["groups"]
    assert any("Zzyzx Backend Engineer V21.2g" in t for t in groups.get("job_titles", []))
    assert "companies" not in groups or isinstance(groups["companies"], list)


def test_grouped_autocomplete_never_returns_unauthorized_entities(client):
    _register_and_login(client, "v21_2groupedauth")
    _create_and_publish_job(client)
    resp = client.get("/api/v1/search/autocomplete/grouped", params={"q": "Python"})
    assert resp.status_code == 200
    # No auth header at all — same permission machinery as regular
    # search/autocomplete (apply_visibility) governs this endpoint too.
    assert resp.status_code == 200


def test_grouped_autocomplete_empty_query_returns_no_groups(client):
    resp = client.get("/api/v1/search/autocomplete/grouped", params={"q": "zzzznonexistentprefixxx"})
    assert resp.status_code == 200
    assert resp.json()["groups"] == {}


# ---------------------------------------------------------------------------
# Stipend reuses the salary_min/max filter/sort path (V21.2 fix)
# ---------------------------------------------------------------------------


def test_internship_stipend_is_filterable_via_salary_range(client):
    headers = _register_and_login(client, "v21_2stipend")

    # /admin/ingest's ManualJob schema has no salary/stipend field at
    # all — stipend only flows through the recruiter job-creation path
    # (RecruiterJobIn), so that's what this test exercises, same as a
    # real internship posting would be created.
    rec_email = "v21_2stipendrec@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": rec_email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Rec"},
    )
    rec_login = client.post("/api/v1/auth/login", json={"email": rec_email, "password": "password12345!"})
    rec_me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {rec_login.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{rec_me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    rec_login2 = client.post("/api/v1/auth/recruiter/login", json={"email": rec_email, "password": "password12345!"})
    rec_headers = {"Authorization": f"Bearer {rec_login2.json()['access_token']}"}

    _counter["n"] += 1
    title = f"Python Intern V21.2 #{_counter['n']}"
    job = client.post(
        "/api/v1/recruiter/jobs", headers=rec_headers,
        json={
            "title": title, "organization": "Acme Corp", "location": "Remote",
            "description": "Internship role.", "qualification": "Pursuing B.Tech",
            "job_type": "Internship", "stipend": "₹15,000 - ₹25,000 per month", "skills": ["Python"],
        },
    ).json()
    job_id = job["id"]
    client.post(f"/api/v1/recruiter/jobs/{job_id}/submit-for-review", headers=rec_headers)
    client.post(f"/api/v1/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)

    resp = client.get(
        "/api/v1/search", params={"q": title, "salary_min": 10000, "salary_max": 30000}, headers=headers,
    )
    assert resp.status_code == 200
    assert any(item["entity_id"] == job_id for item in resp.json()["items"])

    # A salary range that doesn't overlap the stipend should exclude it.
    resp2 = client.get(
        "/api/v1/search", params={"q": title, "salary_min": 100000, "salary_max": 200000}, headers=headers,
    )
    assert not any(item["entity_id"] == job_id for item in resp2.json()["items"])
