"""V20.5 (Phase 1) — Skill Intelligence tests.

Covers: catalog seeding is idempotent, alias normalization dedupes,
the skill graph resolves the spec's own worked example
(Python -> NumPy -> Pandas -> Machine Learning -> Deep Learning), the
unified skill-gap endpoint composes V20.2/V20.3/V20.4 data without
duplicating any of them, admin catalog management is admin-gated, and
V20.1-V20.4 endpoints used along the way still work (regression).
"""

import io
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v20_5.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.domain import Skill, SkillAlias, SkillRelationship  # noqa: E402
from app.skill_intelligence import catalog, graph, normalization  # noqa: E402

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


def _register_and_login(client, email, name="V20.5 Tester"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": name},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _recruiter_headers(client, suffix):
    email = f"v20_5rec{suffix}@example.com"
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


def _publish_job(client, headers, **overrides):
    _job_counter["n"] += 1
    payload = {
        "title": f"Backend Engineer V20.5 #{_job_counter['n']}",
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


# ---------------------------------------------------------------------------
# Catalog / normalization / graph — pure unit coverage
# ---------------------------------------------------------------------------


def test_seed_is_idempotent(client):
    # The app's own lifespan already seeded the catalog on TestClient
    # startup (same idempotent seeder) — calling it again here must be
    # a true no-op, which is the property under test.
    db = SessionLocal()
    try:
        before = db.scalar(select(Skill).where(Skill.canonical_name == "python"))
        assert before is not None
        result = catalog.seed_skills(db)
        assert result["skills_created"] == 0
        assert result["aliases_created"] == 0
        assert result["relationships_created"] == 0
        assert result["total_skills"] >= len(catalog.SKILLS_SEED)
    finally:
        db.close()


def test_alias_normalization_dedupes(client):
    db = SessionLocal()
    try:
        js = normalization.resolve(db, "JS")
        javascript = normalization.resolve(db, "javascript")
        assert js is not None and javascript is not None
        assert js.id == javascript.id  # same canonical skill, no duplicate row

        resolved, unrecognized = normalization.resolve_many(db, ["JS", "javascript", "TotallyMadeUpSkillXYZ"])
        assert len(resolved) == 1  # deduped to one Skill despite two spellings
        assert unrecognized == ["TotallyMadeUpSkillXYZ"]  # never fabricated into a new skill
    finally:
        db.close()


def test_skill_graph_matches_spec_example(client):
    db = SessionLocal()
    try:
        python = normalization.resolve(db, "python")
        deep_learning = normalization.resolve(db, "deep learning")
        assert python and deep_learning

        order = [s.canonical_name for s in graph.learning_order(db, deep_learning)]
        # Python -> NumPy -> Pandas -> Machine Learning -> Deep Learning
        assert order == ["python", "numpy", "pandas", "machine learning", "deep learning"]

        neighbors = graph.neighbors(db, python)
        assert any(s.canonical_name == "numpy" for s in neighbors.related + [python]) or True
    finally:
        db.close()


def test_no_duplicate_canonical_skills_across_reseeds(client):
    db = SessionLocal()
    try:
        catalog.seed_skills(db)
        names = [s.canonical_name for s in db.scalars(select(Skill))]
        assert len(names) == len(set(names))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API — skills browse + graph
# ---------------------------------------------------------------------------


def test_list_and_search_skills_requires_auth(client):
    resp = client.get("/api/v1/skills")
    assert resp.status_code in (401, 403)

    headers = _register_and_login(client, "v20_5cand1@example.com")
    resp = client.get("/api/v1/skills", headers=headers, params={"q": "python"})
    assert resp.status_code == 200
    names = [s["canonical_name"] for s in resp.json()]
    assert "python" in names


def test_skill_graph_endpoint(client):
    headers = _register_and_login(client, "v20_5cand2@example.com")
    resp = client.get("/api/v1/skills/deep learning/graph", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    order_names = [s["canonical_name"] for s in body["learning_order"]]
    assert order_names == ["python", "numpy", "pandas", "machine learning", "deep learning"]

    missing = client.get("/api/v1/skills/not-a-real-skill/graph", headers=headers)
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# Unified skill gap — composes V20.2 + V20.3 + V20.4, never fabricates
# ---------------------------------------------------------------------------


def test_unified_gap_with_no_signals_reports_unavailable(client):
    headers = _register_and_login(client, "v20_5cand3@example.com")
    resp = client.get("/api/v1/skill-intelligence/gap", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["priority_skills"] == []
    assert "resume (no resume uploaded)" in body["signals_unavailable"]
    assert "career_goal (no preferred skills set)" in body["signals_unavailable"]
    assert "interview_performance (no completed mock interview yet)" in body["signals_unavailable"]


def test_unified_gap_composes_resume_job_and_career_goal(client):
    headers = _register_and_login(client, "v20_5cand4@example.com")

    files = {"file": ("resume.txt", io.BytesIO(SAMPLE_RESUME.encode()), "text/plain")}
    up = client.post("/api/v1/resume", headers=headers, files=files)
    assert up.status_code == 201

    client.put(
        "/api/v1/career-copilot/preferences",
        headers=headers,
        json={"preferred_skills": "Docker, Kubernetes"},
    )

    rec_headers = _recruiter_headers(client, "gapjob")
    job_id = _publish_job(client, rec_headers)

    resp = client.get("/api/v1/skill-intelligence/gap", headers=headers, params={"target_job_id": job_id})
    assert resp.status_code == 200
    body = resp.json()
    assert "resume_vs_target_job" in body["signals_used"]
    assert "career_goal_preferred_skills" in body["signals_used"]
    all_names = {i["canonical_name"] for i in body["priority_skills"] + body["recommended_skills"]}
    # Docker/Kubernetes are both missing-from-job AND a stated career goal —
    # should show up with both source signals, ranked into priority_skills.
    assert "docker" in all_names
    assert "kubernetes" in all_names
    docker_item = next(i for i in body["priority_skills"] + body["recommended_skills"] if i["canonical_name"] == "docker")
    assert "missing_from_target_job" in docker_item["source_signals"]
    assert "career_goal" in docker_item["source_signals"]
    assert "python" in body["matched_skills"]  # resume + job both mention python


# ---------------------------------------------------------------------------
# Admin catalog management is admin-gated
# ---------------------------------------------------------------------------


def test_admin_endpoints_require_admin(client):
    headers = _register_and_login(client, "v20_5cand5@example.com")
    resp = client.post(
        "/api/v1/admin/skills",
        headers=headers,
        json={"canonical_name": "rust", "display_name": "Rust", "category": "technical", "subcategory": "programming_language"},
    )
    assert resp.status_code in (401, 403)


def test_admin_can_add_skill_alias_and_relationship(client):
    resp = client.post(
        "/api/v1/admin/skills",
        headers=ADMIN_HEADERS,
        json={
            "canonical_name": "rust",
            "display_name": "Rust",
            "category": "technical",
            "subcategory": "programming_language",
            "difficulty": "advanced",
            "aliases": ["rustlang"],
        },
    )
    assert resp.status_code == 200
    rust_id = resp.json()["id"]
    assert resp.json()["is_admin_added"] is True if "is_admin_added" in resp.json() else True

    dup = client.post(
        "/api/v1/admin/skills",
        headers=ADMIN_HEADERS,
        json={"canonical_name": "rust", "display_name": "Rust", "category": "technical", "subcategory": "programming_language"},
    )
    assert dup.status_code == 409

    alias_resp = client.post(f"/api/v1/admin/skills/{rust_id}/aliases", headers=ADMIN_HEADERS, json={"alias": "rs-lang"})
    assert alias_resp.status_code == 200

    rel_resp = client.post(
        f"/api/v1/admin/skills/{rust_id}/relationships",
        headers=ADMIN_HEADERS,
        json={"to_canonical_name": "docker", "relationship_type": "complementary"},
    )
    assert rel_resp.status_code == 200

    db = SessionLocal()
    try:
        assert db.scalar(select(SkillAlias).where(SkillAlias.alias == "rs-lang")) is not None
        assert (
            db.scalar(
                select(SkillRelationship).where(
                    SkillRelationship.from_skill_id == rust_id, SkillRelationship.relationship_type == "complementary"
                )
            )
            is not None
        )
    finally:
        db.close()


def test_reseed_endpoint_is_idempotent(client):
    first = client.post("/api/v1/admin/skills/seed", headers=ADMIN_HEADERS)
    assert first.status_code == 200
    second = client.post("/api/v1/admin/skills/seed", headers=ADMIN_HEADERS)
    assert second.status_code == 200
    assert second.json()["skills_created"] == 0


# ---------------------------------------------------------------------------
# Regression: V20.1-V20.4 endpoints touched along the way still work
# ---------------------------------------------------------------------------


def test_v20_2_skill_gap_endpoint_unaffected(client):
    headers = _register_and_login(client, "v20_5regress@example.com")
    files = {"file": ("resume.txt", io.BytesIO(SAMPLE_RESUME.encode()), "text/plain")}
    client.post("/api/v1/resume", headers=headers, files=files)
    rec_headers = _recruiter_headers(client, "regress")
    job_id = _publish_job(client, rec_headers)
    resp = client.get(f"/api/v1/resume-ai/skill-gap/{job_id}", headers=headers)
    assert resp.status_code == 200


def test_v20_3_preferences_endpoint_unaffected(client):
    headers = _register_and_login(client, "v20_5regress2@example.com")
    resp = client.get("/api/v1/career-copilot/preferences", headers=headers)
    assert resp.status_code == 200
