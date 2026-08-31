"""Every mutation the front end can make, end to end through the API.

The point of these is coverage of the surface rather than of one behaviour: if
a screen offers a button, the endpoint behind it is exercised here, including
what it does when the thing it points at is gone.

The rule the corrections have to keep is that a resolution lives in three
places at once -- the file on disk, the report on screen and the inventory row
-- and an edit that lands in only one of them is worse than no edit at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("httpx")


def a_processed_document(name: str = "expediente.pdf", code: str = "00086"):
    """A finished job with one generated resolution, on disk and in the ledger."""
    from resolutions.api import main

    job = main.registry.create(name, Path(name))
    file_name = f"{code}__acta.pdf"
    report = {
        "document": name,
        "page_count": 3,
        "groups": [{"code": code, "title": "Acta", "pages": [1, 2, 3], "size": 3}],
        "review_queue": [],
        "outputs": [file_name],
        "inventory": {
            "source_document": name,
            "source_pages": 3,
            "items": [
                {
                    "file_name": file_name,
                    "code": code,
                    "title": "Acta",
                    "page_count": 3,
                    "first_page": 1,
                    "last_page": 3,
                    "page_numbers": [1, 2, 3],
                }
            ],
        },
    }
    main.registry.mark_done(job, report)
    main.ledger.record(job.id, report)

    directory = main.settings.output_dir / job.id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / file_name).write_bytes(b"%PDF-1.4 out")
    return job, file_name, directory


class TestReadingEverythingTheFrontReads:
    def test_every_read_endpoint_answers_on_an_empty_service(self, client):
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/jobs").json() == {"jobs": []}
        assert client.get("/api/batches").json() == {"batches": []}
        assert client.get("/api/inventory").json()["total"] == 0
        assert client.get("/api/inventory.csv").status_code == 200
        assert client.get("/api/folder-runs").json() == {"runs": []}
        assert client.get("/api/cache").json()["idle"] is True

    def test_a_processed_document_is_readable_through_every_route(self, client):
        job, file_name, _ = a_processed_document()

        assert client.get(f"/api/jobs/{job.id}").json()["filename"] == "expediente.pdf"
        assert client.get(f"/api/jobs/{job.id}/outputs/{file_name}").status_code == 200
        assert client.get("/api/inventory").json()["total"] == 1


class TestRenamingAResolution:
    def test_the_number_can_be_corrected(self, client):
        # OCR gets a digit wrong often enough that this cannot mean re-running
        # the whole document.
        job, file_name, directory = a_processed_document(code="0OO86")

        response = client.patch(
            f"/api/jobs/{job.id}/outputs/{file_name}", json={"code": "00086"}
        )

        assert response.status_code == 200
        assert response.json()["code"] == "00086"
        assert not (directory / file_name).exists()
        assert (directory / response.json()["file_name"]).is_file()

    def test_the_title_can_be_corrected(self, client):
        job, file_name, _ = a_processed_document()
        response = client.patch(
            f"/api/jobs/{job.id}/outputs/{file_name}",
            json={"title": "Por la cual se adopta el manual"},
        )
        assert response.json()["title"] == "Por la cual se adopta el manual"
        assert "manual" in response.json()["file_name"]

    def test_the_inventory_row_moves_with_the_file(self, client):
        job, file_name, _ = a_processed_document(code="0OO86")
        client.patch(f"/api/jobs/{job.id}/outputs/{file_name}", json={"code": "00086"})

        row = client.get("/api/inventory").json()["rows"][0]
        assert row["code"] == "00086"
        assert row["file_name"].startswith("00086")

    def test_the_report_on_screen_moves_with_the_file(self, client):
        job, file_name, _ = a_processed_document(code="0OO86")
        client.patch(f"/api/jobs/{job.id}/outputs/{file_name}", json={"code": "00086"})

        report = client.get(f"/api/jobs/{job.id}").json()["report"]
        assert [group["code"] for group in report["groups"]] == ["00086"]
        assert report["outputs"][0].startswith("00086")

    def test_the_renamed_file_is_downloadable_under_its_new_name(self, client):
        job, file_name, _ = a_processed_document(code="0OO86")
        renamed = client.patch(
            f"/api/jobs/{job.id}/outputs/{file_name}", json={"code": "00086"}
        ).json()["file_name"]

        assert client.get(f"/api/jobs/{job.id}/outputs/{renamed}").status_code == 200
        assert client.get(f"/api/jobs/{job.id}/outputs/{file_name}").status_code == 404

    def test_a_number_with_no_digits_is_refused(self, client):
        job, file_name, _ = a_processed_document()
        response = client.patch(
            f"/api/jobs/{job.id}/outputs/{file_name}", json={"code": "SIN NUMERO"}
        )
        assert response.status_code == 422

    def test_an_empty_number_is_refused(self, client):
        job, file_name, _ = a_processed_document()
        assert (
            client.patch(f"/api/jobs/{job.id}/outputs/{file_name}", json={"code": " "}).status_code
            == 422
        )

    def test_renaming_onto_an_existing_file_is_refused(self, client):
        job, file_name, directory = a_processed_document()
        (directory / "00072__otra.pdf").write_bytes(b"%PDF-1.4")

        response = client.patch(
            f"/api/jobs/{job.id}/outputs/{file_name}",
            json={"code": "00072", "title": "otra"},
        )
        assert response.status_code == 409
        assert (directory / file_name).is_file()

    def test_renaming_a_file_that_does_not_exist_is_not_found(self, client):
        job, _, _ = a_processed_document()
        response = client.patch(f"/api/jobs/{job.id}/outputs/ghost.pdf", json={"code": "1"})
        assert response.status_code == 404


class TestDeletingAResolution:
    def test_the_file_and_its_inventory_row_go_together(self, client):
        job, file_name, directory = a_processed_document()

        response = client.request("DELETE", f"/api/jobs/{job.id}/outputs/{file_name}")

        assert response.json()["was_recorded"] is True
        assert not (directory / file_name).exists()
        assert client.get("/api/inventory").json()["total"] == 0

    def test_the_report_stops_listing_it(self, client):
        job, file_name, _ = a_processed_document()
        client.request("DELETE", f"/api/jobs/{job.id}/outputs/{file_name}")

        report = client.get(f"/api/jobs/{job.id}").json()["report"]
        assert report["groups"] == []
        assert report["outputs"] == []
        assert report["inventory"]["generated_files"] == 0

    def test_the_other_resolutions_of_the_document_are_untouched(self, client):
        job, file_name, directory = a_processed_document()
        (directory / "00072__otra.pdf").write_bytes(b"%PDF-1.4")

        client.request("DELETE", f"/api/jobs/{job.id}/outputs/{file_name}")

        assert (directory / "00072__otra.pdf").is_file()

    def test_deleting_one_that_is_not_there_is_not_found(self, client):
        job, _, _ = a_processed_document()
        assert (
            client.request("DELETE", f"/api/jobs/{job.id}/outputs/ghost.pdf").status_code == 404
        )

    def test_a_traversal_attempt_cannot_reach_outside_the_job(self, client):
        job, _, _ = a_processed_document()
        response = client.request("DELETE", f"/api/jobs/{job.id}/outputs/..%2F..%2Fsettings.py")
        assert response.status_code == 404


class TestRenamingADocument:
    def test_a_document_can_be_renamed_on_screen(self, client):
        job, _, _ = a_processed_document()
        response = client.patch(f"/api/jobs/{job.id}", json={"filename": "Marzo 2024.pdf"})
        assert response.json()["filename"] == "Marzo 2024.pdf"
        assert client.get(f"/api/jobs/{job.id}").json()["filename"] == "Marzo 2024.pdf"

    def test_an_empty_name_is_refused(self, client):
        job, _, _ = a_processed_document()
        assert client.patch(f"/api/jobs/{job.id}", json={"filename": "  "}).status_code == 422

    def test_renaming_an_unknown_document_is_not_found(self, client):
        assert client.patch("/api/jobs/ghost", json={"filename": "x.pdf"}).status_code == 404


class TestBatches:
    def test_a_batch_can_be_renamed(self, client):
        batch_id = client.post("/api/batches", json={"name": "Lote"}).json()["id"]
        response = client.patch(f"/api/batches/{batch_id}", json={"name": "Expedientes marzo"})
        assert response.json()["name"] == "Expedientes marzo"

    def test_an_empty_batch_name_is_refused(self, client):
        batch_id = client.post("/api/batches", json={"name": "Lote"}).json()["id"]
        assert client.patch(f"/api/batches/{batch_id}", json={"name": ""}).status_code == 422

    def test_a_batch_can_be_cleared_off_the_screen(self, client):
        from resolutions.api import main

        batch_id = client.post("/api/batches", json={"name": "Lote"}).json()["id"]
        for name in ("a.pdf", "b.pdf"):
            job = main.registry.create(name, Path(name), batch_id=batch_id)
            main.registry.mark_done(job, {"groups": [], "review_queue": []})

        response = client.request("DELETE", f"/api/batches/{batch_id}")

        assert response.json()["removed"] == 2
        assert client.get("/api/jobs").json() == {"jobs": []}

    def test_clearing_a_batch_keeps_its_files_unless_purged(self, client):
        from resolutions.api import main

        batch_id = client.post("/api/batches", json={"name": "Lote"}).json()["id"]
        job = main.registry.create("a.pdf", Path("a.pdf"), batch_id=batch_id)
        main.registry.mark_done(job, {"groups": [], "review_queue": []})
        directory = main.settings.output_dir / job.id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "00086__acta.pdf").write_bytes(b"%PDF")

        client.request("DELETE", f"/api/batches/{batch_id}")
        assert directory.exists()

    def test_purging_a_batch_takes_its_files(self, client):
        from resolutions.api import main

        batch_id = client.post("/api/batches", json={"name": "Lote"}).json()["id"]
        job = main.registry.create("a.pdf", Path("a.pdf"), batch_id=batch_id)
        main.registry.mark_done(job, {"groups": [], "review_queue": []})
        directory = main.settings.output_dir / job.id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "00086__acta.pdf").write_bytes(b"%PDF")

        client.request("DELETE", f"/api/batches/{batch_id}?purge=true")
        assert not directory.exists()

    def test_a_running_document_is_not_cleared_with_its_batch(self, client):
        from resolutions.api import main

        batch_id = client.post("/api/batches", json={"name": "Lote"}).json()["id"]
        job = main.registry.create("a.pdf", Path("a.pdf"), batch_id=batch_id)
        main.registry.mark_running(job)

        assert client.request("DELETE", f"/api/batches/{batch_id}").json()["removed"] == 0
        assert len(client.get("/api/jobs").json()["jobs"]) == 1

    def test_deleting_an_unknown_batch_is_not_found(self, client):
        assert client.request("DELETE", "/api/batches/ghost").status_code == 404


class TestCorrectionsSurviveAScreenClear:
    def test_the_inventory_still_carries_the_correction(self, client):
        # The ledger outlives the registry, so a fix made before clearing has to
        # still be there afterwards.
        job, file_name, _ = a_processed_document(code="0OO86")
        renamed = client.patch(
            f"/api/jobs/{job.id}/outputs/{file_name}", json={"code": "00086"}
        ).json()["file_name"]

        client.request("DELETE", "/api/jobs")

        rows = client.get("/api/inventory").json()["rows"]
        assert rows[0]["code"] == "00086"
        assert client.get(f"/api/jobs/{job.id}/outputs/{renamed}").status_code == 200

    def test_a_correction_after_the_clear_still_reaches_the_ledger(self, client):
        job, file_name, _ = a_processed_document(code="0OO86")
        client.request("DELETE", "/api/jobs")

        response = client.patch(
            f"/api/jobs/{job.id}/outputs/{file_name}", json={"code": "00086"}
        )

        assert response.status_code == 200
        assert client.get("/api/inventory").json()["rows"][0]["code"] == "00086"


def a_document_with_two_resolutions(name: str = "expediente.pdf"):
    """A finished job whose two resolutions are both on disk and in the ledger."""
    from resolutions.api import main

    job = main.registry.create(name, Path(name))
    files = ["00086__acta.pdf", "00087__resuelve.pdf"]
    report = {
        "document": name,
        "page_count": 4,
        "groups": [
            {"code": "00086", "title": "Acta", "pages": [1, 2], "size": 2},
            {"code": "00087", "title": "Resuelve", "pages": [3, 4], "size": 2},
        ],
        "review_queue": [],
        "outputs": files,
        "inventory": {
            "source_document": name,
            "source_pages": 4,
            "items": [
                {
                    "file_name": files[0],
                    "code": "00086",
                    "title": "Acta",
                    "page_count": 2,
                    "first_page": 1,
                    "last_page": 2,
                    "page_numbers": [1, 2],
                },
                {
                    "file_name": files[1],
                    "code": "00087",
                    "title": "Resuelve",
                    "page_count": 2,
                    "first_page": 3,
                    "last_page": 4,
                    "page_numbers": [3, 4],
                },
            ],
        },
    }
    main.registry.mark_done(job, report)
    main.ledger.record(job.id, report)

    directory = main.settings.output_dir / job.id
    directory.mkdir(parents=True, exist_ok=True)
    for file_name in files:
        (directory / file_name).write_bytes(b"%PDF-1.4 out")
    return job, files, directory


class TestRenamingAProcessedDocument:
    """`PATCH /api/documents/{id}`: the name the archive shows, corrected.

    Distinct from renaming the job, which only reaches the card while it is
    still on screen. This one has to reach the record, because the archive is
    read from the ledger long after the screen was cleared.
    """

    def test_every_row_of_the_document_takes_the_new_name(self, client):
        job, _, _ = a_document_with_two_resolutions()

        response = client.patch(
            f"/api/documents/{job.id}", json={"source_document": "Marzo 2024.pdf"}
        )

        assert response.status_code == 200
        assert response.json()["rows"] == 2
        rows = client.get("/api/inventory").json()["rows"]
        assert {row["source_document"] for row in rows} == {"Marzo 2024.pdf"}

    def test_the_archive_lists_it_once_under_the_new_name(self, client):
        job, _, _ = a_document_with_two_resolutions()
        client.patch(f"/api/documents/{job.id}", json={"source_document": "Marzo 2024.pdf"})

        documents = client.get("/api/documents").json()["documents"]

        assert [document["source_document"] for document in documents] == ["Marzo 2024.pdf"]

    def test_the_card_on_screen_takes_it_too(self, client):
        job, _, _ = a_document_with_two_resolutions()
        client.patch(f"/api/documents/{job.id}", json={"source_document": "Marzo 2024.pdf"})
        assert client.get(f"/api/jobs/{job.id}").json()["filename"] == "Marzo 2024.pdf"

    def test_a_document_only_in_the_ledger_can_still_be_renamed(self, client):
        job, _, _ = a_document_with_two_resolutions()
        client.request("DELETE", "/api/jobs")

        response = client.patch(
            f"/api/documents/{job.id}", json={"source_document": "Marzo 2024.pdf"}
        )

        assert response.status_code == 200
        assert client.get("/api/documents").json()["documents"][0][
            "source_document"
        ] == "Marzo 2024.pdf"

    def test_an_empty_name_is_refused(self, client):
        job, _, _ = a_document_with_two_resolutions()
        assert (
            client.patch(f"/api/documents/{job.id}", json={"source_document": "  "}).status_code
            == 422
        )

    def test_a_name_that_is_a_path_is_refused(self, client):
        # The name is drawn on a screen and written to the ledger; it is not a
        # place on disk, and a separator in it would say otherwise.
        job, _, _ = a_document_with_two_resolutions()
        for attempt in ("../otro.pdf", "carpeta/otro.pdf"):
            response = client.patch(
                f"/api/documents/{job.id}", json={"source_document": attempt}
            )
            assert response.status_code == 422, attempt

    def test_renaming_an_unknown_document_is_not_found(self, client):
        assert (
            client.patch("/api/documents/ghost", json={"source_document": "x.pdf"}).status_code
            == 404
        )


class TestErasingAProcessedDocument:
    """`DELETE /api/documents/{id}`: the one deletion that leaves nothing.

    Clearing the screen forgets a job and keeps the work. This discards the
    work: the generated PDFs, the inventory rows and the card, together, so
    nothing is left pointing at something that is gone.
    """

    def test_the_files_the_rows_and_the_card_all_go(self, client):
        job, files, directory = a_document_with_two_resolutions()

        response = client.request("DELETE", f"/api/documents/{job.id}")

        assert response.status_code == 200
        assert response.json()["rows"] == 2
        assert not directory.exists()
        assert client.get("/api/inventory").json()["rows"] == []
        assert client.get("/api/documents").json()["documents"] == []
        assert client.get(f"/api/jobs/{job.id}").status_code == 404

    def test_the_other_documents_are_untouched(self, client):
        first, _, first_directory = a_document_with_two_resolutions("enero.pdf")
        a_document_with_two_resolutions("febrero.pdf")

        client.request("DELETE", f"/api/documents/{first.id}")

        assert not first_directory.exists()
        documents = client.get("/api/documents").json()["documents"]
        assert [document["source_document"] for document in documents] == ["febrero.pdf"]

    def test_a_document_only_in_the_ledger_can_still_be_erased(self, client):
        job, _, directory = a_document_with_two_resolutions()
        client.request("DELETE", "/api/jobs")

        response = client.request("DELETE", f"/api/documents/{job.id}")

        assert response.status_code == 200
        assert response.json()["from_screen"] is False
        assert not directory.exists()
        assert client.get("/api/inventory").json()["rows"] == []

    def test_a_document_still_being_processed_is_refused(self, client):
        from resolutions.api import main

        job = main.registry.create("a.pdf", Path("a.pdf"))
        main.registry.mark_running(job)

        assert client.request("DELETE", f"/api/documents/{job.id}").status_code == 409
        assert client.get(f"/api/jobs/{job.id}").status_code == 200

    def test_erasing_one_that_is_not_there_is_not_found(self, client):
        assert client.request("DELETE", "/api/documents/ghost").status_code == 404

    def test_the_swept_scratch_no_longer_counts_it_as_referenced(self, client):
        # The janitor keeps output whose job is still in the ledger. Once the
        # document is erased, nothing refers to it and nothing is left behind.
        from resolutions.api import main

        job, _, directory = a_document_with_two_resolutions()
        client.request("DELETE", f"/api/documents/{job.id}")

        assert job.id not in main.ledger.job_ids()
        assert not directory.exists()
