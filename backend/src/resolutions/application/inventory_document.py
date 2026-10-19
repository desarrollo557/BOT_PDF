"""Levantar el inventario de un documento sin partirlo.

Es la otra cosa que se puede pedir del sistema. Un libro empastado de registro
de diplomas no se divide -- nadie va a desencuadernarlo -- pero sí hay que
saber qué contiene, folio por folio y graduando por graduando.

El primer paso no es leer los datos sino averiguar qué se está mirando: una
caja de escaneos trae resoluciones de rectoría y libros de diplomas mezclados, y
cada uno se inventaría con columnas distintas. Eso lo decide `domain.doctype`
sobre lo que está impreso en las páginas, nunca sobre el nombre del archivo.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..domain.diploma import CriterioDeCorte, DiplomaRecord
from ..domain.doctype import DocumentType, TypeVerdict, classify_pages
from ..domain.grouping import GroupingEngine, GroupingResult
from ..domain.matricula import StudentRecord
from ..domain.page import Provenance
from ..domain.validation import (
    Issue,
    Severity,
    summarise,
    validate_diplomas,
    validate_matriculas,
    validate_resolutions,
)
from .acta_fuid import filas_de_actas
from .acta_split import ActaSplit
from .control import NullRunControl, RunControl
from .diploma_fuid import filas_del_libro
from .diploma_split import group_by_record
from .fuid import FuidRow, Ubicacion
from .matricula_fuid import filas_de_expedientes
from .matricula_split import group_by_student
from .orquestador import MIN_SAMPLE_CHARS as MIN_SAMPLE_CHARS
from .orquestador import SAMPLE_PAGES, muestrear
from .pipeline import ClassificationPipeline
from .ports import OcrEngine, PageSource
from .progress import NullProgressReporter, ProgressEvent, ProgressReporter, Stage
from .read_diploma_book import LECTORES, BookReadingStats, ReadDiplomaBook
from .read_student_records import ReadStudentRecords, RecordsReadingStats
from .resolution_fuid import filas_de_resoluciones

logger = logging.getLogger(__name__)

# La muestra con que se reconoce el documento -- cuántas páginas, desde cuántos
# caracteres sirve la capa de texto -- vive con el orquestador, que es quien la
# usa para algo más que los marcadores. `SAMPLE_PAGES` y `MIN_SAMPLE_CHARS` se
# siguen pudiendo importar desde aquí, que es donde las busca quien ya las usaba.


@dataclass(slots=True)
class InventoryOutcome:
    """Lo que se averiguó del documento, y las filas que produce."""

    document: str
    page_count: int
    verdict: TypeVerdict
    rows: list[FuidRow] = field(default_factory=list)
    records: list[DiplomaRecord] = field(default_factory=list)
    #: Los expedientes académicos, cuando el documento resultó ser un legajo de
    #: matrículas. Van aparte de ``records`` y no en su lugar porque no son la
    #: misma cosa: un registro de diploma es una página y un expediente son
    #: todas las hojas de un estudiante.
    students: list[StudentRecord] = field(default_factory=list)
    reading: BookReadingStats | RecordsReadingStats | None = None
    #: Qué páginas forman cada unidad documental. Se devuelve para que escribir
    #: los PDF no obligue a leer el documento por segunda vez.
    grouping: GroupingResult | None = None
    #: Lo que la comprobación encontró. Ni una sola de estas cosas se corrige
    #: sola: se señalan, y quien firma decide.
    issues: list[Issue] = field(default_factory=list)
    #: De qué peldaño salió cada página, contado por la rama que la leyó. Cada
    #: tipo de documento lo sabe de una forma distinta -- el libro de folios lo
    #: cuenta en su lector, las resoluciones en la clasificación de cada página
    #: -- y esto es donde las tres formas se encuentran.
    provenance: dict[str, int] = field(default_factory=dict)
    #: Las páginas que se leyeron, cuando no fue el documento entero: retomar
    #: una entrega a medias lee sólo las que faltan en el destino. ``None`` es
    #: el documento entero.
    paginas: tuple[int, ...] | None = None

    @property
    def paginas_leidas(self) -> list[int]:
        """Las páginas de las que esta lectura responde: las que cuadran la entrega."""
        return list(self.paginas) if self.paginas else list(range(1, self.page_count + 1))

    @property
    def incidents(self) -> list[str]:
        """Los hallazgos como los lee el operador, con la página delante."""
        return [issue.describe() for issue in self.issues]

    @property
    def document_type(self) -> DocumentType:
        return self.verdict.document_type

    @property
    def review_queue(self) -> list[dict[str, object]]:
        """Las páginas que alguien tiene que mirar, con el motivo de cada una.

        Sale de los mismos hallazgos que ya se comprobaron, agrupados por página
        para que la pantalla no tenga que contarlos. Un hallazgo sin página --
        "faltan tres folios entre el 812 y el 816" -- es del documento entero y
        no de ninguna hoja, así que no entra en esta cola.
        """
        motivos: dict[int, list[str]] = {}
        for issue in self.issues:
            # Sólo lo que pesa como error. Los avisos -- un campo que no se
            # leyó, un folio repetido -- están en el informe y en el FUID, pero
            # no traen a nadie a abrir la página: una cola donde está todo no
            # señala nada.
            if issue.page_number and issue.severity is Severity.ERROR:
                motivos.setdefault(issue.page_number, []).append(issue.reason)
        return [
            {"page": pagina, "reason": "; ".join(razones)}
            for pagina, razones in sorted(motivos.items())
        ]

    def as_dict(self) -> dict[str, object]:
        grupos = self.grouping.groups if self.grouping else []
        return {
            "document": self.document,
            "page_count": self.page_count,
            **({"paginas": list(self.paginas)} if self.paginas else {}),
            "document_type": str(self.document_type),
            "document_type_label": self.document_type.label,
            "type_confidence": round(self.verdict.confidence, 4),
            "records": len(self.rows),
            "reading": self.reading.as_dict() if self.reading else None,
            "validation": summarise(self.issues),
            "issues": [issue.as_dict() for issue in self.issues],
            "incidents": self.incidents,
            # -----------------------------------------------------------------
            #  Lo que la pantalla espera de cualquier informe
            # -----------------------------------------------------------------
            #  Un informe de inventario traía otras claves que uno de división,
            #  y la pantalla, que sólo conocía las de división, se rompía entera
            #  al terminar un libro de diplomas: sin modal de cierre y con la
            #  barra de navegación caída. Ninguno de estos valores se inventa
            #  -- todos salen de lo que este mismo trabajo midió -- y estar aquí
            #  es lo que permite que una sola pantalla sirva a los dos.
            "groups": [
                {
                    "code": grupo.code.value,
                    "title": grupo.title,
                    "pages": list(grupo.page_numbers),
                    "size": grupo.size,
                }
                for grupo in grupos
            ],
            "quarantine": list(self.grouping.quarantine) if self.grouping else [],
            "repairs": [
                {
                    "page": arreglo.page_number,
                    "observed": arreglo.observed.value,
                    "applied": arreglo.applied.value,
                    "distance": arreglo.distance,
                }
                for arreglo in (self.grouping.repairs if self.grouping else [])
            ],
            "review_queue": self.review_queue,
            # Un trabajo de inventario no escribe ningún PDF. Quien sí los
            # escribe -- la división de un libro de folios -- sobrescribe esta
            # clave con los nombres reales de lo que dejó en disco.
            "outputs": [],
            "stats": self._stats(),
        }

    def _stats(self) -> dict[str, object]:
        """El coste de la lectura, medido y no supuesto.

        El modelo de visión no interviene en ninguna de estas ramas: ni un libro
        de folios ni un legajo de matrículas lo consultan. El cero, por tanto, no
        es un hueco rellenado sino lo que realmente ocurrió.
        """
        fallos: dict[str, str] = {}
        if self.reading is not None:
            fallos = {str(p): e for p, e in self.reading.failures.items()}
        return {
            "by_provenance": dict(self.provenance),
            "escalated": sum(
                cantidad
                for peldano, cantidad in self.provenance.items()
                if peldano != str(Provenance.TEXT_LAYER)
            ),
            "vision_requests": 0,
            "resolved_by_context": 0,
            "vision_page_ratio": 0.0,
            "failed_pages": fallos,
            "document_type": str(self.document_type),
            "type_confidence": round(self.verdict.confidence, 4),
        }


class InventoryDocument:
    """Lee un documento y devuelve sus filas de inventario. No escribe PDF."""

    def __init__(
        self,
        ocr: OcrEngine | None = None,
        pipeline: ClassificationPipeline | None = None,
        grouping: GroupingEngine | None = None,
        progress: ProgressReporter | None = None,
        control: RunControl | None = None,
        workers: int = LECTORES,
        criterio: CriterioDeCorte = CriterioDeCorte.PAGINA,
        rastreo=None,
        mosaico=None,
        mosaico_de_cedulas=None,
        mosaico_de_fechas=None,
        lectura_de_ahorro: bool = False,
        mistral_summary=None,  # MistralSummaryAdapter para resúmenes de actas
    ) -> None:
        self._ocr = ocr
        self._pipeline = pipeline
        self._grouping = grouping or GroupingEngine()
        self._progress = progress or NullProgressReporter()
        self._control = control or NullRunControl()
        #: Cuántas páginas se leen a la vez. Leer un libro es esperar al
        #: proveedor de OCR, no calcular, así que este número es el que decide
        #: si un libro de 398 páginas tarda veinte minutos o tres.
        self._workers = max(1, workers)
        #: Con qué señal se corta un libro de diplomas. Viaja desde la
        #: pantalla porque es una decisión del operador sobre su papel, no
        #: del servicio: un libro foliado hoja a hoja y uno donde cada
        #: graduado ocupa varias caras se parten por cosas distintas.
        self._criterio = criterio
        #: Quién rastrea localmente una cédula que la lectura normal dejó
        #: escapar, antes de que llegue a pagarse.
        self._rastreo = rastreo
        #: Quien lee los nombres de varias caras en una sola imagen, cuando
        #: el operador eligió pagar por la franja y no por la hoja.
        self._mosaico = mosaico
        self._mosaico_de_cedulas = mosaico_de_cedulas
        self._mosaico_de_fechas = mosaico_de_fechas
        self._lectura_de_ahorro = lectura_de_ahorro
        #: Adaptador para generar resúmenes de actas con Mistral
        self._mistral_summary = mistral_summary

    def execute(
        self,
        source: PageSource,
        *,
        document_name: str,
        ubicacion: Ubicacion | None = None,
        first_order: int = 1,
        declarado: DocumentType | None = None,
        paginas: Sequence[int] | None = None,
    ) -> InventoryOutcome:
        """Reconoce el documento y lo lee con la rama de su tipo.

        ``paginas`` lee sólo esas páginas, conservando su número. Sólo lo sabe
        hacer el libro de diplomas, que es la habilidad que retoma entregas a
        medias; las demás leen siempre el documento entero.
        """
        if paginas and declarado is not DocumentType.DIPLOMA:
            raise ValueError("sólo un libro de diplomas se puede leer por páginas sueltas")
        self._report(ProgressEvent(stage=Stage.OPENED, page_count=source.page_count))
        if declarado is not None:
            # Lo que el operador dijo que está cargando manda, y no se comprueba
            # contra una muestra: la muestra cuesta doce páginas -- doce pasadas
            # de OCR en un escaneo --, y cuando se equivoca condena el libro
            # entero a la ruta que no sabe cortarlo. Quien tiene el papel
            # delante sabe lo que es; el despachador ya lo dio por bueno, y
            # volver a preguntárselo al papel aquí era la segunda muestra del
            # mismo trabajo.
            verdict = TypeVerdict(document_type=declarado, confidence=1.0)
            self._report(
                ProgressEvent(
                    stage=Stage.IDENTIFYING,
                    done=SAMPLE_PAGES,
                    total=SAMPLE_PAGES,
                    detail=f"{declarado.label}, declarado por el operador",
                )
            )
        else:
            # Reconocer el documento cuesta una muestra de doce páginas y, en un
            # escaneo sin capa de texto, doce pasadas de OCR. Ocurre antes de la
            # primera página, así que callarlo deja la pantalla en blanco justo
            # al arrancar, que es cuando el operador está mirando.
            self._report(
                ProgressEvent(
                    stage=Stage.IDENTIFYING,
                    done=0,
                    total=SAMPLE_PAGES,
                    detail="reconociendo de qué documento se trata",
                )
            )
            verdict = self.identify(source)
            self._report(
                ProgressEvent(
                    stage=Stage.IDENTIFYING,
                    done=SAMPLE_PAGES,
                    total=SAMPLE_PAGES,
                    detail=verdict.document_type.label,
                )
            )

        if verdict.document_type is DocumentType.DIPLOMA:
            return self._diplomas(
                source, verdict, document_name, ubicacion, first_order, paginas
            )
        if verdict.document_type is DocumentType.RESOLUCION:
            return self._resoluciones(source, verdict, document_name, ubicacion, first_order)
        if verdict.document_type is DocumentType.MATRICULA:
            return self._matriculas(
                source, verdict, document_name, ubicacion, first_order
            )
        if verdict.document_type is DocumentType.ACTA:
            return self._actas(source, verdict, document_name, ubicacion, first_order)

        # Ni una cosa ni la otra. No se inventa una lectura: se dice que no se
        # reconoció y el documento queda a la espera de que alguien lo mire.
        outcome = InventoryOutcome(
            document=document_name,
            page_count=source.page_count,
            verdict=verdict,
            issues=[
                Issue(
                    field="tipo",
                    reason=(
                        "no se reconoció el tipo de documento, así que no se "
                        "generaron filas"
                    ),
                    severity=Severity.ERROR,
                )
            ],
        )
        return outcome

    # -- qué documento es -----------------------------------------------------

    def identify(self, source: PageSource) -> TypeVerdict:
        """Decide el tipo mirando una muestra de páginas repartidas."""
        return classify_pages(self._sample(source))

    def _sample(self, source: PageSource) -> list[tuple[int, str]]:
        # Doce páginas repartidas, por su capa de texto o, en un escaneo, por la
        # banda superior: la misma muestra que mira el orquestador, sacada por
        # la misma función para que los dos no puedan ver cosas distintas.
        return muestrear(source, self._ocr)

    # -- libros de diplomas ---------------------------------------------------

    def _diplomas(
        self,
        source: PageSource,
        verdict: TypeVerdict,
        document_name: str,
        ubicacion: Ubicacion | None,
        first_order: int,
        paginas: Sequence[int] | None = None,
    ) -> InventoryOutcome:
        lector = ReadDiplomaBook(
            ocr=self._ocr,
            progress=self._progress,
            control=self._control,
            workers=self._workers,
            criterio=self._criterio,
            rastreo=self._rastreo,
            mosaico=self._mosaico,
            mosaico_de_cedulas=self._mosaico_de_cedulas,
            mosaico_de_fechas=self._mosaico_de_fechas,
            lectura_de_ahorro=self._lectura_de_ahorro,
        )
        records, stats = lector.execute(source, paginas)

        rows = filas_del_libro(
            records,
            nombre_del_archivo=document_name,
            ubicacion=ubicacion,
            desde=first_order,
            criterio=self._criterio,
        )

        return InventoryOutcome(
            document=document_name,
            page_count=source.page_count,
            verdict=verdict,
            rows=rows,
            records=records,
            reading=stats,
            provenance=dict(stats.provenance),
            # Un libro de folios se parte casi uno a uno: cada cara es un
            # registro terminado. La excepción es la cara que no trae ningún
            # identificador, que es la vuelta de la hoja anterior y se archiva
            # con ella -- la misma decisión que toman las filas del FUID, para
            # que el inventario y la carpeta cuenten lo mismo.
            grouping=group_by_record(records, self._criterio, por_pagina=bool(paginas)),
            issues=validate_diplomas(records, self._criterio),
            paginas=tuple(r.page_number for r in records) if paginas else None,
        )

    # -- expedientes académicos -----------------------------------------------

    def _matriculas(
        self,
        source: PageSource,
        verdict: TypeVerdict,
        document_name: str,
        ubicacion: Ubicacion | None,
        first_order: int,
    ) -> InventoryOutcome:
        """Inventariar un legajo de matrículas: una fila por estudiante.

        No se parece a ninguno de los otros dos. Una resolución se agrupa por su
        número, un libro de folios no se agrupa en absoluto, y aquí la unidad
        documental es la persona: la carátula de matrícula y las hojas de
        registro de estudios que la siguen son un solo expediente y una sola
        fila, con tantos folios como hojas.
        """
        lector = ReadStudentRecords(
            ocr=self._ocr, progress=self._progress, control=self._control
        )
        expedientes, stats = lector.execute(source)

        rows = filas_de_expedientes(
            expedientes,
            nombre_del_archivo=document_name,
            ubicacion=ubicacion,
            desde=first_order,
        )

        return InventoryOutcome(
            document=document_name,
            page_count=source.page_count,
            verdict=verdict,
            rows=rows,
            students=expedientes,
            reading=stats,
            provenance=dict(stats.provenance),
            grouping=group_by_student(expedientes),
            issues=validate_matriculas(expedientes),
        )

    # -- resoluciones ---------------------------------------------------------

    def _resoluciones(
        self,
        source: PageSource,
        verdict: TypeVerdict,
        document_name: str,
        ubicacion: Ubicacion | None,
        first_order: int,
    ) -> InventoryOutcome:
        """Inventariar sin partir: se agrupa igual, pero no se escribe nada.

        La agrupación es la que decide qué es una unidad documental, así que
        hace falta aunque no vaya a salir ningún PDF de ella.
        """
        if self._pipeline is None:
            raise ValueError(
                "para inventariar resoluciones hace falta la cascada de clasificación"
            )

        classifications, _ = self._pipeline.classify(source)
        self._report(ProgressEvent(stage=Stage.GROUPING, page_count=source.page_count))
        result = self._grouping.group(classifications)
        result.verify_integrity(total_pages=source.page_count)

        rows = filas_de_resoluciones(
            result.groups,
            nombre_del_archivo=document_name,
            ubicacion=ubicacion,
            desde=first_order,
        )

        # La procedencia de una resolución la sabe la clasificación de cada
        # página, que es quien recorrió la cascada. Se cuenta aquí porque el
        # inventario no guarda las clasificaciones, sólo la agrupación.
        procedencia: dict[str, int] = {}
        for pagina in classifications:
            clave = str(pagina.provenance)
            procedencia[clave] = procedencia.get(clave, 0) + 1

        return InventoryOutcome(
            document=document_name,
            page_count=source.page_count,
            verdict=verdict,
            rows=rows,
            provenance=procedencia,
            grouping=result,
            issues=validate_resolutions(classifications, result),
        )

    # -- actas de grado --------------------------------------------------------

    def _actas(
        self,
        source: PageSource,
        verdict: TypeVerdict,
        document_name: str,
        ubicacion: Ubicacion | None,
        first_order: int,
    ) -> InventoryOutcome:
        """Inventariar actas de grado: una fila por acta."""
        if self._ocr is None:
            raise ValueError("para inventariar actas hace falta OCR (Tesseract + Mistral)")

        split = ActaSplit(
            ocr=self._ocr,
            mistral_summary=self._mistral_summary,
            progress=self._progress,
            control=self._control,
            workers=self._workers,
        )
        result = split.execute(source, document_name=document_name, ubicacion=ubicacion)

        # Convertir ActaSplitResult a InventoryOutcome
        rows = filas_de_actas(
            result.actas,
            nombre_del_archivo=document_name,
            ubicacion=ubicacion,
        )

        return InventoryOutcome(
            document=document_name,
            page_count=result.page_count,
            verdict=verdict,
            rows=rows,
            issues=result.issues,
        )

    # -- telemetría -----------------------------------------------------------

    def _report(self, event: ProgressEvent) -> None:
        try:
            self._progress.emit(event)
        except Exception:  # noqa: BLE001
            logger.debug("el informe de progreso falló, se continúa", exc_info=True)


#: Las plantillas que viajan con el programa, una por tipo de documento.
#:
#: No son formatos distintos -- las dos son el FO-GD-008 -- sino el mismo
#: formato con la cabecera de su oficina productora ya puesta. Un libro de
#: diplomas lo produce la Secretaría General, y decirlo en cada entrega a mano
#: es una forma de que un día no se diga.
#:
#: La plantilla de diplomas es **sólo** para los PDF que resultaron ser
#: diplomas. Los demás tipos van a la genérica aunque salgan de la misma caja:
#: el inventario de diplomas es una entrega con su propia cabecera y su propio
#: objeto, y meterle dentro los expedientes de un legajo de matrículas lo
#: convertiría en dos inventarios pegados sin que nadie lo note.
_PLANTILLAS = {
    DocumentType.DIPLOMA: "fuid-diplomas.xlsx",
    DocumentType.RESOLUCION: "fuid-fo-gd-008.xlsx",
    # Las actas de grado: el FO-GD-008, una fila por graduado. Su fila guía
    # dice «nombre - título», «cédula», «upd»: es el formato de este inventario.
    DocumentType.ACTA: "fuid-fo-gd-008.xlsx",
}
_PLANTILLA_GENERICA = "fuid-fo-gd-008.xlsx"


def template_for(document_type: DocumentType) -> Path:
    """La plantilla que le corresponde a este tipo de documento.

    Siempre devuelve una que existe: un inventario que no se puede escribir
    porque nadie configuró una ruta es una función que no existe.
    """
    assets = Path(__file__).resolve().parents[1] / "assets"
    return assets / _PLANTILLAS.get(document_type, _PLANTILLA_GENERICA)


def default_template() -> Path:
    """La plantilla genérica, para cuando no se sabe qué documento es."""
    return template_for(DocumentType.DESCONOCIDO)


#: Los formatos de inventario que el sistema sabe rellenar, por su código. Son
#: formatos de clientes distintos y no versiones de uno solo: FO-GD-008 es el de
#: la Universidad, con dieciocho columnas y bloque de firmas al pie, y F-PSD-001
#: el de una empresa, con veintisiete y sin cabecera aparte. Cada uno lo escribe
#: su propio adaptador, porque lo único que comparten es el instructivo.
FORMATO_UNIVERSIDAD = "fo-gd-008"
FORMATO_PSD001 = "f-psd-001"

_FORMATOS = {
    FORMATO_UNIVERSIDAD: "fuid-fo-gd-008.xlsx",
    FORMATO_PSD001: "fuid-f-psd-001.xlsx",
    "diplomas": "fuid-diplomas.xlsx",
}


def template_named(formato: str | None) -> Path | None:
    """La plantilla de un formato pedido por su código, o ``None`` si no existe.

    ``None`` y no una excepción: que alguien escriba mal el código de un formato
    en los ajustes no debe dejar sin inventario un trabajo que ya se leyó. Quien
    llama se queda con la plantilla que le tocaba por tipo de documento.
    """
    if not formato:
        return None
    archivo = _FORMATOS.get(str(formato).strip().lower())
    if archivo is None:
        return None
    return Path(__file__).resolve().parents[1] / "assets" / archivo
