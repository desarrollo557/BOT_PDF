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


def test_health_declares_what_this_build_can_do(client):
    """A running service has to be able to say which version of itself it is.

    Python holds the code it imported at start-up, so a service left running
    across an update answers 404 to every new route. Without a version on
    health, that reads as a broken request instead of a stale process.
    """
    payload = client.get("/api/health").json()
    assert payload["api_revision"] >= 4
    assert "folder-runs" in payload["features"]
    assert "inventory" in payload["features"]


def test_every_feature_health_claims_actually_answers(client):
    # The list is a promise to the screen; a promise nothing checks is a lie
    # waiting to happen.
    payload = client.get("/api/health").json()
    probes = {
        "inventory": ("GET", "/api/inventory"),
        "documents": ("GET", "/api/documents"),
        "folder-runs": ("GET", "/api/folder-runs"),
        "cache-sweep": ("GET", "/api/cache"),
    }
    for feature, (method, url) in probes.items():
        assert feature in payload["features"]
        assert client.request(method, url).status_code == 200
