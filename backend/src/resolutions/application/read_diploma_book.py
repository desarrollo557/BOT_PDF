"""Read a whole book of diploma registrations, one record per page.

The same cascade the resolution splitter uses, for a different question. The
embedded text layer answers most pages for nothing; a page that leaves a field
unread is re-rendered and passed to OCR, and only what was actually missing is
taken from that second reading. On the three printed books measured, the text
layer alone left 57 of 1 084 pages incomplete and OCR closed all but a handful.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from ..domain.diploma import DiplomaRecord, extract_diploma, lines_from_text, merge
from ..domain.page import Provenance
from .control import NullRunControl, RunControl
from .diagnostico import explicar
from .ports import OcrEngine
from .progress import NullProgressReporter, ProgressEvent, ProgressReporter, Stage

logger = logging.getLogger(__name__)

#: Escalations are rendered larger than the classification cascade uses. These
#: are small printed captions and eight-digit identity numbers, not a heading in
#: 24 point, and at 200 dpi Tesseract loses the digits that matter.
ESCALATION_DPI = 300


@dataclass(slots=True)
class BookReadingStats:
    """Where the readings came from, counted rather than assumed."""

    pages: int = 0
    from_text_layer: int = 0
    escalated: int = 0
    recovered_by_ocr: int = 0
    incomplete: list[int] = field(default_factory=list)
    failures: dict[int, str] = field(default_factory=dict)
    #: Cuántas páginas acabó respondiendo cada peldaño. No es lo mismo que
    #: ``escalated``, que cuenta los intentos: una escalada que falla deja en
    #: pie la lectura de la capa de texto, y aquí se cuenta esa.
    provenance: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "pages": self.pages,
            "from_text_layer": self.from_text_layer,
            "escalated": self.escalated,
            "recovered_by_ocr": self.recovered_by_ocr,
            "provenance": dict(self.provenance),
            "incomplete": list(self.incomplete),
            "failures": {str(page): error for page, error in sorted(self.failures.items())},
        }


class ReadDiplomaBook:
    """One book in, one record per page out."""

    def __init__(
        self,
        ocr: OcrEngine | None = None,
        progress: ProgressReporter | None = None,
        escalation_dpi: int = ESCALATION_DPI,
        control: RunControl | None = None,
    ) -> None:
        self._ocr = ocr
        self._progress = progress or NullProgressReporter()
        self._dpi = escalation_dpi
        self._control = control or NullRunControl()

    def execute(self, source) -> tuple[list[DiplomaRecord], BookReadingStats]:
        stats = BookReadingStats(pages=source.page_count)
        self._report(ProgressEvent(stage=Stage.OPENED, page_count=source.page_count))

        records: list[DiplomaRecord] = []
        for page_number in range(1, source.page_count + 1):
            record, provenance = self._read_page(source, page_number, stats)
            records.append(record)
            stats.provenance[str(provenance)] = stats.provenance.get(str(provenance), 0) + 1
            self._report(
                ProgressEvent(
                    stage=Stage.PAGE,
                    page_number=page_number,
                    page_count=source.page_count,
                    # De dónde salió la lectura. Decirlo no es adorno: la cinta
                    # de progreso pinta con la misma marca la página fallida y
                    # la que no declara procedencia, así que callarlo hacía que
                    # un libro entero se anunciara como ilegible mientras se
                    # leía perfectamente.
                    provenance=str(provenance),
                    failed=record.needs_review,
                    # Y por qué. Marcar una página sin decir qué le pasa obliga
                    # al operador a abrirla para averiguarlo, que es justo el
                    # trabajo que este sistema existe para ahorrarle.
                    detail=record.review_reason,
                )
            )

        # Sin DONE: leer no es terminar. Quien anuncia el final es quien sabe
        # qué queda por hacer después, que es el trabajo y no el lector.
        return records, stats

    def _read_page(
        self, source, page_number: int, stats: BookReadingStats
    ) -> tuple[DiplomaRecord, Provenance]:
        """El registro de la página y el peldaño del que salió.

        La procedencia es la del peldaño que produjo lo que se conserva, no la
        del último que se intentó: una escalada que falló deja en pie la lectura
        de la capa de texto, y decir "OCR" ahí sería contar el intento en vez
        del resultado.
        """
        # Entre una página y la siguiente: aquí no hay nada a medio leer, así que
        # es donde parar es seguro y reanudar significa continuar.
        self._control.check()
        try:
            record = extract_diploma(source.lines_of(page_number), page_number)
        except Exception as error:  # noqa: BLE001 - contained to this page
            logger.warning("no se pudo leer la página %s", page_number, exc_info=True)
            stats.failures[page_number] = explicar(error)
            return (
                DiplomaRecord(
                    page_number=page_number,
                    warnings=[f"la página no pudo procesarse: {error}"],
                ),
                Provenance.NONE,
            )

        # No basta con que estén todos los campos: una página que se
        # contradice a sí misma -- el folio del encabezado contra el del pie, un
        # nombre con un dígito dentro -- está completa y mal leída. El OCR entra
        # en las dos, porque en las dos hay algo que verificar.
        if not record.needs_review:
            stats.from_text_layer += 1
            return record, Provenance.TEXT_LAYER

        if self._ocr is None:
            stats.incomplete.append(page_number)
            return record, Provenance.TEXT_LAYER

        stats.escalated += 1
        try:
            image = source.render(page_number, None, self._dpi)
            second = extract_diploma(lines_from_text(self._ocr.read(image).text), page_number)
        except Exception as error:  # noqa: BLE001
            logger.warning("falló el OCR de la página %s", page_number, exc_info=True)
            stats.failures[page_number] = explicar(error)
            stats.incomplete.append(page_number)
            return record, Provenance.TEXT_LAYER

        merged = merge(record, second)
        if not merged.needs_review:
            stats.recovered_by_ocr += 1
        else:
            stats.incomplete.append(page_number)
        # La escalada renderiza la página entera, no una banda del encabezado.
        return merged, Provenance.OCR_FULL_PAGE

    def _report(self, event: ProgressEvent) -> None:
        try:
            self._progress.emit(event)
        except Exception:  # noqa: BLE001 - telemetry never breaks the work
            logger.debug("el informe de progreso falló, se continúa", exc_info=True)


def make_progress_hook(on_page: Callable[[int, int], None]) -> ProgressReporter:
    """Adapt a plain callback to the reporter the use case expects."""

    class _Hook:
        def emit(self, event: ProgressEvent) -> None:
            if event.stage is Stage.PAGE and event.page_number:
                on_page(event.page_number, event.page_count or 0)

    return _Hook()
