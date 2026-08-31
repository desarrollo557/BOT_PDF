from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from itertools import count
from pathlib import Path
from uuid import uuid4

#: Creation order, monotonic and collision-free. Wall-clock timestamps tie when
#: fifty files are queued in the same millisecond, and a tie makes the list order
#: arbitrary — which reads as a bug to whoever is watching the screen.
_sequence = count()


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


#: One character per page, so a 400-page ribbon travels as a 400-byte string
#: instead of an array of objects. At 50 concurrent documents that difference is
#: the whole reason the live view stays cheap.
PENDING_MARK = "."
PROVENANCE_MARKS = {
    "text_layer": "t",
    "ocr_region": "h",
    "ocr_full_page": "f",
    "vision_model": "v",
    "none": "x",
}
FAILED_MARK = "x"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class JobProgress:
    """Live state of one document, rebuilt from the worker's event stream."""

    stage: str = "queued"
    page_count: int = 0
    pages_done: int = 0
    failed_pages: int = 0
    by_provenance: dict[str, int] = field(default_factory=dict)
    marks: list[str] = field(default_factory=list)
    started_monotonic: float | None = None
    elapsed_seconds: float = 0.0

    @property
    def pages_per_second(self) -> float:
        if not self.elapsed_seconds or not self.pages_done:
            return 0.0
        return self.pages_done / self.elapsed_seconds

    @property
    def percent(self) -> float:
        if not self.page_count:
            return 0.0
        return min(100.0, 100.0 * self.pages_done / self.page_count)

    def apply(self, event: dict) -> None:
        stage = str(event.get("stage") or "")
        if stage == "opened":
            self.page_count = int(event.get("page_count") or 0)
            self.marks = [PENDING_MARK] * self.page_count
            self.started_monotonic = time.monotonic()
            self.stage = "analysing"
            return

        if stage == "page":
            page_number = int(event.get("page_number") or 0)
            failed = bool(event.get("failed"))
            provenance = str(event.get("provenance") or "none")
            mark = FAILED_MARK if failed else PROVENANCE_MARKS.get(provenance, PENDING_MARK)

            if 1 <= page_number <= len(self.marks):
                previous = self.marks[page_number - 1]
                self.marks[page_number - 1] = mark
                # The vision rung revisits a page already counted during
                # analysis, so it repaints the mark without double counting.
                if previous != PENDING_MARK:
                    self._recount(previous, mark, failed)
                    return

            self.pages_done += 1
            self.by_provenance[provenance] = self.by_provenance.get(provenance, 0) + 1
            if failed:
                self.failed_pages += 1
            self._tick()
            return

        if stage in {"grouping", "assembling", "done", "failed"}:
            self.stage = stage
            self._tick()

    def _recount(self, previous_mark: str, mark: str, failed: bool) -> None:
        for name, char in PROVENANCE_MARKS.items():
            if char == previous_mark:
                self.by_provenance[name] = max(0, self.by_provenance.get(name, 0) - 1)
                break
        for name, char in PROVENANCE_MARKS.items():
            if char == mark:
                self.by_provenance[name] = self.by_provenance.get(name, 0) + 1
                break
        if failed:
            self.failed_pages += 1

    def _tick(self) -> None:
        if self.started_monotonic is not None:
            self.elapsed_seconds = time.monotonic() - self.started_monotonic

    def as_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "page_count": self.page_count,
            "pages_done": self.pages_done,
            "failed_pages": self.failed_pages,
            "by_provenance": dict(self.by_provenance),
            "ribbon": "".join(self.marks),
            "percent": round(self.percent, 2),
            "pages_per_second": round(self.pages_per_second, 2),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }


@dataclass(slots=True)
class Job:
    id: str
    filename: str
    source: Path
    batch_id: str | None = None
    state: JobState = JobState.QUEUED
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    report: dict | None = None
    progress: JobProgress = field(default_factory=JobProgress)
    sequence: int = field(default_factory=lambda: next(_sequence))

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "batch_id": self.batch_id,
            "filename": self.filename,
            "state": str(self.state),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "report": self.report,
            "progress": self.progress.as_dict(),
        }


