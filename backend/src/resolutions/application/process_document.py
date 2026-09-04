from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..domain.grouping import GroupingEngine, GroupingResult
from ..domain.page import PageClassification
from ..domain.validation import summarise, validate_resolutions
from .control import NullRunControl, RunControl
from .diagnostico import explicar
from .inventory import Inventory, build_inventory
from .pipeline import ClassificationPipeline, PipelineStats
from .ports import DocumentAssembler, DocumentStore, InventoryStore
from .progress import NullProgressReporter, ProgressEvent, ProgressReporter, Stage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """Una página que alguien tiene que mirar.

    Empezó siendo sólo lo que la máquina se negaba a adivinar -- una página sin
    número antes de ella, una que no se pudo leer -- y eso dejaba fuera el caso
    que más daño hace: la página que sí se leyó, y se leyó mal. Sobre el libro
    00072-00094 de la Universidad la cola decía siete páginas mientras seis
    resoluciones inventadas se habían escrito ya en el disco con números
    copiados del cuerpo del texto.

    Así que aquí llega todo aquello de lo que el sistema tiene constancia de que
    pudo salir torcido, se haya recuperado o no. Cada motivo se escribe para que
    la pantalla pueda agruparlos: no es lo mismo "hay que decidir a qué
    resolución pertenece esta página" que "el PDF de origen viene defectuoso y
    aquí se leyó de la imagen".
    """

    page_number: int
    reason: str


@dataclass(frozen=True, slots=True)
class ProcessingReport:
    document: Path
    page_count: int
    grouping: GroupingResult
    classifications: list[PageClassification]
    #: What the operator called the file, which is not what it is stored as.
    #: Uploads land on disk under a generated name; an inventory recording that
    #: name cannot answer which document a resolution came from.
    document_name: str | None = None
    outputs: list[Path] = field(default_factory=list)
    review_queue: list[ReviewItem] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)
    inventory: Inventory | None = None
    inventory_path: Path | None = None

    @property
    def issues(self):
        return validate_resolutions(self.classifications, self.grouping)

    def as_dict(self) -> dict[str, object]:
        return {
            "document": self.document_name or self.document.name,
            "page_count": self.page_count,
            "groups": [
                {
                    "code": group.code.value,
                    "title": group.title,
                    "pages": group.page_numbers,
                    "size": group.size,
                }
                for group in self.grouping.groups
            ],
            "quarantine": self.grouping.quarantine,
            "repairs": [
                {
                    "page": repair.page_number,
                    "observed": repair.observed.value,
                    "applied": repair.applied.value,
                    "distance": repair.distance,
                }
                for repair in self.grouping.repairs
            ],
            "review_queue": [
                {"page": item.page_number, "reason": item.reason} for item in self.review_queue
            ],
            "outputs": [path.name for path in self.outputs],
            "stats": self.stats,
            # Lo que la comprobación encontró en la lectura. Va en el informe de
            # la división igual que en el del inventario: partir bien un
            # documento que se leyó mal produce archivos correctos con el
            # nombre equivocado, que es la peor de las salidas.
            "validation": summarise(self.issues),
            "issues": [issue.as_dict() for issue in self.issues],
            "inventory": self.inventory.as_dict() if self.inventory else None,
        }


