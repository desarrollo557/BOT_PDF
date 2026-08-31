from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol, runtime_checkable

from ..domain.grouping import GroupingResult
from .inventory import Inventory


@dataclass(frozen=True, slots=True)
class Band:
    """A fractional rectangle of a page, in 0..1 coordinates.

    Fractional rather than absolute so one band travels across A4, Letter and
    whatever a scanner decided the page size was that morning.
    """

    x0: float = 0.0
    y0: float = 0.0
    x1: float = 1.0
    y1: float = 1.0

    def __post_init__(self) -> None:
        if not (0.0 <= self.x0 < self.x1 <= 1.0 and 0.0 <= self.y0 < self.y1 <= 1.0):
            raise ValueError(f"degenerate band: {self}")

    @property
    def area(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)


#: Where a resolution number lives on virtually every administrative document.
#: Rendering this instead of the full page is a ~10x cut in OCR pixels and, when
#: a crop reaches the vision model, roughly the same cut in image tokens.
HEADER_BAND = Band(0.0, 0.0, 1.0, 0.28)


@dataclass(frozen=True, slots=True)
class OcrResult:
    text: str
    mean_confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class Crop:
    """A rendered slice of one page, queued for the vision model."""

    page_number: int
    image_png: bytes


@runtime_checkable
class PageSource(Protocol):
    """A document opened for reading, one page at a time.

    Deliberately page-at-a-time: a 400-page scan rendered eagerly is hundreds of
    megabytes of pixmaps, and doing that on 16 workers is how a box dies.
    """

    @property
    def page_count(self) -> int: ...

    def text_of(self, page_number: int) -> str: ...

    def render(self, page_number: int, band: Band | None = None, dpi: int = 200) -> bytes: ...

    def close(self) -> None: ...


@runtime_checkable
class DocumentStore(Protocol):
    def open(self, document: Path) -> PageSource: ...


@runtime_checkable
class OcrEngine(Protocol):
    def read(self, image_png: bytes) -> OcrResult: ...


@runtime_checkable
class VisionOracle(Protocol):
    """Last resort reader. Answers for a batch of crops in one round trip."""

    def read_codes(self, crops: list[Crop]) -> dict[int, str | None]: ...


@runtime_checkable
class RoiRegistry(Protocol):
    """Remembers where the number sits for each layout that has been seen.

    This is the difference between paying the model once per layout and paying it
    once per page. The same template repeats across tens of thousands of pages.
    """

    def lookup(self, fingerprint: str) -> Band | None: ...

    def remember(self, fingerprint: str, band: Band) -> None: ...


@runtime_checkable
class DocumentAssembler(Protocol):
    def write(
        self,
        source: Path,
        result: GroupingResult,
        destination: Path,
    ) -> Iterable[Path]: ...


@runtime_checkable
class InventoryStore(Protocol):
    """Persists the record of what a source document produced."""

    def write(self, inventory: Inventory, destination: Path) -> Path: ...