@dataclass(slots=True)
class Batch:
    id: str
    name: str
    created_at: str = field(default_factory=_now)
    job_ids: list[str] = field(default_factory=list)
    sequence: int = field(default_factory=lambda: next(_sequence))


class JobRegistry:
    """Jobs, batches, live progress, and a fan-out channel for the UI.

    In memory on purpose for the demo. The surface is small enough that moving it
    to Postgres or Redis touches this file and nothing else.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._batches: dict[str, Batch] = {}
        self._subscribers: set[asyncio.Queue[dict]] = set()
        self._dirty: set[str] = set()

    # -- batches --------------------------------------------------------------

    def create_batch(self, name: str) -> Batch:
        batch = Batch(id=uuid4().hex, name=name or "Lote sin nombre")
        self._batches[batch.id] = batch
        return batch

    def get_batch(self, batch_id: str) -> Batch | None:
        return self._batches.get(batch_id)

    def list_batches(self) -> list[Batch]:
        return sorted(self._batches.values(), key=lambda batch: batch.sequence, reverse=True)

    def batch_summary(self, batch: Batch) -> dict[str, object]:
        jobs = [self._jobs[job_id] for job_id in batch.job_ids if job_id in self._jobs]
        states = [job.state for job in jobs]
        pages_total = sum(job.progress.page_count for job in jobs)
        pages_done = sum(job.progress.pages_done for job in jobs)
        resolutions = sum(
            len(job.report["groups"]) for job in jobs if job.report and "groups" in job.report
        )
        review = sum(
            len(job.report["review_queue"]) for job in jobs if job.report and "review_queue" in job.report
        )
        return {
            "id": batch.id,
            "name": batch.name,
            "created_at": batch.created_at,
            "documents": len(jobs),
            "done": states.count(JobState.DONE),
            "failed": states.count(JobState.FAILED),
            "running": states.count(JobState.RUNNING),
            "queued": states.count(JobState.QUEUED),
            "pages_total": pages_total,
            "pages_done": pages_done,
            "percent": round(100.0 * pages_done / pages_total, 2) if pages_total else 0.0,
            "resolutions": resolutions,
            "review_items": review,
            "job_ids": list(batch.job_ids),
        }

    # -- jobs -----------------------------------------------------------------

    def create(self, filename: str, source: Path, batch_id: str | None = None) -> Job:
        job = Job(id=uuid4().hex, filename=filename, source=source, batch_id=batch_id)
        self._jobs[job.id] = job
        if batch_id and batch_id in self._batches:
            self._batches[batch_id].job_ids.append(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda job: job.sequence, reverse=True)

    @property
    def pending(self) -> int:
        return sum(
            1 for job in self._jobs.values() if job.state in (JobState.QUEUED, JobState.RUNNING)
        )

    def mark_running(self, job: Job) -> None:
        job.state = JobState.RUNNING
        job.started_at = _now()
        self.publish(job)

    def mark_done(self, job: Job, report: dict) -> None:
        job.state = JobState.DONE
        job.report = report
        job.finished_at = _now()
        job.progress.stage = "done"
        self.publish(job)

    def mark_failed(self, job: Job, error: str) -> None:
        job.state = JobState.FAILED
        job.error = error
        job.finished_at = _now()
        job.progress.stage = "failed"
        self.publish(job)

    # -- live progress --------------------------------------------------------

    def apply_progress(self, event: dict) -> None:
        """Fold one worker event into its job, and mark the job for the next tick.

        Events are not published one by one: a 400-page document would push 400
        frames at a browser that can only usefully render a handful per second.
        """
        job = self._jobs.get(str(event.get("job_id") or ""))
        if job is None:
            return
        job.progress.apply(event)
        self._dirty.add(job.id)

    def flush(self) -> list[Job]:
        """Return the jobs that changed since the last tick, and clear the flags."""
        changed = [self._jobs[job_id] for job_id in self._dirty if job_id in self._jobs]
        self._dirty.clear()
        for job in changed:
            self.publish(job)
        return changed

    # -- fan-out --------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue[dict]:
        # Bounded: a tab that stops reading gets frames dropped rather than
        # growing the server's memory on its behalf.
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self._subscribers.discard(queue)

    def publish(self, job: Job) -> None:
        payload = job.as_dict()
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass
