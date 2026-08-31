"""Who was at the console when a document was processed.

There is no password behind the name, so this is attribution and never
authorisation. That distinction is the whole design: the name is recorded so
the archive can answer "who ran this", and nothing anywhere is allowed to grant
or withhold anything because of it.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import pytest

pytest.importorskip("httpx")

PDF = b"%PDF-1.4 not really a pdf"


def report(document="expediente.pdf"):
    return {
        "document": document,
        "inventory": {
            "source_document": document,
            "items": [
                {
                    "file_name": "00086__acta.pdf",
                    "code": "00086",
                    "title": "Acta",
                    "page_count": 1,
                    "first_page": 1,
                    "last_page": 1,
                    "page_numbers": [1],
                }
            ],
        },
    }


def sent(name: str) -> str:
    """A name as the browser puts it on the wire."""
    return quote(name)


class TestRecordingTheOperator:
    def test_an_upload_carries_the_name_from_the_header(self, client):
        response = client.post(
            "/api/jobs",
            files={"file": ("a.pdf", PDF, "application/pdf")},
            headers={"X-Operator": sent("Ana Gomez")},
        )
        job_id = response.json()["id"]
        assert client.get(f"/api/jobs/{job_id}").json()["operator"] == "Ana Gomez"

    def test_an_accented_name_survives_the_trip(self, client):
        # HTTP header values are ASCII. Half the names in a Spanish-speaking
        # building carry an accent, so this is the common case, not the edge.
        response = client.post(
            "/api/jobs",
            files={"file": ("a.pdf", PDF, "application/pdf")},
            headers={"X-Operator": sent("María Martínez Muñoz")},
        )
        job_id = response.json()["id"]
        assert client.get(f"/api/jobs/{job_id}").json()["operator"] == "María Martínez Muñoz"

    def test_an_upload_without_a_name_is_still_accepted(self, client):
        # The name is a label, not a gate. Nothing is refused for its absence.
        response = client.post("/api/jobs", files={"file": ("a.pdf", PDF, "application/pdf")})
        assert response.status_code == 202
        assert client.get(f"/api/jobs/{response.json()['id']}").json()["operator"] is None

    def test_a_blank_name_is_read_as_no_name(self, client):
        response = client.post(
            "/api/jobs",
            files={"file": ("a.pdf", PDF, "application/pdf")},
            headers={"X-Operator": "   "},
        )
        assert client.get(f"/api/jobs/{response.json()['id']}").json()["operator"] is None

    def test_an_absurd_name_is_bounded_rather_than_refused(self, client):
        from resolutions.api.main import MAX_OPERATOR

        response = client.post(
            "/api/jobs",
            files={"file": ("a.pdf", PDF, "application/pdf")},
            headers={"X-Operator": "x" * 500},
        )
        name = client.get(f"/api/jobs/{response.json()['id']}").json()["operator"]
        assert len(name) == MAX_OPERATOR

    def test_a_folder_run_carries_it_too(self, client, tmp_path):
        source = tmp_path / "entrada"
        source.mkdir()
        response = client.post(
            "/api/folder-runs",
            json={"source": str(source), "destination": str(tmp_path / "salida")},
            headers={"X-Operator": sent("Turno noche")},
        )
        assert response.json()["operator"] == "Turno noche"


class TestTheArchiveRemembers:
    def test_the_ledger_row_carries_the_operator(self, client):
        from resolutions.api import main

        job = main.registry.create("expediente.pdf", Path("expediente.pdf"), operator="Ana")
        main.registry.mark_done(job, report())
        main.ledger.record(job.id, report(), operator=job.operator)

        assert client.get("/api/inventory").json()["rows"][0]["operator"] == "Ana"

    def test_the_document_history_carries_it(self, client):
        from resolutions.api import main

        main.ledger.record("job-1", report(), operator="Ana")
        assert client.get("/api/documents").json()["documents"][0]["operator"] == "Ana"

    def test_it_survives_clearing_the_screen(self, client):
        from resolutions.api import main

        job = main.registry.create("expediente.pdf", Path("expediente.pdf"), operator="Ana")
        main.registry.mark_done(job, report())
        main.ledger.record(job.id, report(), operator=job.operator)

        client.request("DELETE", "/api/jobs")
        assert client.get("/api/documents").json()["documents"][0]["operator"] == "Ana"

    def test_the_archive_can_be_searched_by_operator(self, client):
        from resolutions.api import main

        main.ledger.record("job-1", report(document="marzo.pdf"), operator="Ana")
        main.ledger.record("job-2", report(document="abril.pdf"), operator="Beto")
        assert client.get("/api/inventory?q=ana").json()["total"] == 1

    def test_work_done_without_a_name_is_still_recorded(self, client):
        from resolutions.api import main

        main.ledger.record("job-1", report())
        rows = client.get("/api/inventory").json()["rows"]
        assert len(rows) == 1
        assert rows[0]["operator"] is None


class TestItGrantsNothing:
    """The one property that must never quietly change."""

    def test_reading_needs_no_name(self, client):
        for url in ("/api/jobs", "/api/inventory", "/api/documents", "/api/folder-runs"):
            assert client.get(url).status_code == 200

    def test_deleting_needs_no_name(self, client):
        # Stated as a test so that if anyone ever wires the header to a
        # permission, this fails and the decision has to be made deliberately.
        assert client.request("DELETE", "/api/jobs").status_code == 200

    def test_an_unknown_name_is_as_good_as_any_other(self, client):
        response = client.post(
            "/api/jobs",
            files={"file": ("a.pdf", PDF, "application/pdf")},
            headers={"X-Operator": sent("quien sea")},
        )
        assert response.status_code == 202
