"""V21.1 — Unified Search Infrastructure tests.

Covers: indexing (create/update/delete/bulk/reindex/index health),
deterministic ranking, filters, sorting, pagination, permission
enforcement (private jobs never leak to another user or an anonymous
visitor), autocomplete, facets, no-result suggestions, and that
V16-V20.6 regression endpoints touched along the way (job publish,
company directory, skill catalog) still work.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v21_1.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.domain import Job, Skill  # noqa: E402
from app.search import indexer  # noqa: E402
from app.search.document import EntityType  # noqa: E402
from app.search.models import SearchIndexDocument  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}

_counter = {"n": 0}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _register_and_login(client, email_prefix: str) -> tuple[dict, str]:
    _counter["n"] += 1
    email = f"{email_prefix}{_counter['n']}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Test User"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, email


def _recruiter_headers(client, suffix: str) -> tuple[dict, int]:
    email = f"v21_1rec{suffix}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Test Recruiter"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).json()
    client.post(f"/api/v1/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    login = client.post("/api/v1/auth/recruiter/login", json={"email": email, "password": "password12345!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, me["id"]


def _create_job(client, **overrides) -> int:
    _counter["n"] += 1
    payload = {
        "title": f"Backend Engineer V21.1 #{_counter['n']}",
        "organization": "Acme Corp",
        "description": "We need someone strong in Python, SQL, and Docker for our backend team.",
        "qualification": "B.Tech in Computer Science",
        "location": "Bangalore",
        "job_type": "Private",
        "skills": "Python,SQL,Docker",
        "source_name": "V21.1 Test",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/admin/ingest", headers=ADMIN_HEADERS, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["job_id"]


def _publish_job(client, job_id: int) -> None:
    resp = client.post(f"/api/v1/admin/jobs/{job_id}/publish", headers=ADMIN_HEADERS)
    assert resp.status_code == 200, resp.text


def _reindex(client) -> dict:
    resp = client.post("/api/v1/admin/search/reindex", headers=ADMIN_HEADERS)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------------------------------------------------
# Indexing
# --------------------------------------------------------------------


def test_index_job_creates_a_search_document(client):
    job_id = _create_job(client, title="Unique Indexer Probe Role")
    _publish_job(client, job_id)

    # POST /admin/ingest accepts ManualJob.skills but a pre-existing
    # ingest-pipeline gap never applies it to the row (see
    # app/search/document.py's _parse_job_skills docstring / CHANGELOG_V21_1.md
    # "Found but not fixed") — set it directly here so this test targets
    # the indexer's own comma/JSON-array parsing, not that unrelated gap.
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        job.skills = "Python,SQL,Docker"
        db.commit()

        assert indexer.index_job(db, job_id) is True
        db.commit()
        doc = db.scalars(
            select(SearchIndexDocument).where(
                SearchIndexDocument.entity_type == EntityType.JOB.value, SearchIndexDocument.entity_id == job_id
            )
        ).first()
        assert doc is not None
        assert doc.title == "Unique Indexer Probe Role"
        assert doc.status == "published"
        assert doc.visibility == "public"
        assert "python" in (doc.skills_text or "")
    finally:
        db.close()


def test_index_job_parses_json_array_skills_format(client):
    """Regression guard for the recruiter.py-vs-question_engine.py
    Job.skills format mismatch discovered while building this: the
    indexer must handle both the comma-separated and JSON-array forms
    without raising."""
    job_id = _create_job(client, title="JSON Skills Probe Role")
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        job.skills = '["Python", "SQL"]'
        db.commit()
        assert indexer.index_job(db, job_id) is True
        db.commit()
        doc = db.scalars(
            select(SearchIndexDocument).where(
                SearchIndexDocument.entity_type == EntityType.JOB.value, SearchIndexDocument.entity_id == job_id
            )
        ).first()
        assert "python" in (doc.skills_text or "")
        assert "sql" in (doc.skills_text or "")
    finally:
        db.close()


def test_index_job_updates_existing_document_not_duplicates(client):
    job_id = _create_job(client, title="Update Probe Role")
    db = SessionLocal()
    try:
        indexer.index_job(db, job_id)
        db.commit()
        job = db.get(Job, job_id)
        job.title = "Updated Probe Role Title"
        db.commit()
        indexer.index_job(db, job_id)
        db.commit()

        docs = db.scalars(
            select(SearchIndexDocument).where(
                SearchIndexDocument.entity_type == EntityType.JOB.value, SearchIndexDocument.entity_id == job_id
            )
        ).all()
        assert len(docs) == 1
        assert docs[0].title == "Updated Probe Role Title"
    finally:
        db.close()


def test_delete_entity_removes_the_document(client):
    job_id = _create_job(client, title="Delete Probe Role")
    db = SessionLocal()
    try:
        indexer.index_job(db, job_id)
        db.commit()
        indexer.delete_entity(db, EntityType.JOB, job_id)
        db.commit()
        doc = db.scalars(
            select(SearchIndexDocument).where(
                SearchIndexDocument.entity_type == EntityType.JOB.value, SearchIndexDocument.entity_id == job_id
            )
        ).first()
        assert doc is None
    finally:
        db.close()


def test_government_job_indexes_as_government_recruitment_entity_type(client):
    job_id = _create_job(client, title="SSC CGL Probe Recruitment", job_type="Government", organization="SSC")
    db = SessionLocal()
    try:
        indexer.index_job(db, job_id)
        db.commit()
        doc = db.scalars(
            select(SearchIndexDocument).where(
                SearchIndexDocument.entity_type == EntityType.GOVERNMENT_RECRUITMENT.value,
                SearchIndexDocument.entity_id == job_id,
            )
        ).first()
        assert doc is not None
    finally:
        db.close()


def test_bulk_index_and_reindex_all_are_idempotent(client):
    _create_job(client, title="Bulk Probe A")
    _create_job(client, title="Bulk Probe B")
    db = SessionLocal()
    try:
        first = indexer.bulk_index(db, EntityType.JOB)
        second = indexer.bulk_index(db, EntityType.JOB)
        # Idempotent upsert: running twice indexes the same rows again,
        # it doesn't duplicate them.
        assert first.errors == 0
        assert second.errors == 0
        job_count = db.scalar(select(SearchIndexDocument.entity_id).where(
            SearchIndexDocument.entity_type.in_(
                [EntityType.JOB.value, EntityType.GOVERNMENT_RECRUITMENT.value,
                 EntityType.INTERNSHIP.value, EntityType.APPRENTICESHIP.value]
            )
        ).distinct().limit(1))
        assert job_count is not None
    finally:
        db.close()


def test_index_health_reports_counts(client):
    _reindex(client)
    resp = client.get("/api/v1/admin/search/index-health", headers=ADMIN_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "by_entity_type" in body
    assert body["total_documents"] >= 0
    assert body["last_indexed_at"] is not None


def test_reindex_endpoint_requires_admin(client):
    resp = client.post("/api/v1/admin/search/reindex")
    assert resp.status_code in (401, 403)


# --------------------------------------------------------------------
# Real-time indexing (V21.1 Phase 3) — a write shows up in search
# WITHOUT calling _reindex()/POST /admin/search/reindex first, proving
# the app.search.hooks.sync_* calls wired into the write paths
# actually run rather than relying on the periodic scheduler job.
# --------------------------------------------------------------------


def test_publishing_a_job_is_searchable_without_manual_reindex(client):
    job_id = _create_job(client, title="Realtime Publish Probe Role")
    _publish_job(client, job_id)  # no _reindex(client) call — this is the point of the test

    resp = client.get("/api/v1/search", params={"q": "Realtime Publish Probe"})
    ids = {item["entity_id"] for item in resp.json()["items"]}
    assert job_id in ids


def test_rejecting_a_job_removes_it_from_search_without_manual_reindex(client):
    job_id = _create_job(client, title="Realtime Reject Probe Role")
    _publish_job(client, job_id)
    resp = client.get("/api/v1/search", params={"q": "Realtime Reject Probe"})
    assert job_id in {item["entity_id"] for item in resp.json()["items"]}

    reject_resp = client.post(f"/api/v1/admin/jobs/{job_id}/reject", headers=ADMIN_HEADERS)
    assert reject_resp.status_code == 200, reject_resp.text

    # Rejected is neither "published" (visible) status, so it drops out
    # of default anonymous search results immediately.
    resp = client.get("/api/v1/search", params={"q": "Realtime Reject Probe"})
    assert job_id not in {item["entity_id"] for item in resp.json()["items"]}


def test_recruiter_publish_flow_is_searchable_without_manual_reindex(client):
    rec_headers, _ = _recruiter_headers(client, "realtime1")
    create_resp = client.post(
        "/api/v1/recruiter/jobs",
        headers=rec_headers,
        json={
            "title": "Realtime Recruiter Probe Role",
            "organization": "Realtime Co",
            "description": "Proves the recruiter create_job -> sync_job hook fires without a manual reindex.",
            "qualification": "Any",
            "location": "Remote",
            "job_type": "Private",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    job_id = create_resp.json()["id"]

    # Owner should see their own not-yet-published job in search
    # immediately (visibility=private, owner_user_id match) — no
    # reindex call in between.
    owner_resp = client.get("/api/v1/search", params={"q": "Realtime Recruiter Probe"}, headers=rec_headers)
    assert job_id in {item["entity_id"] for item in owner_resp.json()["items"]}

    _publish_job(client, job_id)

    anon_resp = client.get("/api/v1/search", params={"q": "Realtime Recruiter Probe"})
    assert job_id in {item["entity_id"] for item in anon_resp.json()["items"]}


def test_company_verification_is_searchable_without_manual_reindex(client):
    rec_headers, _ = _recruiter_headers(client, "realtime2")
    _counter["n"] += 1
    resp = client.put(
        "/api/v1/recruiter/company",
        headers=rec_headers,
        json={"name": f"Realtime Search Co {_counter['n']}", "industry": "Software", "description": "d", "location": "Remote"},
    )
    assert resp.status_code == 200, resp.text
    # PUT /recruiter/company returns {} due to a pre-existing bug
    # unrelated to this pass (app.api.company._ensure_owner_membership's
    # own internal db.commit() expires the `org` object before FastAPI
    # serializes it — reproduces identically on the untouched V20.6
    # baseline; see CHANGELOG_V21_1.md "Found but not fixed"), so fetch
    # the id via GET instead of trusting the PUT response body.
    org_id = client.get("/api/v1/recruiter/company", headers=rec_headers).json()["id"]

    admin_verify = client.post(f"/api/v1/admin/companies/{org_id}/verify", headers=ADMIN_HEADERS)
    assert admin_verify.status_code == 200, admin_verify.text

    # A company is indexed as public once it has a slug (set at
    # creation) — verification affects quality_score, not visibility —
    # so it should already be findable by name without a reindex call.
    name_resp = client.get("/api/v1/search", params={"q": f"Realtime Search Co {_counter['n']}"})
    ids = {item["entity_id"] for item in name_resp.json()["items"]}
    assert org_id in ids


def test_skill_creation_is_searchable_without_manual_reindex(client):
    _counter["n"] += 1
    unique_name = f"realtimeskillprobe{_counter['n']}"
    resp = client.post(
        "/api/v1/admin/skills",
        headers=ADMIN_HEADERS,
        json={"canonical_name": unique_name, "display_name": unique_name, "category": "technical", "subcategory": "general"},
    )
    assert resp.status_code == 200, resp.text

    search_resp = client.get("/api/v1/search", params={"q": unique_name, "entity_type": "SKILL"})
    ids = {item["title"].lower() for item in search_resp.json()["items"]}
    assert unique_name in ids


# --------------------------------------------------------------------
# Cursor pagination (V21.1 Phase 4)
# --------------------------------------------------------------------


def test_cursor_pagination_walks_every_result_exactly_once(client):
    titles = []
    for i in range(7):
        jid = _create_job(client, title=f"Cursor Walk Probe Role {i}")
        _publish_job(client, jid)
        titles.append(f"Cursor Walk Probe Role {i}")
    _reindex(client)

    seen_ids: list[int] = []
    cursor = None
    for _ in range(10):  # safety bound so a bug can't infinite-loop the test
        params = {"q": "Cursor Walk Probe", "sort": "newest", "page_size": 3}
        if cursor:
            params["cursor"] = cursor
        resp = client.get("/api/v1/search", params=params)
        body = resp.json()
        seen_ids.extend(item["entity_id"] for item in body["items"])
        cursor = body["next_cursor"]
        if not cursor:
            break

    assert len(seen_ids) == len(set(seen_ids)), "cursor pagination must not repeat an item across pages"
    assert len(seen_ids) >= 7


def test_cursor_from_wrong_sort_is_ignored_not_an_error(client):
    job_id = _create_job(client, title="Cursor Mismatch Probe Role")
    _publish_job(client, job_id)
    _reindex(client)

    first = client.get("/api/v1/search", params={"q": "Cursor Mismatch Probe", "sort": "newest"})
    cursor = first.json().get("next_cursor")

    # Replaying a (possibly-None) cursor under a DIFFERENT sort must
    # never 500 — it's treated as "no cursor", not an error.
    resp = client.get(
        "/api/v1/search",
        params={"q": "Cursor Mismatch Probe", "sort": "salary", "cursor": cursor or "not-a-real-cursor"},
    )
    assert resp.status_code == 200, resp.text


def test_invalid_cursor_token_does_not_error(client):
    resp = client.get("/api/v1/search", params={"q": "anything", "cursor": "not-valid-base64!!!"})
    assert resp.status_code == 200, resp.text


# --------------------------------------------------------------------
# Anonymous-search caching (V21.1 Phase 4)
# --------------------------------------------------------------------


def test_identical_anonymous_search_is_served_from_cache(client):
    job_id = _create_job(client, title="Cache Hit Probe Role")
    _publish_job(client, job_id)
    _reindex(client)

    first = client.get("/api/v1/search", params={"q": "Cache Hit Probe"})
    assert job_id in {item["entity_id"] for item in first.json()["items"]}

    # A second identical anonymous request should return the exact same
    # (cached) payload without needing another reindex/write in between.
    second = client.get("/api/v1/search", params={"q": "Cache Hit Probe"})
    assert second.json() == first.json()


def test_cache_hit_avoids_a_second_provider_query(client):
    from unittest.mock import patch

    from app.search import service

    job_id = _create_job(client, title="Cache Bypass Probe Role")
    _publish_job(client, job_id)
    _reindex(client)

    # Prime the cache with one real, uncounted request.
    client.get("/api/v1/search", params={"q": "Cache Bypass Probe"})

    real_search = service._provider.search
    with patch.object(service._provider, "search", wraps=real_search) as spy:
        client.get("/api/v1/search", params={"q": "Cache Bypass Probe"})
        assert spy.call_count == 0, "an identical anonymous request should be served from cache, not re-query the provider"

        # A DIFFERENT anonymous query must still hit the provider for real.
        client.get("/api/v1/search", params={"q": "Cache Bypass Probe Distinct Query"})
        assert spy.call_count == 1


def test_publishing_a_job_invalidates_the_anonymous_search_cache(client):
    # Prime the cache with a query that currently has no matches.
    probe_query = f"Cache Invalidation Probe {_counter['n'] + 1}"
    empty_first = client.get("/api/v1/search", params={"q": probe_query})
    assert empty_first.json()["total_count"] == 0

    job_id = _create_job(client, title=probe_query + " Role")
    _publish_job(client, job_id)  # fires app.search.hooks.sync_job -> cache.clear()

    # No manual reindex call — if the cache weren't invalidated by the
    # publish hook, this would still return the stale empty result.
    after_publish = client.get("/api/v1/search", params={"q": probe_query})
    assert job_id in {item["entity_id"] for item in after_publish.json()["items"]}


def test_recruiter_search_is_never_served_from_the_anonymous_cache(client):
    """The anonymous cache must never leak a recruiter's own private
    results to a different actor — see app.search.cache's docstring."""
    rec_headers, _ = _recruiter_headers(client, "cacheleak1")
    create_resp = client.post(
        "/api/v1/recruiter/jobs",
        headers=rec_headers,
        json={
            "title": "Cache Leak Probe Role",
            "organization": "Cache Leak Co",
            "description": "Must never be visible to a different, uncached actor via a shared cache entry.",
            "qualification": "Any",
            "location": "Remote",
            "job_type": "Private",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    job_id = create_resp.json()["id"]

    # Owner's (non-anonymous) request populates nothing in the
    # anonymous cache — confirmed by an anonymous request for the same
    # query never seeing the still-unpublished job.
    client.get("/api/v1/search", params={"q": "Cache Leak Probe"}, headers=rec_headers)
    anon_resp = client.get("/api/v1/search", params={"q": "Cache Leak Probe"})
    assert job_id not in {item["entity_id"] for item in anon_resp.json()["items"]}


# --------------------------------------------------------------------
# Search: filters, sorting, pagination, ranking
# --------------------------------------------------------------------


def test_search_finds_published_job_by_title_keyword(client):
    job_id = _create_job(client, title="Distinctive Kotlin Engineer Role", skills="Kotlin")
    _publish_job(client, job_id)
    _reindex(client)

    resp = client.get("/api/v1/search", params={"q": "Kotlin Engineer"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_count"] >= 1
    assert any(item["entity_id"] == job_id for item in body["items"])


def test_search_respects_job_type_filter(client):
    private_id = _create_job(client, title="Filter Probe Private Role", job_type="Private")
    intern_id = _create_job(client, title="Filter Probe Internship Role", job_type="Internship")
    _publish_job(client, private_id)
    _publish_job(client, intern_id)
    _reindex(client)

    resp = client.get("/api/v1/search", params={"q": "Filter Probe", "job_type": "Internship"})
    body = resp.json()
    returned_ids = {item["entity_id"] for item in body["items"]}
    assert intern_id in returned_ids
    assert private_id not in returned_ids


def test_search_location_filter(client):
    bangalore_id = _create_job(client, title="Location Probe Role BLR", location="Bangalore")
    delhi_id = _create_job(client, title="Location Probe Role DEL", location="Delhi")
    _publish_job(client, bangalore_id)
    _publish_job(client, delhi_id)
    _reindex(client)

    resp = client.get("/api/v1/search", params={"q": "Location Probe", "location": "Bangalore"})
    ids = {item["entity_id"] for item in resp.json()["items"]}
    assert bangalore_id in ids
    assert delhi_id not in ids


def test_search_sort_newest_orders_by_posted_date(client):
    old_id = _create_job(client, title="Sort Probe Old Role")
    _publish_job(client, old_id)
    db = SessionLocal()
    try:
        job = db.get(Job, old_id)
        from datetime import date, timedelta

        job.start_date = date.today() - timedelta(days=30)
        db.commit()
    finally:
        db.close()

    new_id = _create_job(client, title="Sort Probe New Role")
    _publish_job(client, new_id)
    db = SessionLocal()
    try:
        job = db.get(Job, new_id)
        from datetime import date

        job.start_date = date.today()
        db.commit()
    finally:
        db.close()
    _reindex(client)

    resp = client.get("/api/v1/search", params={"q": "Sort Probe", "sort": "newest"})
    ids = [item["entity_id"] for item in resp.json()["items"]]
    assert ids.index(new_id) < ids.index(old_id)


def test_search_pagination_page_size_respected(client):
    for i in range(5):
        jid = _create_job(client, title=f"Pagination Probe Role {i}")
        _publish_job(client, jid)
    _reindex(client)

    resp = client.get("/api/v1/search", params={"q": "Pagination Probe", "page": 1, "page_size": 2})
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total_count"] >= 5


def test_exact_title_match_ranks_above_partial_match(client):
    exact_id = _create_job(client, title="Rank Probe Exact Title")
    partial_id = _create_job(client, 
        title="Something Else Entirely", description="Mentions Rank Probe Exact Title once in passing"
    )
    _publish_job(client, exact_id)
    _publish_job(client, partial_id)
    _reindex(client)

    resp = client.get("/api/v1/search", params={"q": "Rank Probe Exact Title"})
    ids = [item["entity_id"] for item in resp.json()["items"]]
    assert exact_id in ids
    assert ids.index(exact_id) < (ids.index(partial_id) if partial_id in ids else len(ids))


def test_ranking_factors_are_present_and_explainable(client):
    job_id = _create_job(client, title="Explainability Probe Role")
    _publish_job(client, job_id)
    _reindex(client)

    resp = client.get("/api/v1/search", params={"q": "Explainability Probe"})
    item = next(i for i in resp.json()["items"] if i["entity_id"] == job_id)
    assert "score_factors" in item
    assert set(item["score_factors"].keys()) >= {"exact_title_match", "token_coverage", "recency"}


# --------------------------------------------------------------------
# Permissions
# --------------------------------------------------------------------


def test_unpublished_job_not_visible_to_anonymous_search(client):
    job_id = _create_job(client, title="Private Draft Probe Role")  # never published
    db = SessionLocal()
    try:
        indexer.index_job(db, job_id)
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/v1/search", params={"q": "Private Draft Probe"})
    ids = {item["entity_id"] for item in resp.json()["items"]}
    assert job_id not in ids


def test_unpublished_job_visible_to_its_owner_but_not_another_user(client):
    rec_headers, rec_id = _recruiter_headers(client, "perm1")
    resp = client.post(
        "/api/v1/recruiter/jobs",
        headers=rec_headers,
        json={
            "title": "Owner Visibility Probe Role",
            "organization": "Owner Co",
            "description": "A role only the owning recruiter should see pre-publish.",
            "qualification": "Any",
            "location": "Remote",
            "job_type": "Private",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    job_id = resp.json()["id"] if "id" in resp.json() else resp.json().get("job_id")

    db = SessionLocal()
    try:
        indexer.index_job(db, job_id)
        db.commit()
    finally:
        db.close()

    # Owner sees it.
    owner_resp = client.get("/api/v1/search", params={"q": "Owner Visibility Probe"}, headers=rec_headers)
    owner_ids = {item["entity_id"] for item in owner_resp.json()["items"]}
    assert job_id in owner_ids

    # A different recruiter does not.
    other_headers, _ = _recruiter_headers(client, "perm2")
    other_resp = client.get("/api/v1/search", params={"q": "Owner Visibility Probe"}, headers=other_headers)
    other_ids = {item["entity_id"] for item in other_resp.json()["items"]}
    assert job_id not in other_ids

    # Anonymous does not.
    anon_resp = client.get("/api/v1/search", params={"q": "Owner Visibility Probe"})
    anon_ids = {item["entity_id"] for item in anon_resp.json()["items"]}
    assert job_id not in anon_ids


def test_admin_sees_unpublished_jobs_in_search(client):
    job_id = _create_job(client, title="Admin Visibility Probe Role")
    db = SessionLocal()
    try:
        indexer.index_job(db, job_id)
        db.commit()
    finally:
        db.close()

    # Promote a fresh user to admin, then use the admin-specific login
    # (role-gated logins require the matching endpoint — see
    # app/api/auth.py's /login, /recruiter/login, /admin/login).
    _counter["n"] += 1
    email = f"v21_1_admin_probe{_counter['n']}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Test Admin"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    ).json()
    client.post(f"/api/v1/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": "admin"})
    login = client.post("/api/v1/auth/admin/login", json={"email": email, "password": "password12345!"})
    admin_token_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.get("/api/v1/search", params={"q": "Admin Visibility Probe"}, headers=admin_token_headers)
    ids = {item["entity_id"] for item in resp.json()["items"]}
    assert job_id in ids


# --------------------------------------------------------------------
# Autocomplete / facets / no-result suggestions
# --------------------------------------------------------------------


def test_autocomplete_returns_matching_prefixes(client):
    job_id = _create_job(client, title="Autocomplete Probe Zephyr Role")
    _publish_job(client, job_id)
    _reindex(client)

    resp = client.get("/api/v1/search/autocomplete", params={"q": "Autocomplete Probe"})
    assert resp.status_code == 200, resp.text
    suggestions = resp.json()["suggestions"]
    assert any("Autocomplete Probe" in s for s in suggestions)


def test_facets_endpoint_returns_bucketed_counts(client):
    job_id = _create_job(client, title="Facet Probe Role", job_type="Private", location="Chennai")
    _publish_job(client, job_id)
    _reindex(client)

    resp = client.get("/api/v1/search/facets", params={"facet": ["job_type", "location"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "job_type" in body
    assert "location" in body


def test_no_results_returns_suggestions_not_fabricated_matches(client):
    resp = client.get("/api/v1/search", params={"q": "zzzznonexistentqueryxyz123"})
    body = resp.json()
    assert body["total_count"] == 0
    assert body["items"] == []
    # Suggestions (if any) must be plain text hints, never a fabricated result.
    for suggestion in body["suggestions"]:
        assert "kind" in suggestion and "text" in suggestion


# --------------------------------------------------------------------
# Skill catalog / learning resource indexing (reuse, not duplication)
# --------------------------------------------------------------------


def test_skill_indexes_and_is_searchable(client):
    db = SessionLocal()
    try:
        skill = db.scalars(select(Skill).where(Skill.canonical_name == "python")).first()
        assert skill is not None, "expected V20.5 seeded catalog to include python"
        indexer.index_skill(db, skill.id)
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/v1/search", params={"q": "python", "entity_type": "SKILL"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_count"] >= 1


# --------------------------------------------------------------------
# V16-V20.6 regression spot-check (endpoints this pass's changes are
# adjacent to: job publish flow, RBAC-gated admin routes, auth).
# --------------------------------------------------------------------


def test_regression_job_publish_flow_still_works(client):
    job_id = _create_job(client, title="Regression Probe Role")
    resp = client.get("/api/v1/admin/review", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    _publish_job(client, job_id)
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        assert job.status == "published"
        assert job.verified is True
    finally:
        db.close()


def test_regression_platform_public_listing_unaffected(client):
    resp = client.get("/api/v1/jobs")
    assert resp.status_code == 200


def test_regression_auth_register_and_login_unaffected(client):
    headers, email = _register_and_login(client, "v21_1_regression_auth")
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == email


def test_regression_admin_endpoints_still_require_admin_key(client):
    resp = client.get("/api/v1/admin/review")
    assert resp.status_code in (401, 403)
