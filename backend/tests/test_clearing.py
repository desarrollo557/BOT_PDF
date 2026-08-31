"""Clearing the workspace.

Fifty documents pile up on one screen, so the operator needs a way to start
clean. What must never happen is clearing away work that is still running, or
leaving output directories on disk with nothing pointing at them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("httpx")

from resolutions.api.jobs import JobRegistry, JobState  # noqa: E402


def finished(registry: JobRegistry, name: str, state: JobState = JobState.DONE):
    job = registry.create(name, Path(name))
    if state is JobState.DONE:
        registry.mark_done(job, {"groups": [], "review_queue": []})
    else:
        registry.mark_failed(job, "boom")
    return job


class TestRemovingOneJob:
    def test_a_finished_job_is_forgotten(self):
        registry = JobRegistry()
        job = finished(registry, "a.pdf")
        assert registry.remove(job.id) is job
        assert registry.get(job.id) is None

    def test_a_failed_job_can_be_cleared_too(self):
        registry = JobRegistry()
        job = finished(registry, "a.pdf", JobState.FAILED)
        assert registry.remove(job.id) is not None

    def test_a_running_job_is_never_removed(self):
        # Its worker is still emitting progress for that id, and its output
        # directory is half written.
        registry = JobRegistry()
        job = registry.create("a.pdf", Path("a.pdf"))
        registry.mark_running(job)
        assert registry.remove(job.id) is None
        assert registry.get(job.id) is job

    def test_a_queued_job_is_never_removed(self):
        registry = JobRegistry()
        job = registry.create("a.pdf", Path("a.pdf"))
        assert registry.remove(job.id) is None

    def test_removing_an_unknown_job_is_not_an_error(self):
        assert JobRegistry().remove("ghost") is None


class TestRemovingFinished:
    def test_only_finished_jobs_are_cleared(self):
        registry = JobRegistry()
        done = finished(registry, "done.pdf")
        failed = finished(registry, "failed.pdf", JobState.FAILED)
        running = registry.create("running.pdf", Path("running.pdf"))
        registry.mark_running(running)

        removed = {job.id for job in registry.remove_finished()}
        assert removed == {done.id, failed.id}
        assert [job.id for job in registry.list()] == [running.id]

    def test_the_pending_count_survives_a_clear(self):
        registry = JobRegistry()
        finished(registry, "done.pdf")
        registry.mark_running(registry.create("running.pdf", Path("running.pdf")))
        registry.remove_finished()
        assert registry.pending == 1


class TestBatchBookkeeping:
    def test_a_cleared_job_leaves_its_batch(self):
        registry = JobRegistry()
        batch = registry.create_batch("Lote")
        first = registry.create("a.pdf", Path("a.pdf"), batch_id=batch.id)
        second = registry.create("b.pdf", Path("b.pdf"), batch_id=batch.id)
        registry.mark_done(first, {"groups": [], "review_queue": []})
        registry.mark_done(second, {"groups": [], "review_queue": []})

        registry.remove(first.id)
        assert registry.get_batch(batch.id).job_ids == [second.id]

    def test_an_emptied_batch_is_dropped(self):
        # A label with no referent would keep an empty card on the screen the
        # operator just asked to clear.
        registry = JobRegistry()
        batch = registry.create_batch("Lote")
        job = registry.create("a.pdf", Path("a.pdf"), batch_id=batch.id)
        registry.mark_done(job, {"groups": [], "review_queue": []})
        registry.remove(job.id)
        assert registry.get_batch(batch.id) is None
        assert registry.list_batches() == []


class TestClearEndpoints:
    @staticmethod
    def a_done_job(name: str = "a.pdf"):
        """A finished job with output on disk, without waiting on a worker."""
        from resolutions.api import main

        job = main.registry.create(name, Path(name))
        main.registry.mark_done(job, {"groups": [], "review_queue": []})
        directory = main.settings.output_dir / job.id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "00086__acta.pdf").write_bytes(b"pdf")
        return job, directory

    def test_clearing_reports_what_it_removed(self, client):
        first, _ = self.a_done_job("a.pdf")
        second, _ = self.a_done_job("b.pdf")
        payload = client.request("DELETE", "/api/jobs").json()
        assert payload["removed"] == 2
        assert set(payload["ids"]) == {first.id, second.id}
        assert client.get("/api/jobs").json() == {"jobs": []}

    def test_clearing_an_empty_workspace_removes_nothing(self, client):
        assert client.request("DELETE", "/api/jobs").json() == {"removed": 0, "ids": []}
        assert client.get("/api/jobs").json() == {"jobs": []}

    def test_deleting_an_unknown_document_is_not_found(self, client):
        response = client.request("DELETE", "/api/jobs/ghost")
        assert response.status_code == 404
        assert response.json()["detail"] == "El trabajo no existe"

    def test_deleting_one_document_leaves_the_others(self, client):
        first, _ = self.a_done_job("a.pdf")
        self.a_done_job("b.pdf")

        assert client.request("DELETE", f"/api/jobs/{first.id}").status_code == 200
        assert len(client.get("/api/jobs").json()["jobs"]) == 1

    def test_purging_one_document_takes_its_files_with_it(self, client):
        first, first_dir = self.a_done_job("a.pdf")
        _, second_dir = self.a_done_job("b.pdf")

        response = client.request("DELETE", f"/api/jobs/{first.id}?purge=true")
        assert response.json()["purged"] is True
        assert not first_dir.exists()
        assert second_dir.exists()

    def test_a_document_still_processing_is_refused(self, client):
        from resolutions.api import main

        job = main.registry.create("busy.pdf", Path("busy.pdf"))
        main.registry.mark_running(job)
        response = client.request("DELETE", f"/api/jobs/{job.id}")
        assert response.status_code == 409
        assert response.json()["detail"] == "El documento todavía se está procesando"

    def test_clearing_the_screen_keeps_the_generated_pdfs(self, client):
        # Clearing empties a screen; it does not undo the work. The inventory
        # still links at these files, so they have to survive.
        _, directory = self.a_done_job()
        client.request("DELETE", "/api/jobs")
        assert (directory / "00086__acta.pdf").is_file()

    def test_a_cleared_document_can_still_be_downloaded(self, client):
        job, _ = self.a_done_job()
        client.request("DELETE", "/api/jobs")
        response = client.get(f"/api/jobs/{job.id}/outputs/00086__acta.pdf")
        assert response.status_code == 200
        assert response.content == b"pdf"

    def test_a_removal_is_announced_to_open_tabs(self):
        # A second tab that never hears about the deletion keeps showing a folder
        # whose files are already gone.
        registry = JobRegistry()
        job = finished(registry, "a.pdf")
        queue = registry.subscribe()
        while not queue.empty():
            queue.get_nowait()

        registry.remove(job.id)
        assert queue.get_nowait()["deleted"] is True
