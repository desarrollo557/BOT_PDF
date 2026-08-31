"""The idle janitor.

Three things accumulate during a run and are worthless once it ends: an upload
whose job is gone, an output directory nothing references, and the page ribbon
of a document whose report already says everything the ribbon said. None is a
product, and the generated PDFs and the ledger are never touched.

The two guards are the point of the design. Sweeping under a running worker
would delete a half-written output directory, and sweeping when nothing has
changed would turn an idle system into a directory listing every thirty seconds.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from resolutions.api.janitor import IdleJanitor
from resolutions.api.jobs import JobRegistry
from resolutions.api.settings import Settings


@pytest.fixture
def workspace(tmp_path):
    settings = replace(
        Settings(),
        upload_dir=tmp_path / "uploads",
        output_dir=tmp_path / "outputs",
        ledger_path=tmp_path / "inventory.jsonl",
    )
    settings.ensure_directories()
    return settings


def sweep(janitor: IdleJanitor, force: bool = False):
    return asyncio.run(janitor.sweep_if_idle(force=force))


def upload(settings: Settings, name: str) -> Path:
    path = settings.upload_dir / name
    path.write_bytes(b"%PDF-1.4")
    return path


def outputs(settings: Settings, job_id: str) -> Path:
    directory = settings.output_dir / job_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "00086__acta.pdf").write_bytes(b"pdf")
    return directory


class TestIdleGuard:
    def test_nothing_is_swept_while_a_document_is_running(self, workspace):
        registry = JobRegistry()
        registry.mark_running(registry.create("a.pdf", workspace.upload_dir / "a.pdf"))
        orphan = upload(workspace, "orphan.pdf")

        assert sweep(IdleJanitor(registry, workspace)) is None
        assert orphan.exists()

    def test_nothing_is_swept_while_a_document_is_queued(self, workspace):
        registry = JobRegistry()
        registry.create("a.pdf", workspace.upload_dir / "a.pdf")
        assert sweep(IdleJanitor(registry, workspace)) is None

    def test_a_forced_sweep_still_refuses_to_run_under_a_worker(self, workspace):
        registry = JobRegistry()
        registry.mark_running(registry.create("a.pdf", workspace.upload_dir / "a.pdf"))
        assert sweep(IdleJanitor(registry, workspace), force=True) is None


class TestChangeGuard:
    def test_an_unchanged_registry_is_not_swept_twice(self, workspace):
        # The whole point: an idle system costs one integer comparison, not a
        # directory listing every thirty seconds.
        janitor = IdleJanitor(JobRegistry(), workspace)
        assert sweep(janitor) is not None
        assert sweep(janitor) is None

    def test_a_finished_document_makes_the_next_tick_sweep_again(self, workspace):
        registry = JobRegistry()
        janitor = IdleJanitor(registry, workspace)
        sweep(janitor)

        job = registry.create("a.pdf", workspace.upload_dir / "a.pdf")
        registry.mark_done(job, {"groups": []})
        assert janitor.should_sweep() is True

    def test_a_forced_sweep_ignores_the_change_guard(self, workspace):
        janitor = IdleJanitor(JobRegistry(), workspace)
        sweep(janitor)
        assert sweep(janitor, force=True) is not None


class TestReclaiming:
    def test_an_upload_whose_job_is_gone_is_removed(self, workspace):
        orphan = upload(workspace, "orphan.pdf")
        result = sweep(IdleJanitor(JobRegistry(), workspace))
        assert not orphan.exists()
        assert result.as_dict()["uploads"] == 1

    def test_an_upload_a_job_still_points_at_is_kept(self, workspace):
        registry = JobRegistry()
        source = upload(workspace, "live.pdf")
        job = registry.create("live.pdf", source)
        registry.mark_done(job, {"groups": []})

        sweep(IdleJanitor(registry, workspace))
        assert source.exists()

    def test_an_output_directory_nothing_references_is_removed(self, workspace):
        stale = outputs(workspace, "ghost-job")
        sweep(IdleJanitor(JobRegistry(), workspace))
        assert not stale.exists()

    def test_output_the_ledger_still_references_is_never_removed(self, workspace):
        # This is what makes clearing the screen safe: the job is gone from the
        # registry, and only the ledger stands between its PDFs and the sweep.
        kept = outputs(workspace, "recorded-job")
        janitor = IdleJanitor(JobRegistry(), workspace, referenced=lambda: {"recorded-job"})
        sweep(janitor)
        assert (kept / "00086__acta.pdf").is_file()

    def test_output_of_a_live_job_is_never_removed(self, workspace):
        registry = JobRegistry()
        job = registry.create("a.pdf", workspace.upload_dir / "a.pdf")
        registry.mark_done(job, {"groups": []})
        directory = outputs(workspace, job.id)
        sweep(IdleJanitor(registry, workspace))
        assert directory.exists()

    def test_a_ribbon_is_dropped_once_the_document_is_reported(self, workspace):
        registry = JobRegistry()
        job = registry.create("a.pdf", workspace.upload_dir / "a.pdf")
        registry.apply_progress({"job_id": job.id, "stage": "opened", "page_count": 400})
        registry.mark_done(job, {"groups": []})

        assert len(job.progress.marks) == 400
        result = sweep(IdleJanitor(registry, workspace))
        assert job.progress.marks == []
        assert result.as_dict()["ribbons"] == 1

    def test_the_page_count_survives_the_ribbon(self, workspace):
        # The report is what the finished view reads; only the per-page marks go.
        registry = JobRegistry()
        job = registry.create("a.pdf", workspace.upload_dir / "a.pdf")
        registry.apply_progress({"job_id": job.id, "stage": "opened", "page_count": 12})
        registry.mark_done(job, {"groups": []})
        sweep(IdleJanitor(registry, workspace))
        assert job.progress.page_count == 12


class TestSafety:
    def test_a_broken_reference_index_sweeps_nothing(self, workspace):
        # Rather than guess, it does nothing. Guessing here deletes real output.
        def broken():
            raise RuntimeError("ledger unreadable")

        stale = outputs(workspace, "ghost-job")
        janitor = IdleJanitor(JobRegistry(), workspace, referenced=broken)
        with pytest.raises(RuntimeError):
            sweep(janitor)
        assert stale.exists()

    def test_a_sweep_with_nothing_to_do_reports_empty(self, workspace):
        result = sweep(IdleJanitor(JobRegistry(), workspace))
        assert result.empty is True
        assert result.as_dict() == {"uploads": 0, "outputs": 0, "ribbons": 0}


class TestCacheEndpoints:
    def test_the_cache_status_reports_the_idle_state(self, client):
        payload = client.get("/api/cache").json()
        assert payload["idle"] is True
        assert payload["interval_seconds"] > 0

    def test_a_manual_sweep_runs_when_the_queue_is_empty(self, client):
        assert client.post("/api/cache/sweep").json()["swept"] is True

    def test_a_manual_sweep_is_refused_while_work_is_in_flight(self, client):
        from resolutions.api import main

        main.registry.mark_running(main.registry.create("a.pdf", Path("a.pdf")))
        payload = client.post("/api/cache/sweep").json()
        assert payload["swept"] is False
        assert payload["reason"] == "hay documentos en proceso"
