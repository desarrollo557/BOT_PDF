"""Turning a shuffled box of scans into one PDF per document.

The order matters and it is the whole design: fingerprint every page locally,
let structure settle every seam it can for free, and pay a model only for what
is left. On the expediente this was built against, the free tier answered the
seams that carried an explicit page count and the model was asked once, about
the rest, in a single request.

Classification comes after, never before. What kind of paper a segment is --
factura, pagaré, recurso de reposición -- is a question about a document that
already has edges. Asking it of a box that has not been cut yet is what makes a
classifier pick one answer for ninety pages of different things.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.fingerprint import Heading, PageFingerprint, fingerprint_page
from ..domain.segmentation import (
    Boundary,
    SegmentationResult,
    Verdict,
    assemble,
    decide_boundaries,
)
from .control import NullRunControl, RunControl
from .ports import BoundaryOracle, PageSource
from .progress import ProgressEvent, ProgressReporter, Stage


class SegmentDocument:
    """Cut a document wherever one piece of paper ends and the next begins."""

    def __init__(
        self,
        oracle: BoundaryOracle | None = None,
        reporter: ProgressReporter | None = None,
        control: RunControl | None = None,
    ) -> None:
        self._oracle = oracle
        self._reporter = reporter
        self._control = control or NullRunControl()

    def run(self, source: PageSource) -> SegmentationResult:
        fingerprints = self._read(source)
        if not fingerprints:
            return SegmentationResult()

        boundaries = decide_boundaries(fingerprints)
        boundaries = self._escalate(fingerprints, boundaries)

        result = assemble(fingerprints, boundaries)
        result.verify_integrity([f.page_number for f in fingerprints])
        return result

    def _read(self, source: PageSource) -> list[PageFingerprint]:
        total = source.page_count
        fingerprints: list[PageFingerprint] = []
        for page_number in range(1, total + 1):
            # Entre una hoja y la siguiente: aquí no hay nada a medio leer, así
            # que es el único sitio donde parar deja la caja en un estado que se
            # puede contar.
            self._control.check()
            fingerprints.append(
                fingerprint_page(
                    page_number,
                    source.text_of(page_number),
                    self._headings(source, page_number),
                )
            )
            self._report(Stage.IDENTIFYING, page_number, total, "leyendo la caja")
        return fingerprints

    @staticmethod
    def _headings(source: PageSource, page_number: int) -> list[Heading]:
        """Geometry when the source has it, nothing when it does not.

        A source that cannot say where its lines are is not an error: the
        fingerprint simply loses the letterhead signal and the rest still holds.
        """
        try:
            boxes = source.boxes_of(page_number)
        except Exception:  # noqa: BLE001 - geometry is an optimisation, not a requirement
            return []
        return [Heading(text=b.text, center_x=b.center_x, top=b.top) for b in boxes]

    def _escalate(
        self,
        fingerprints: Sequence[PageFingerprint],
        boundaries: list[Boundary],
    ) -> list[Boundary]:
        """Ask the model about the seams, and only the seams, structure missed."""
        seams = [(b.left, b.right) for b in boundaries if b.verdict is Verdict.UNDECIDED]
        if not seams or self._oracle is None:
            return boundaries

        # Y una vez más antes de preguntar. No es simetría con el bucle de
        # lectura: es el único punto del recorrido donde seguir cuesta dinero, y
        # una consulta pagada por un trabajo que el operador ya abandonó no la
        # recupera nadie.
        #
        # Fuera del `try`, y eso importa: dentro, el `except` que convierte una
        # caída del modelo en "estas costuras van a revisión" se tragaría también
        # la cancelación, y el trabajo seguiría como si nada hubiera pasado.
        self._control.check()

        self._report(Stage.IDENTIFYING, 0, len(seams), f"{len(seams)} dudas al modelo")
        try:
            answers = self._oracle.judge([f.compact() for f in fingerprints], seams)
        except Exception:  # noqa: BLE001 - a model outage degrades, it does not fail
            return boundaries

        resolved: list[Boundary] = []
        for boundary in boundaries:
            starts = answers.get((boundary.left, boundary.right))
            if boundary.verdict is not Verdict.UNDECIDED or starts is None:
                resolved.append(boundary)
                continue
            resolved.append(
                Boundary(
                    left=boundary.left,
                    right=boundary.right,
                    verdict=Verdict.STARTS if starts else Verdict.CONTINUES,
                    reason="decidido por el modelo",
                    deterministic=False,
                )
            )
        return resolved

    def _report(self, stage: Stage, done: int, total: int, detail: str) -> None:
        if self._reporter is None:
            return
        self._reporter.emit(ProgressEvent(stage=stage, done=done, total=total, detail=detail))
