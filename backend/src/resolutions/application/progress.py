from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Stage(StrEnum):
    """Milestones a document passes through, in order."""

    OPENED = "opened"
    PAGE = "page"
    GROUPING = "grouping"
    ASSEMBLING = "assembling"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """One observable moment in the processing of a document.

    Emitted from inside the worker, so the operator watches the real cascade
    rather than a spinner that means nothing.
    """

    stage: Stage
    page_number: int | None = None
    page_count: int | None = None
    provenance: str | None = None
    code: str | None = None
    failed: bool = False
    detail: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "stage": str(self.stage),
            "page_number": self.page_number,
            "page_count": self.page_count,
            "provenance": self.provenance,
            "code": self.code,
            "failed": self.failed,
            "detail": self.detail,
        }


@runtime_checkable
class ProgressReporter(Protocol):
    """Receives progress events.

    Implementations are called from worker threads and must never raise: a
    telemetry problem is not a reason to lose a document.
    """

    def emit(self, event: ProgressEvent) -> None: ...


class NullProgressReporter:
    """The default. Processing does not depend on anyone watching."""

    def emit(self, event: ProgressEvent) -> None:
        return None


class RecordingProgressReporter:
    """Keeps events in memory. Useful for tests and for single-process runs."""

    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    def emit(self, event: ProgressEvent) -> None:
        self.events.append(event)

    def stages(self) -> list[str]:
        return [str(event.stage) for event in self.events]
