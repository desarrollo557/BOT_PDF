from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

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


@dataclass(frozen=True, slots=True)
class LineBox:
    """Dónde está un renglón dentro de su página, en fracciones de 0 a 1.

    En fracciones y no en puntos porque un expediente mezcla tamaños de hoja: la
    misma caja tiene que significar lo mismo en A4, en Carta y en lo que decidió
    el escáner esa mañana.

    ``center_x`` es el centro horizontal del renglón y ``top`` su borde
    superior. Con esos dos números se distingue un encabezado -- centrado y
    arriba -- de una frase que empieza por la palabra "Resolución" a media
    página, que es lo que hace falta y no cabe en el texto plano.
    """

    text: str
    center_x: float
    top: float


@runtime_checkable
class PageSource(Protocol):
    """A document opened for reading, one page at a time.

    Deliberately page-at-a-time: a 400-page scan rendered eagerly is hundreds of
    megabytes of pixmaps, and doing that on 16 workers is how a box dies.
    """

    @property
    def page_count(self) -> int: ...

    def text_of(self, page_number: int) -> str: ...

    def boxes_of(self, page_number: int) -> list[LineBox]:
        """Los renglones de la página con su sitio, en el orden de ``text_of``.

        Opcional: una fuente que no sepa dónde están sus renglones devuelve una
        lista vacía y el sistema decide sin geometría, como hacía antes.
        """
        return []

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
class BoundaryOracle(Protocol):
    """Judges the seams that structure could not settle.

    Takes the whole box at once, on purpose. Asked seam by seam, a model cannot
    know that pages 12 to 15 are all the same acta; given every page's
    fingerprint together it can. That it is also one round trip instead of one
    per boundary -- 124 of them on a real expediente -- is the smaller half of
    the argument.

    Which provider answers is not this layer's business: the same protocol is
    satisfied by Claude, by Gemini, and by the null implementation that sends
    every doubt to a human instead.
    """

    def judge(
        self,
        pages: list[dict[str, object]],
        seams: list[tuple[int, int]],
    ) -> dict[tuple[int, int], bool]:
        """True where the right-hand page of a seam opens a new document.

        A seam left out of the answer stays undecided. Silence is a valid reply
        -- an unanswered doubt goes to review, which is where a guess would have
        ended up anyway, only without the pretence.
        """
        ...


@runtime_checkable
class RoiRegistry(Protocol):
    """Remembers where the number sits for each layout that has been seen.

    This is the difference between paying the model once per layout and paying it
    once per page. The same template repeats across tens of thousands of pages.
    """

    def lookup(self, fingerprint: str) -> Band | None: ...

    def remember(self, fingerprint: str, band: Band) -> None: ...


@dataclass(frozen=True, slots=True)
class AssemblyResult:
    """What was written, and which pages could not be.

    A page that cannot be copied is named rather than silently missing: the
    document ships with everything that could be salvaged, and the operator gets
    a list instead of a page-count discrepancy to discover on their own.
    """

    outputs: list[Path] = field(default_factory=list)
    unwritable_pages: dict[int, str] = field(default_factory=dict)
    #: Resolution code -> the file name actually written for it. The writer may
    #: shorten a name to fit the filesystem, so the inventory records what is on
    #: disk rather than recomputing what it thinks should be.
    written: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class DocumentAssembler(Protocol):
    def write(
        self,
        source: Path,
        result: GroupingResult,
        destination: Path,
    ) -> AssemblyResult: ...


@runtime_checkable
class InventoryStore(Protocol):
    """Persists the record of what a source document produced."""

    def write(self, inventory: Inventory, destination: Path) -> Path: ...
