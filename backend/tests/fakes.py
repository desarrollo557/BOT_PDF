"""In-memory doubles so the pipeline can be tested without MuPDF or Tesseract."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from resolutions.application.inventory import Inventory
from resolutions.application.ports import Band, Crop, OcrResult
from resolutions.domain.grouping import GroupingResult
from resolutions.domain.naming import output_filename


@dataclass
class FakePage:
    """A page described by what each rung of the cascade would see.

    ``text`` is the embedded text layer (empty means a scan), ``header`` is what
    OCR reads off the top band, and ``body`` is the rest of the pixels.
    """

    text: str = ""
    header: str = ""
    body: str = ""


@dataclass
class FakePageSource:
    pages: list[FakePage]
    renders: list[tuple[int, Band | None]] = field(default_factory=list)
    closed: bool = False

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def text_of(self, page_number: int) -> str:
        return self.pages[page_number - 1].text

    def render(self, page_number: int, band: Band | None = None, dpi: int = 200) -> bytes:
        self.renders.append((page_number, band))
        page = self.pages[page_number - 1]
        payload = page.header if band is not None else f"{page.header}\n{page.body}".strip()
        return payload.encode()

    def close(self) -> None:
        self.closed = True

    @property
    def band_renders(self) -> int:
        return sum(1 for _, band in self.renders if band is not None)

    @property
    def full_renders(self) -> int:
        return sum(1 for _, band in self.renders if band is None)


@dataclass
class FakeDocumentStore:
    source: FakePageSource

    def open(self, document: Path) -> FakePageSource:
        return self.source


@dataclass
class FakeOcr:
    """Reads back the fake render payload and counts calls, so cost is assertable."""

    calls: int = 0

    def read(self, image_png: bytes) -> OcrResult:
        self.calls += 1
        text = image_png.decode()
        return OcrResult(text=text, mean_confidence=0.8 if text else 0.0)


@dataclass
class FakeVision:
    answers: dict[int, str | None] = field(default_factory=dict)
    batches: list[list[int]] = field(default_factory=list)

    def read_codes(self, crops: list[Crop]) -> dict[int, str | None]:
        self.batches.append([crop.page_number for crop in crops])
        return {crop.page_number: self.answers.get(crop.page_number) for crop in crops}


@dataclass
class FakeAssembler:
    written: list[tuple[str, list[int]]] = field(default_factory=list)

    def write(self, source: Path, result: GroupingResult, destination: Path) -> list[Path]:
        self.written = [(g.code.value, g.page_numbers) for g in result.groups]
        return [destination / output_filename(g.code, g.title) for g in result.groups]


@dataclass
class FakeInventoryStore:
    recorded: Inventory | None = None

    def write(self, inventory: Inventory, destination: Path) -> Path:
        self.recorded = inventory
        return destination / "inventory.json"


BODY = (
    "Que la presente medida se dicta en uso de las facultades conferidas por el "
    "articulo 4 del decreto reglamentario vigente, y en atencion a lo dictaminado "
    "por el servicio juridico permanente de esta jurisdiccion, sin observaciones."
)
