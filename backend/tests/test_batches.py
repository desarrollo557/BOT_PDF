from __future__ import annotations

import pytest

pytest.importorskip("httpx")

from resolutions.api.jobs import JobProgress, JobRegistry  # noqa: E402

PDF = b"%PDF-1.4 not really a pdf"


class TestBatchEndpoints:
    def test_a_batch_can_be_opened_and_read_back(self, client):
        created = client.post("/api/batches", json={"name": "Expedientes marzo"})
        assert created.status_code == 201
        batch_id = created.json()["id"]

        summary = client.get(f"/api/batches/{batch_id}").json()
        assert summary["name"] == "Expedientes marzo"
        assert summary["documents"] == 0

    def test_an_unnamed_batch_still_gets_a_label(self, client):
        assert client.post("/api/batches", json={}).json()["name"] == "Lote sin nombre"

    def test_uploading_into_a_missing_batch_is_refused(self, client):
        response = client.post(
            "/api/jobs?batch_id=nope", files={"file": ("a.pdf", PDF, "application/pdf")}
        )
        assert response.status_code == 404

    def test_uploads_land_in_their_batch(self, client):
        batch_id = client.post("/api/batches", json={"name": "Lote"}).json()["id"]
        for index in range(3):
            response = client.post(
                f"/api/jobs?batch_id={batch_id}",
                files={"file": (f"doc-{index}.pdf", PDF, "application/pdf")},
            )
            assert response.status_code == 202
            assert response.json()["batch_id"] == batch_id

        summary = client.get(f"/api/batches/{batch_id}").json()
        assert summary["documents"] == 3
        assert len(summary["job_ids"]) == 3

    def test_a_large_batch_is_accepted_in_one_go(self, client):
        # The point of the feature: 50+ documents queued together.
        batch_id = client.post("/api/batches", json={"name": "Lote grande"}).json()["id"]
        for index in range(60):
            assert (
                client.post(
                    f"/api/jobs?batch_id={batch_id}",
                    files={"file": (f"doc-{index}.pdf", PDF, "application/pdf")},
                ).status_code
                == 202
            )
        assert client.get(f"/api/batches/{batch_id}").json()["documents"] == 60

    def test_batches_are_listed_newest_first(self, client):
        client.post("/api/batches", json={"name": "Primero"})
        client.post("/api/batches", json={"name": "Segundo"})
        names = [batch["name"] for batch in client.get("/api/batches").json()["batches"]]
        assert names == ["Segundo", "Primero"]

    def test_errors_speak_the_operator_s_language(self, client):
        assert client.get("/api/batches/nope").json()["detail"] == "El lote no existe"
        response = client.post("/api/jobs", files={"file": ("a.txt", b"x", "text/plain")})
        assert response.json()["detail"] == "Solo se aceptan archivos PDF"


class TestProgressFolding:
    def build(self):
        registry = JobRegistry()
        from pathlib import Path

        job = registry.create("doc.pdf", Path("doc.pdf"))
        return registry, job

    def test_opening_a_document_sizes_the_ribbon(self):
        registry, job = self.build()
        registry.apply_progress({"job_id": job.id, "stage": "opened", "page_count": 5})
        assert job.progress.as_dict()["ribbon"] == "....."
        assert job.progress.stage == "analysing"

    def test_each_page_paints_its_rung(self):
        registry, job = self.build()
        registry.apply_progress({"job_id": job.id, "stage": "opened", "page_count": 4})
        for page, provenance in [(1, "text_layer"), (2, "ocr_region"), (3, "ocr_full_page")]:
            registry.apply_progress(
                {"job_id": job.id, "stage": "page", "page_number": page, "provenance": provenance}
            )
        assert job.progress.as_dict()["ribbon"] == "thf."
        assert job.progress.pages_done == 3

    def test_a_failed_page_is_marked_and_counted(self):
        registry, job = self.build()
        registry.apply_progress({"job_id": job.id, "stage": "opened", "page_count": 2})
        registry.apply_progress(
            {"job_id": job.id, "stage": "page", "page_number": 1, "provenance": "none", "failed": True}
        )
        assert job.progress.as_dict()["ribbon"] == "x."
        assert job.progress.failed_pages == 1

    def test_the_vision_rung_repaints_a_page_without_counting_it_twice(self):
        registry, job = self.build()
        registry.apply_progress({"job_id": job.id, "stage": "opened", "page_count": 2})
        registry.apply_progress(
            {"job_id": job.id, "stage": "page", "page_number": 1, "provenance": "ocr_full_page"}
        )
        registry.apply_progress(
            {"job_id": job.id, "stage": "page", "page_number": 1, "provenance": "vision_model"}
        )
        progress = job.progress.as_dict()
        assert progress["ribbon"] == "v."
        assert job.progress.pages_done == 1
        assert progress["by_provenance"] == {"ocr_full_page": 0, "vision_model": 1}

    def test_progress_is_coalesced_not_published_per_page(self):
        registry, job = self.build()
        registry.apply_progress({"job_id": job.id, "stage": "opened", "page_count": 400})
        for page in range(1, 401):
            registry.apply_progress(
                {"job_id": job.id, "stage": "page", "page_number": page, "provenance": "text_layer"}
            )
        # 401 events folded, one job to publish on the next tick.
        assert len(registry.flush()) == 1
        assert registry.flush() == []

    def test_events_for_unknown_jobs_are_ignored(self):
        registry, _ = self.build()
        registry.apply_progress({"job_id": "ghost", "stage": "opened", "page_count": 3})
        assert registry.flush() == []

    def test_percent_and_rate_are_reported(self):
        progress = JobProgress()
        progress.apply({"stage": "opened", "page_count": 10})
        for page in range(1, 6):
            progress.apply({"stage": "page", "page_number": page, "provenance": "text_layer"})
        assert progress.as_dict()["percent"] == 50.0
        assert progress.as_dict()["pages_per_second"] >= 0.0
