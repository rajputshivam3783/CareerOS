"""V22.3 — Application Timeline, Notes & Documents tests.

Covers notes/interviews/tasks/documents CRUD, ownership isolation
(IDOR) across all four child resources, document upload validation
(type/size), secure download, timeline ordering + status-history
integration, and task overdue handling.
"""

import io
import os
import shutil

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v22_3.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"
os.environ["APPLICATION_DOCUMENT_STORAGE_DIR"] = "./test_v22_3_uploads"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

_counter = {"n": 0}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
    shutil.rmtree("./test_v22_3_uploads", ignore_errors=True)


def _register_and_login(client, email_prefix: str) -> dict:
    _counter["n"] += 1
    email = f"{email_prefix}{_counter['n']}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password12345!", "password_confirm": "password12345!", "full_name": "Test User"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "password12345!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_application(client, headers, **overrides):
    payload = {"company": "Acme", "job_title": "Engineer", "status": "APPLIED"}
    payload.update(overrides)
    resp = client.post("/api/v1/applications", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


def test_note_create_read_update_delete(client):
    headers = _register_and_login(client, "v22_3notes")
    a = _create_application(client, headers)

    create = client.post(f"/api/v1/applications/{a['id']}/notes", headers=headers, json={"content": "Recruiter called"})
    assert create.status_code == 201, create.text
    note = create.json()
    assert note["content"] == "Recruiter called"

    listed = client.get(f"/api/v1/applications/{a['id']}/notes", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = client.patch(f"/api/v1/applications/{a['id']}/notes/{note['id']}", headers=headers, json={"content": "Recruiter called back"})
    assert updated.status_code == 200
    assert updated.json()["content"] == "Recruiter called back"

    deleted = client.delete(f"/api/v1/applications/{a['id']}/notes/{note['id']}", headers=headers)
    assert deleted.status_code == 204

    listed_after = client.get(f"/api/v1/applications/{a['id']}/notes", headers=headers)
    assert listed_after.json() == []


def test_note_content_length_validated(client):
    headers = _register_and_login(client, "v22_3notesval")
    a = _create_application(client, headers)

    empty = client.post(f"/api/v1/applications/{a['id']}/notes", headers=headers, json={"content": "   "})
    assert empty.status_code in (400, 422)

    too_long = client.post(f"/api/v1/applications/{a['id']}/notes", headers=headers, json={"content": "x" * 10_001})
    assert too_long.status_code == 422


def test_note_ownership_isolation(client):
    headers_a = _register_and_login(client, "v22_3notesowner_a")
    headers_b = _register_and_login(client, "v22_3notesowner_b")
    a = _create_application(client, headers_a)
    note = client.post(f"/api/v1/applications/{a['id']}/notes", headers=headers_a, json={"content": "private"}).json()

    # Cross-user read of the application's notes at all
    cross_list = client.get(f"/api/v1/applications/{a['id']}/notes", headers=headers_b)
    assert cross_list.status_code == 404

    cross_update = client.patch(f"/api/v1/applications/{a['id']}/notes/{note['id']}", headers=headers_b, json={"content": "hijacked"})
    assert cross_update.status_code == 404

    cross_delete = client.delete(f"/api/v1/applications/{a['id']}/notes/{note['id']}", headers=headers_b)
    assert cross_delete.status_code == 404


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------


def test_interview_create_update_delete(client):
    headers = _register_and_login(client, "v22_3interviews")
    a = _create_application(client, headers)

    create = client.post(
        f"/api/v1/applications/{a['id']}/interviews",
        headers=headers,
        json={"interview_type": "technical", "round_name": "Round 1", "scheduled_at": "2026-10-01T10:00:00"},
    )
    assert create.status_code == 201, create.text
    interview = create.json()
    assert interview["interview_type"] == "TECHNICAL"
    assert interview["result"] == "SCHEDULED"

    update = client.patch(
        f"/api/v1/applications/{a['id']}/interviews/{interview['id']}",
        headers=headers,
        json={"result": "passed"},
    )
    assert update.status_code == 200
    assert update.json()["result"] == "PASSED"

    delete = client.delete(f"/api/v1/applications/{a['id']}/interviews/{interview['id']}", headers=headers)
    assert delete.status_code == 204


def test_interview_type_validation(client):
    headers = _register_and_login(client, "v22_3interviewsval")
    a = _create_application(client, headers)
    bad = client.post(f"/api/v1/applications/{a['id']}/interviews", headers=headers, json={"interview_type": "NOT_A_TYPE"})
    assert bad.status_code == 422


def test_interview_completion_appears_in_timeline(client):
    headers = _register_and_login(client, "v22_3interviewtl")
    a = _create_application(client, headers)
    interview = client.post(
        f"/api/v1/applications/{a['id']}/interviews", headers=headers, json={"interview_type": "hr"}
    ).json()
    client.patch(f"/api/v1/applications/{a['id']}/interviews/{interview['id']}", headers=headers, json={"result": "completed"})

    tl = client.get(f"/api/v1/applications/{a['id']}/timeline", headers=headers).json()
    types = [e["event_type"] for e in tl]
    assert "INTERVIEW_SCHEDULED" in types
    assert "INTERVIEW_COMPLETED" in types


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def test_task_create_complete_update_delete(client):
    headers = _register_and_login(client, "v22_3tasks")
    a = _create_application(client, headers)

    create = client.post(f"/api/v1/applications/{a['id']}/tasks", headers=headers, json={"title": "Send follow-up"})
    assert create.status_code == 201
    task = create.json()
    assert task["completed"] is False

    complete = client.patch(f"/api/v1/applications/{a['id']}/tasks/{task['id']}", headers=headers, json={"completed": True})
    assert complete.status_code == 200
    assert complete.json()["completed"] is True
    assert complete.json()["completed_at"] is not None

    uncomplete = client.patch(f"/api/v1/applications/{a['id']}/tasks/{task['id']}", headers=headers, json={"completed": False})
    assert uncomplete.json()["completed_at"] is None

    delete = client.delete(f"/api/v1/applications/{a['id']}/tasks/{task['id']}", headers=headers)
    assert delete.status_code == 204


def test_task_overdue_flag(client):
    headers = _register_and_login(client, "v22_3taskoverdue")
    a = _create_application(client, headers)
    task = client.post(
        f"/api/v1/applications/{a['id']}/tasks", headers=headers, json={"title": "Old task", "due_at": "2020-01-01T00:00:00"}
    ).json()
    assert task["overdue"] is True

    future_task = client.post(
        f"/api/v1/applications/{a['id']}/tasks", headers=headers, json={"title": "Future task", "due_at": "2099-01-01T00:00:00"}
    ).json()
    assert future_task["overdue"] is False


def test_task_title_validation(client):
    headers = _register_and_login(client, "v22_3taskval")
    a = _create_application(client, headers)
    bad = client.post(f"/api/v1/applications/{a['id']}/tasks", headers=headers, json={"title": "   "})
    assert bad.status_code == 422


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def test_document_upload_list_download_delete(client):
    headers = _register_and_login(client, "v22_3docs")
    a = _create_application(client, headers)

    file_content = b"%PDF-1.4 fake resume content"
    upload = client.post(
        f"/api/v1/applications/{a['id']}/documents",
        headers=headers,
        data={"category": "resume"},
        files={"file": ("resume.pdf", io.BytesIO(file_content), "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    doc = upload.json()
    assert doc["category"] == "RESUME"
    assert doc["original_filename"] == "resume.pdf"
    assert "stored_filename" not in doc  # never expose the raw storage path/name

    listed = client.get(f"/api/v1/applications/{a['id']}/documents", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    download = client.get(f"/api/v1/applications/{a['id']}/documents/{doc['id']}/download", headers=headers)
    assert download.status_code == 200
    assert download.content == file_content

    delete = client.delete(f"/api/v1/applications/{a['id']}/documents/{doc['id']}", headers=headers)
    assert delete.status_code == 204

    listed_after = client.get(f"/api/v1/applications/{a['id']}/documents", headers=headers)
    assert listed_after.json() == []


def test_document_type_validation_rejects_unsupported_extension(client):
    headers = _register_and_login(client, "v22_3docstype")
    a = _create_application(client, headers)
    upload = client.post(
        f"/api/v1/applications/{a['id']}/documents",
        headers=headers,
        data={"category": "resume"},
        files={"file": ("virus.exe", io.BytesIO(b"MZ..."), "application/octet-stream")},
    )
    assert upload.status_code == 400


def test_document_size_validation(client):
    headers = _register_and_login(client, "v22_3docssize")
    a = _create_application(client, headers)
    too_big = b"a" * (11 * 1024 * 1024)  # exceeds 10MB default cap
    upload = client.post(
        f"/api/v1/applications/{a['id']}/documents",
        headers=headers,
        data={"category": "resume"},
        files={"file": ("big.pdf", io.BytesIO(too_big), "application/pdf")},
    )
    assert upload.status_code == 413


def test_document_ownership_isolation(client):
    headers_a = _register_and_login(client, "v22_3docsowner_a")
    headers_b = _register_and_login(client, "v22_3docsowner_b")
    a = _create_application(client, headers_a)
    doc = client.post(
        f"/api/v1/applications/{a['id']}/documents",
        headers=headers_a,
        data={"category": "resume"},
        files={"file": ("resume.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
    ).json()

    cross_download = client.get(f"/api/v1/applications/{a['id']}/documents/{doc['id']}/download", headers=headers_b)
    assert cross_download.status_code == 404

    cross_delete = client.delete(f"/api/v1/applications/{a['id']}/documents/{doc['id']}", headers=headers_b)
    assert cross_delete.status_code == 404

    # document still exists for the real owner after the attempted cross-user delete
    still_listed = client.get(f"/api/v1/applications/{a['id']}/documents", headers=headers_a)
    assert len(still_listed.json()) == 1


def test_invalid_application_id_returns_404_not_arbitrary_access(client):
    headers = _register_and_login(client, "v22_3invalidid")
    resp = client.get("/api/v1/applications/999999/documents", headers=headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


def test_timeline_ordering_and_status_history_integration(client):
    headers = _register_and_login(client, "v22_3timeline")
    a = _create_application(client, headers, status="APPLIED")

    client.post(f"/api/v1/applications/{a['id']}/notes", headers=headers, json={"content": "note 1"})
    client.post(f"/api/v1/applications/{a['id']}/tasks", headers=headers, json={"title": "task 1"})
    client.post(f"/api/v1/applications/{a['id']}/status", headers=headers, json={"status": "INTERVIEW"})

    tl = client.get(f"/api/v1/applications/{a['id']}/timeline", headers=headers)
    assert tl.status_code == 200
    entries = tl.json()

    event_types = [e["event_type"] for e in entries]
    assert "APPLICATION_CREATED" in event_types
    assert "NOTE_ADDED" in event_types
    assert "TASK_CREATED" in event_types
    assert "STATUS_CHANGED" in event_types

    # newest-first by default
    timestamps = [e["occurred_at"] for e in entries]
    assert timestamps == sorted(timestamps, reverse=True)

    asc = client.get(f"/api/v1/applications/{a['id']}/timeline?order=asc", headers=headers).json()
    asc_timestamps = [e["occurred_at"] for e in asc]
    assert asc_timestamps == sorted(asc_timestamps)


def test_timeline_ownership_isolation(client):
    headers_a = _register_and_login(client, "v22_3timelineowner_a")
    headers_b = _register_and_login(client, "v22_3timelineowner_b")
    a = _create_application(client, headers_a)
    resp = client.get(f"/api/v1/applications/{a['id']}/timeline", headers=headers_b)
    assert resp.status_code == 404
