from __future__ import annotations

import pytest

pytest.importorskip("httpx")


def test_health_reports_the_worker_topology(client):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["document_workers"] >= 1
    assert payload["vision"] in {"claude", "disabled"}


def test_non_pdf_uploads_are_refused_before_any_work_starts(client):
    response = client.post("/api/jobs", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 415


def test_an_empty_upload_is_refused(client):
    response = client.post("/api/jobs", files={"file": ("empty.pdf", b"", "application/pdf")})
    assert response.status_code == 400


def test_unknown_jobs_and_outputs_are_not_found(client):
    assert client.get("/api/jobs/does-not-exist").status_code == 404
    assert client.get("/api/jobs/does-not-exist/outputs/a.pdf").status_code == 404


def test_a_traversal_attempt_cannot_escape_the_job_directory(client):
    response = client.get("/api/jobs/abc/outputs/..%2F..%2Fsettings.py")
    assert response.status_code == 404


def test_the_job_list_starts_empty(client):
    assert client.get("/api/jobs").json() == {"jobs": []}
