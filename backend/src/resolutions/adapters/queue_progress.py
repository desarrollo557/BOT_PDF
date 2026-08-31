from __future__ import annotations

from ..application.progress import ProgressEvent


class QueueProgressReporter:
    """Ships progress out of a worker process through a shared queue.

    ``put_nowait`` on purpose: if the consumer falls behind, telemetry is dropped
    rather than allowed to block a document that is otherwise processing fine.
    Losing a progress frame costs a stale bar for 250ms; blocking costs throughput.
    """

    def __init__(self, queue, job_id: str) -> None:
        self._queue = queue
        self._job_id = job_id

    def emit(self, event: ProgressEvent) -> None:
        try:
            self._queue.put_nowait({"job_id": self._job_id, **event.as_dict()})
        except Exception:  # noqa: BLE001 - full queue, dead manager, shutting down
            return None
