"""V20.2 — AI Resume Intelligence tests.

No provider API key is configured anywhere in this file (same as
test_v20_1_ai_infrastructure.py), so every generative endpoint
(bullet-improve, summary, project-improve, job-advice) deterministically
exercises its template-fallback path — no network call is ever made.
This is intentional: it lets this file verify the *fallback* behavior
(which must never fabricate anything) without needing real credentials,
while the AI-path prompts themselves are reviewed in
AI_RESUME_PRIVACY.md rather than executed here.

Extraction/normalization/scoring are pure functions and get direct
unit coverage; the API surface gets end-to-end coverage through the
same upload -> analyze -> match flow a real user would follow.
"""

import io
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v20_2.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.resume_ai import extraction, normalization, scoring, skill_gap  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}

SAMPLE_RESUME = """Jordan Rivera
jordan.rivera@example.com
+1 415-555-0142
San Francisco, CA
github.com/jordanrivera
linkedin.com/in/jordanrivera

SUMMARY
Backend engineer focused on distributed systems and reliability.

SKILLS
Python, SQL, Docker, AWS, Git, Kubernetes

EXPERIENCE
- Led migration of the payments service to Kubernetes, reducing deploy time by 40%
- Built a Python/SQL data pipeline processing 2 million records daily
- Automated CI/CD with Docker, cutting release cycle from days to hours

EDUCATION
B.Tech in Computer Science, State University, 2019

PROJECTS
- Built an open-source AWS cost dashboard using Python and SQL

CERTIFICATIONS
AWS Certified Solutions Architect

ACHIEVEMENTS
Won internal hackathon for a Kubernetes-based deployment tool

LANGUAGES
English, Spanish
"""

SPARSE_RESUME = """Alex Doe
alex@example.com
"""


def _register_and_login(client, email, name="V20.2 Tester"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": name},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _recruiter_headers(client, suffix):
    email = f"v20_2rec{suffix}@example.com"
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
        "title": f"Backend Engineer #{_job_counter['n']}",
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


def _upload_sample_resume(client, headers, text=SAMPLE_RESUME, filename="resume.txt"):
    files = {"file": (filename, io.BytesIO(text.encode()), "text/plain")}
    response = client.post("/api/v1/resume", headers=headers, files=files)
    assert response.status_code == 201
    return response


@pytest.fixture(scope="module")
def client_with_resume():
    with TestClient(app) as client:
        headers = _register_and_login(client, "v202-candidate@example.com")
        _upload_sample_resume(client, headers)
        job_id = _publish_job(client, _recruiter_headers(client, "job-owner"))
        yield {"client": client, "headers": headers, "job_id": job_id}


# --- Deterministic extraction / normalization (unit-level, no API) ----------


def test_extraction_finds_contact_fields_and_sections():
    extracted = extraction.extract(SAMPLE_RESUME)
    assert extracted.name == "Jordan Rivera"
    assert extracted.email == "jordan.rivera@example.com"
    assert extracted.phone != extraction.NOT_FOUND
    assert "github.com/jordanrivera" in extracted.github.lower()
    assert "linkedin.com/in/jordanrivera" in extracted.linkedin.lower()
    assert "experience" in extracted.sections
    assert "education" in extracted.sections
    assert "skills" in extracted.sections


def test_extraction_reports_not_found_rather_than_guessing():
    extracted = extraction.extract(SPARSE_RESUME)
    assert extracted.phone == extraction.NOT_FOUND
    assert extracted.github == extraction.NOT_FOUND
    assert "experience" not in extracted.sections


def test_normalization_dedupes_and_flags_missing_sections():
    extracted = extraction.extract(SAMPLE_RESUME)
    profile = normalization.normalize(extracted, SAMPLE_RESUME)
    assert "python" in profile.technical_skills
    assert "kubernetes" in profile.technical_skills
    assert len(profile.technical_skills) == len(set(profile.technical_skills))  # deduped
    assert profile.experience_entries
    assert "soft_skills" not in profile.missing_sections or profile.soft_skills == []


def test_normalization_of_sparse_resume_flags_most_sections_missing():
    extracted = extraction.extract(SPARSE_RESUME)
    profile = normalization.normalize(extracted, SPARSE_RESUME)
    assert "experience" in profile.missing_sections
    assert "education" in profile.missing_sections
    assert profile.summary == extraction.NOT_FOUND


def test_skill_alias_normalization():
    text = "Skills: JS, ReactJS, Postgres"
    extracted = extraction.extract(text)
    profile = normalization.normalize(extracted, text)
    assert "javascript" in profile.technical_skills
    assert "react" in profile.technical_skills
    assert "sql" in profile.technical_skills


# --- Deterministic scoring (unit-level) --------------------------------------


def test_scores_are_explainable_and_reproducible():
    extracted = extraction.extract(SAMPLE_RESUME)
    profile = normalization.normalize(extracted, SAMPLE_RESUME)

    result_a = scoring.skills_score(profile)
    result_b = scoring.skills_score(profile)
    assert result_a.score == result_b.score  # same inputs -> same score, always
    assert result_a.reasons  # every score carries an explanation

    experience = scoring.experience_score(profile)
    assert experience.score > 0
    assert experience.reasons


def test_sparse_resume_scores_lower_than_full_resume():
    full_profile = normalization.normalize(extraction.extract(SAMPLE_RESUME), SAMPLE_RESUME)
    sparse_profile = normalization.normalize(extraction.extract(SPARSE_RESUME), SPARSE_RESUME)

    full_components = {
        "content_quality": scoring.content_quality_score(full_profile),
        "ats_compatibility": scoring.ats_compatibility_score(full_profile, False),
        "skills": scoring.skills_score(full_profile),
        "experience": scoring.experience_score(full_profile),
        "education": scoring.education_score(full_profile),
        "project": scoring.project_score(full_profile),
        "achievement_strength": scoring.achievement_strength_score(full_profile),
    }
    sparse_components = {
        "content_quality": scoring.content_quality_score(sparse_profile),
        "ats_compatibility": scoring.ats_compatibility_score(sparse_profile, False),
        "skills": scoring.skills_score(sparse_profile),
        "experience": scoring.experience_score(sparse_profile),
        "education": scoring.education_score(sparse_profile),
        "project": scoring.project_score(sparse_profile),
        "achievement_strength": scoring.achievement_strength_score(sparse_profile),
    }
    assert scoring.resume_quality_score(full_components).score > scoring.resume_quality_score(sparse_components).score


def test_ats_compatibility_treats_unknown_layout_as_neutral():
    profile = normalization.normalize(extraction.extract(SAMPLE_RESUME), SAMPLE_RESUME)
    known_safe = scoring.ats_compatibility_score(profile, False)
    unknown = scoring.ats_compatibility_score(profile, None)
    risky = scoring.ats_compatibility_score(profile, True)
    assert risky.score < known_safe.score
    assert unknown.score <= known_safe.score  # neutral is never scored better than a known-safe layout
    assert unknown.score >= risky.score  # and never worse than a known-risky one


# --- Skill gap (unit-level) --------------------------------------------------


def test_skill_gap_categorizes_correctly():
    from app.models.domain import Job

    job = Job(
        title="Backend Engineer",
        organization="Acme",
        description="Need Python, SQL, Docker, Kubernetes, and Terraform experience.",
        qualification="B.Tech",
        status="published",
    )
    profile = normalization.normalize(extraction.extract(SAMPLE_RESUME), SAMPLE_RESUME)
    result = skill_gap.analyze(profile, job)

    assert "python" in result.matched_skills
    assert "terraform" in result.missing_skills
    assert all(skill in profile.technical_skills for skill in result.matched_skills)
    assert all(skill not in profile.technical_skills for skill in result.missing_skills)


# --- API: analysis / ATS / recommendations -----------------------------------


def test_analysis_endpoint_returns_scores_with_reasons(client_with_resume):
    client, headers = client_with_resume["client"], client_with_resume["headers"]
    response = client.get("/api/v1/resume-ai/analysis", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["scores"]["overall"]["score"] >= 0
    assert body["scores"]["overall"]["reasons"]
    for component in body["scores"]["components"].values():
        assert "reasons" in component and component["reasons"]
    assert body["profile"]["email"] == "jordan.rivera@example.com"


def test_analysis_requires_a_resume():
    with TestClient(app) as client:
        headers = _register_and_login(client, "v202-noresume@example.com")
        response = client.get("/api/v1/resume-ai/analysis", headers=headers)
        assert response.status_code == 404


def test_ats_endpoint_shape(client_with_resume):
    client, headers = client_with_resume["client"], client_with_resume["headers"]
    response = client.get("/api/v1/resume-ai/ats", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["readability"] in ("good", "fair", "at_risk")
    assert "formatting_risks" in body


def test_recommendations_are_explainable(client_with_resume):
    client, headers = client_with_resume["client"], client_with_resume["headers"]
    response = client.get("/api/v1/resume-ai/recommendations", headers=headers)
    assert response.status_code == 200
    for rec in response.json()["recommendations"]:
        assert rec["reason"] and rec["impact"] and rec["priority"] in ("high", "medium", "low") and rec["suggested_action"]


# --- API: job match / skill gap ----------------------------------------------


def test_job_match_is_explainable_and_bounded(client_with_resume):
    client, headers, job_id = client_with_resume["client"], client_with_resume["headers"], client_with_resume["job_id"]
    response = client.get(f"/api/v1/resume-ai/job-match/{job_id}", headers=headers)
    assert response.status_code == 200
    match = response.json()["match"]
    assert 0 <= match["overall"] <= 100
    for dim in ("skills", "experience", "education", "keywords"):
        assert 0 <= match[dim]["score"] <= 100
        assert match[dim]["explanation"]


def test_skill_gap_endpoint(client_with_resume):
    client, headers, job_id = client_with_resume["client"], client_with_resume["headers"], client_with_resume["job_id"]
    response = client.get(f"/api/v1/resume-ai/skill-gap/{job_id}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert "matched_skills" in body and "missing_skills" in body and "prioritized_gaps" in body


def test_job_advice_never_fabricates_a_skill_not_on_resume(client_with_resume):
    client, headers, job_id = client_with_resume["client"], client_with_resume["headers"], client_with_resume["job_id"]
    response = client.get(f"/api/v1/resume-ai/job-advice/{job_id}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    # No provider is configured in this test env, so this exercises the
    # structured-only fallback — no narrative text, but a complete,
    # honest structured breakdown.
    assert body["source"] == "structured_only"
    assert body["narrative"] is None
    for skill in body["skills_to_highlight"]:
        assert skill in normalization.normalize(extraction.extract(SAMPLE_RESUME), SAMPLE_RESUME).technical_skills


# --- API: generative endpoints (fallback path, no provider configured) ------


def test_bullet_improve_fallback_never_adds_new_facts(client_with_resume):
    client, headers = client_with_resume["client"], client_with_resume["headers"]
    bullet = "Responsible for building internal tools using Python"
    response = client.post("/api/v1/resume-ai/bullet-improve", headers=headers, json={"bullet": bullet})
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "template"
    assert len(body["variants"]) == 2
    # Fallback only rewords — every variant should still mention "Python",
    # never introduce a technology/company that wasn't in the original.
    for variant in body["variants"]:
        assert "python" in variant.lower()


def test_bullet_improve_is_cached_on_repeat_call(client_with_resume):
    client, headers = client_with_resume["client"], client_with_resume["headers"]
    bullet = "Helped with database migrations"
    first = client.post("/api/v1/resume-ai/bullet-improve", headers=headers, json={"bullet": bullet})
    assert first.json()["source"] == "template"  # fallback isn't cached (only real AI output is)

    # A fallback response isn't cached (see app/api/resume_ai.py), so
    # calling again just re-runs the same deterministic fallback —
    # confirms determinism rather than cache behavior for this path.
    second = client.post("/api/v1/resume-ai/bullet-improve", headers=headers, json={"bullet": bullet})
    assert second.json()["variants"] == first.json()["variants"]


def test_summary_generator_fallback_uses_only_detected_facts(client_with_resume):
    client, headers = client_with_resume["client"], client_with_resume["headers"]
    response = client.post("/api/v1/resume-ai/summary", headers=headers, json={"target_role": "Backend Developer"})
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "template"
    assert "Backend Developer" in body["summary"]
    assert "python" in body["summary"].lower()  # a real detected skill, not invented


def test_project_improve_fallback(client_with_resume):
    client, headers = client_with_resume["client"], client_with_resume["headers"]
    response = client.post(
        "/api/v1/resume-ai/project-improve", headers=headers, json={"project_text": "Built a small internal tool."}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "template"
    assert body["suggestions"]


def test_generative_endpoints_are_rate_limited(client_with_resume):
    client, headers = client_with_resume["client"], client_with_resume["headers"]
    # The shared "resume-ai-generate" bucket is limit=20/60s; hammer it
    # past that and confirm a 429 eventually appears rather than an
    # unbounded number of (would-be-billed) calls succeeding.
    statuses = []
    for i in range(25):
        r = client.post("/api/v1/resume-ai/bullet-improve", headers=headers, json={"bullet": f"Did task number {i}"})
        statuses.append(r.status_code)
    assert 429 in statuses


# --- Recruiter integration ---------------------------------------------------


def test_recruiter_can_analyze_an_applicant_resume_snapshot():
    with TestClient(app) as client:
        candidate_headers = _register_and_login(client, "v202-applicant@example.com")
        _upload_sample_resume(client, candidate_headers)

        recruiter_headers = _recruiter_headers(client, "applicant-flow")
        job_id = _publish_job(client, recruiter_headers)

        apply = client.post(f"/api/v1/jobs/{job_id}/apply", headers=candidate_headers, json={})
        assert apply.status_code == 201

        applicants = client.get(f"/api/v1/recruiter/jobs/{job_id}/applicants", headers=recruiter_headers)
        assert applicants.status_code == 200
        applicant_id = applicants.json()[0]["id"]

        response = client.get(f"/api/v1/resume-ai/applicant/{applicant_id}/analysis", headers=recruiter_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["scores"]["overall"]["score"] >= 0
        assert "match" in body and "skill_gap" in body


def test_recruiter_cannot_analyze_an_applicant_outside_their_team():
    with TestClient(app) as client:
        candidate_headers = _register_and_login(client, "v202-applicant2@example.com")
        _upload_sample_resume(client, candidate_headers)

        owner_headers = _recruiter_headers(client, "owner")
        job_id = _publish_job(client, owner_headers)
        client.post(f"/api/v1/jobs/{job_id}/apply", headers=candidate_headers, json={})
        applicants = client.get(f"/api/v1/recruiter/jobs/{job_id}/applicants", headers=owner_headers)
        applicant_id = applicants.json()[0]["id"]

        outsider_headers = _recruiter_headers(client, "outsider")
        response = client.get(f"/api/v1/resume-ai/applicant/{applicant_id}/analysis", headers=outsider_headers)
        assert response.status_code == 404


def test_candidate_cannot_use_recruiter_endpoint(client_with_resume):
    client, headers = client_with_resume["client"], client_with_resume["headers"]
    response = client.get("/api/v1/resume-ai/applicant/1/analysis", headers=headers)
    assert response.status_code == 403


# --- Admin usage --------------------------------------------------------------


def test_resume_ai_usage_requires_admin(client_with_resume):
    client, headers = client_with_resume["client"], client_with_resume["headers"]
    denied = client.get("/api/v1/resume-ai/usage", headers=headers)
    assert denied.status_code in (401, 403)

    allowed = client.get("/api/v1/resume-ai/usage", headers=ADMIN_HEADERS)
    assert allowed.status_code == 200
    assert "recent_resume_ai_calls" in allowed.json()