class ProcessDocument:
    """Read a PDF, decide who owns every page, and write one file per resolution."""

    def __init__(
        self,
        store: DocumentStore,
        pipeline: ClassificationPipeline,
        assembler: DocumentAssembler,
        grouping: GroupingEngine | None = None,
        inventory: InventoryStore | None = None,
        progress: ProgressReporter | None = None,
        sheets: object | None = None,
        control: RunControl | None = None,
    ) -> None:
        self._store = store
        self._pipeline = pipeline
        self._assembler = assembler
        self._grouping = grouping or GroupingEngine()
        self._inventory = inventory
        self._progress = progress or NullProgressReporter()
        self._control = control or NullRunControl()
        #: Writes the per-document delivery note. Optional: a missing spreadsheet
        #: library must not stop a document from being split.
        self._sheets = sheets

    def execute(
        self,
        document: Path,
        destination: Path,
        source_name: str | None = None,
        operator: str | None = None,
    ) -> ProcessingReport:
        """Split ``document`` into ``destination``.

        ``source_name`` is what the operator called the file. Uploads land on
        disk under a generated name, and an inventory that records that name
        instead of theirs cannot answer the only question it exists for: which
        document did this resolution come from.
        """
        name = source_name or document.name
        source = self._store.open(document)
        try:
            classifications, stats = self._pipeline.classify(source)

            self._report(ProgressEvent(stage=Stage.GROUPING, page_count=source.page_count))
            result = self._grouping.group(classifications)

            # Nothing is written until the page accounting balances. A partial
            # split is the one failure mode nobody would catch by eye.
            result.verify_integrity(total_pages=source.page_count)

            # Última oportunidad de parar antes de escribir: a partir de aquí
            # empiezan a aparecer archivos en la carpeta de destino.
            self._control.check()
            self._report(
                ProgressEvent(stage=Stage.ASSEMBLING, page_count=len(result.groups))
            )
            assembly = self._assembler.write(document, result, destination)
            outputs = list(assembly.outputs)
            review_queue = self._build_review_queue(
                classifications, result, stats, assembly.unwritable_pages
            )

            inventory = build_inventory(
                source_document=name,
                source_pages=source.page_count,
                result=result,
                review_pages=[item.page_number for item in review_queue],
                stats=self._describe(stats),
                file_names=assembly.written,
            )
            inventory_path = (
                self._inventory.write(inventory, destination) if self._inventory else None
            )

            report = ProcessingReport(
                document=document,
                document_name=name,
                page_count=source.page_count,
                grouping=result,
                classifications=classifications,
                outputs=outputs,
                review_queue=review_queue,
                stats=self._describe(stats),
                inventory=inventory,
                inventory_path=inventory_path,
            )
            # The delivery note, written beside the PDFs it describes. It needs
            # the finished report -- the page reconciliation, the review queue,
            # the cascade histogram -- so it is written here and not by the
            # inventory store, which only sees the item list.
            if self._sheets is not None:
                try:
                    self._sheets.write(
                        report.as_dict(),
                        destination,
                        operator=operator,
                        processed_at=datetime.now(UTC).isoformat(),
                    )
                except Exception:  # noqa: BLE001 - the split succeeded either way
                    logger.warning("could not write the inventory sheet", exc_info=True)

            self._report(ProgressEvent(stage=Stage.DONE, page_count=source.page_count))
            return report
        except Exception as error:  # noqa: BLE001 - re-raised after reporting
            self._report(
                ProgressEvent(
                    stage=Stage.FAILED,
                    failed=True,
                    detail=explicar(error),
                )
            )
            raise
        finally:
            source.close()

    def _report(self, event: ProgressEvent) -> None:
        try:
            self._progress.emit(event)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _build_review_queue(
        classifications: list[PageClassification],
        result: GroupingResult,
        stats: PipelineStats,
        unwritable_pages: dict[int, str] | None = None,
    ) -> list[ReviewItem]:
        # Reasons are shown to the operator verbatim, so they are written in the
        # language of the people who read them.
        quarantined = set(result.quarantine)
        items = [
            ReviewItem(page_number=page, reason="sin código de resolución antes de esta página")
            for page in result.quarantine
        ]
        items += [
            ReviewItem(page_number=page, reason=f"la página no pudo procesarse: {error}")
            for page, error in stats.failures.items()
            if page not in quarantined
        ]
        failed = set(stats.failures)
        # Sólo se llama a alguien cuando hay números que decidir.
        #
        # Una página que no se dejó leer no trae ningún número, así que no hay
        # ningún conflicto que resolver: hereda la resolución que venía abierta,
        # y en un expediente foliado a mano eso no es una suposición. El orden
        # de las páginas es el orden de los folios, de modo que una página sin
        # identificador entre el folio de una resolución y el siguiente
        # pertenece a esa resolución. Es la regla del archivo, dicha por el
        # operador: "si la página 1 tiene resolución y la página 2 es una
        # factura o una imagen sin texto y el folio es el 2, ya sabemos que
        # pertenece al pdf de la página 1".
        #
        # Las cinco que el libro 00072-00094 dejaba en revisión eran justo eso
        # -- la fotografía de un recibo de consignación de Davivienda mandado
        # por WhatsApp, dos comprobantes de pago del BBVA -- y la pantalla las
        # acusaba de "códigos de resolución en conflicto" cuando no traían ni un
        # número. Una cola llena de anexos correctamente archivados es una cola
        # que nadie mira.
        items += [
            ReviewItem(
                page_number=page.page_number,
                reason="códigos de resolución en conflicto en la página",
            )
            for page in classifications
            if page.ambiguous
            and page.code is not None
            and page.page_number not in quarantined
            and page.page_number not in failed
        ]
        # A page the writer could not copy is the one review reason the operator
        # cannot infer from the output: the file exists and simply has less in it.
        items += [
            ReviewItem(
                page_number=page,
                reason=f"la página no pudo copiarse al PDF de salida: {error}",
            )
            for page, error in (unwritable_pages or {}).items()
        ]

        # Las páginas cuya capa de texto no correspondía a lo impreso NO entran
        # aquí, aunque la cuenta de ellas siga en el informe.
        #
        # Se probó a meterlas y estaba mal. En estos expedientes una capa de
        # texto que no se deja leer casi nunca es un defecto: es un anexo
        # escaneado -- un correo, un formato, la fotografía de una cédula -- o
        # la vuelta de un folio, que el archivo escanea por las dos caras y
        # marca con una "v" en la foliación a mano de la esquina superior
        # derecha. Son diecinueve páginas de doscientas veintidós en el libro
        # 00072-00094, todas normales, y ponerlas en la cola entierra las que
        # de verdad necesitan que alguien las mire.
        #
        # Una página sin identificador no es un problema por sí sola: pertenece
        # a la resolución que venía abierta y ahí es donde se archiva.
        return sorted(items, key=lambda item: item.page_number)

    @staticmethod
    def _describe(stats: PipelineStats) -> dict[str, object]:
        return stats.as_dict()
