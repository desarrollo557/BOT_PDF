"""Leer un legajo de expedientes académicos, un expediente por estudiante.

La misma cascada que usa el lector de libros de diplomas, con una diferencia que
cambia dónde se decide todo: allí la unidad documental era la página, así que
leer y agrupar eran la misma cosa. Aquí no. La carátula de matrícula y las hojas
de registro de estudios que la siguen son un solo expediente, de modo que
primero se lee hoja por hoja y sólo después, con todas las hojas leídas, se
puede decir dónde empieza y dónde acaba cada uno.

La escalada a OCR se paga por hoja y sólo cuando la hoja no dijo nada de sí
misma. Una hoja de asignaturas sin nombre no es una lectura fallida -- el nombre
está en su carátula -- y volver a renderizarla a 300 dpi para buscar algo que no
está impreso sería gastar el presupuesto de OCR en la página equivocada.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..domain.diploma import lines_from_text
from ..domain.matricula import (
    StudentPage,
    StudentRecord,
    extract_student_page,
    group_students,
    merge_pages,
)
from ..domain.page import Provenance
from .control import NullRunControl, RunControl
from .diagnostico import explicar
from .ports import OcrEngine
from .progress import NullProgressReporter, ProgressEvent, ProgressReporter, Stage

logger = logging.getLogger(__name__)

#: A la misma resolución que el libro de diplomas y por la misma razón: lo que
#: hay que leer son leyendas pequeñas y códigos de nueve cifras, no titulares.
ESCALATION_DPI = 300


@dataclass(slots=True)
class RecordsReadingStats:
    """De dónde salió cada lectura, contado y no supuesto."""

    pages: int = 0
    from_text_layer: int = 0
    escalated: int = 0
    recovered_by_ocr: int = 0
    students: int = 0
    incomplete: list[int] = field(default_factory=list)
    failures: dict[int, str] = field(default_factory=dict)
    #: Cuántas hojas acabó respondiendo cada peldaño.
    provenance: dict[str, int] = field(default_factory=dict)
    #: Lo que decidió el revisor de nombres común de cada estudiante, por su
    #: primera hoja: el trabajo lo lleva al informe (2026-11-17).
    nombres_revisados: dict = field(default_factory=dict, repr=False)

    def as_dict(self) -> dict[str, object]:
        return {
            "pages": self.pages,
            "provenance": dict(self.provenance),
            "from_text_layer": self.from_text_layer,
            "escalated": self.escalated,
            "recovered_by_ocr": self.recovered_by_ocr,
            "students": self.students,
            "incomplete": list(self.incomplete),
            "failures": {str(page): error for page, error in sorted(self.failures.items())},
        }


class ReadStudentRecords:
    """Un legajo dentro, un expediente por estudiante fuera."""

    def __init__(
        self,
        ocr: OcrEngine | None = None,
        progress: ProgressReporter | None = None,
        escalation_dpi: int = ESCALATION_DPI,
        control: RunControl | None = None,
        #: La IA que mira la zona del nombre (el revisor de nombres común,
        #: 2026-11-17), y el padrón para sus candidatos.
        juez_del_nombre=None,
        padron=None,
    ) -> None:
        self._juez_del_nombre = juez_del_nombre
        self._padron = padron
        self._ocr = ocr
        self._progress = progress or NullProgressReporter()
        self._dpi = escalation_dpi
        self._control = control or NullRunControl()

    def execute(self, source) -> tuple[list[StudentRecord], RecordsReadingStats]:
        stats = RecordsReadingStats(pages=source.page_count)
        self._report(ProgressEvent(stage=Stage.OPENED, page_count=source.page_count))

        paginas: list[StudentPage] = []
        for page_number in range(1, source.page_count + 1):
            hoja, procedencia = self._read_page(source, page_number, stats)
            paginas.append(hoja)
            stats.provenance[str(procedencia)] = stats.provenance.get(str(procedencia), 0) + 1
            self._report(
                ProgressEvent(
                    stage=Stage.PAGE,
                    page_number=page_number,
                    page_count=source.page_count,
                    # Sin esto la cinta de progreso pinta la página con la misma
                    # marca que usa para una página ilegible, y el operador ve un
                    # legajo entero anunciado como fallido mientras se lee bien.
                    provenance=str(procedencia),
                    failed=hoja.needs_review,
                    detail=hoja.review_reason,
                )
            )

        expedientes = group_students(paginas)
        stats.students = len(expedientes)
        # El nombre de cada estudiante, con el revisor de nombres común a todas
        # las habilidades (2026-11-17): la IA mira la zona del nombre, a todos.
        expedientes = self._revisar_los_nombres(source, expedientes, stats)
        return expedientes, stats

    def _revisar_los_nombres(self, source, expedientes, stats: RecordsReadingStats):
        """El nombre de cada estudiante -- apellidos y nombres -- con la pieza común de los nombres.

        Lo que la IA corrige vuelve a sus dos casillas: las primeras palabras a
        los apellidos, tantas como tenían, y lo demás a los nombres.
        """
        from dataclasses import replace

        from .acta_consejo import nombres_conocidos
        from .revisor_de_nombres import (
            PorRevisar,
            de_la_habilidad,
            revisar_los_nombres,
            zona_para_mirar,
        )

        regla = de_la_habilidad("matriculas")
        con_nombre = [(indice, expediente) for indice, expediente in enumerate(expedientes) if expediente.nombre]
        if not con_nombre:
            return expedientes
        personas = [
            PorRevisar(
                indice,
                [expediente.nombre],
                imagen=(lambda pagina=expediente.page_number: zona_para_mirar(source, pagina, regla))
                if self._juez_del_nombre is not None
                else None,
                pagina=expediente.page_number,
            )
            for indice, expediente in con_nombre
        ]
        conocidas = nombres_conocidos() | (self._padron.palabras if self._padron is not None else frozenset())
        revisados = revisar_los_nombres(
            personas, conocidas=conocidas, padron=self._padron, juez=self._juez_del_nombre, control=self._control,
        )
        expedientes = list(expedientes)
        for indice, revisado in revisados.items():
            expediente = expedientes[indice]
            stats.nombres_revisados[expediente.page_number] = revisado
            if revisado.nombre and revisado.nombre != expediente.nombre:
                palabras = revisado.nombre.split()
                cuantos = len((expediente.apellidos or "").split())
                expedientes[indice] = replace(
                    expediente,
                    apellidos=" ".join(palabras[:cuantos]) or expediente.apellidos,
                    nombres=" ".join(palabras[cuantos:]) or expediente.nombres,
                )
        return expedientes

    def _read_page(
        self, source, page_number: int, stats: RecordsReadingStats
    ) -> tuple[StudentPage, Provenance]:
        """La hoja leída y el peldaño del que salió lo que se conserva."""
        # Entre una hoja y la siguiente no hay nada a medio leer, así que es
        # donde parar es seguro y reanudar significa continuar.
        self._control.check()
        try:
            hoja = extract_student_page(source.lines_of(page_number), page_number)
        except Exception as error:  # noqa: BLE001 - contenido en esta página
            logger.warning("no se pudo leer la página %s", page_number, exc_info=True)
            stats.failures[page_number] = explicar(error)
            return (
                StudentPage(
                    page_number=page_number,
                    warnings=[f"la página no pudo procesarse: {error}"],
                ),
                Provenance.NONE,
            )

        if not hoja.needs_review:
            stats.from_text_layer += 1
            return hoja, Provenance.TEXT_LAYER

        if self._ocr is None:
            stats.incomplete.append(page_number)
            return hoja, Provenance.TEXT_LAYER

        stats.escalated += 1
        try:
            imagen = source.render(page_number, None, self._dpi)
            segunda = extract_student_page(
                lines_from_text(self._ocr.read(imagen).text), page_number
            )
        except Exception as error:  # noqa: BLE001
            logger.warning("falló el OCR de la página %s", page_number, exc_info=True)
            stats.failures[page_number] = explicar(error)
            stats.incomplete.append(page_number)
            return hoja, Provenance.TEXT_LAYER

        fundida = merge_pages(hoja, segunda)
        if not fundida.needs_review:
            stats.recovered_by_ocr += 1
        else:
            stats.incomplete.append(page_number)
        return fundida, Provenance.OCR_FULL_PAGE

    def _report(self, event: ProgressEvent) -> None:
        try:
            self._progress.emit(event)
        except Exception:  # noqa: BLE001 - la telemetría nunca rompe el trabajo
            logger.debug("el informe de progreso falló, se continúa", exc_info=True)
