from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Stage(StrEnum):
    """Milestones a document passes through, in order.

    Cada una existe porque tarda. Una etapa que nadie anuncia es un tramo en que
    la pantalla no sabe qué contestar a "¿qué está haciendo?", y un sistema que
    no contesta eso parece colgado aunque esté trabajando perfectamente.
    """

    OPENED = "opened"
    #: Averiguando de qué documento se trata. Cuesta una muestra de doce páginas
    #: y, en un escaneo sin capa de texto, doce pasadas de OCR: lo bastante para
    #: que el operador se pregunte si pasa algo.
    IDENTIFYING = "identifying"
    PAGE = "page"
    #: Contrastando con OCR las páginas que declaran un número. Es una página por
    #: resolución, no por página, pero en un documento de treinta resoluciones son
    #: treinta renderizados seguidos sin una sola página nueva que mostrar.
    VERIFYING = "verifying"
    GROUPING = "grouping"
    ASSEMBLING = "assembling"
    #: Escribiendo la planilla del inventario. Es lo último que hace un trabajo
    #: y tarda lo suyo, así que tiene que poder decirse: sin esta etapa, el
    #: sistema anunciaba "listo" y seguía trabajando varios segundos más.
    INVENTORYING = "inventorying"
    #: Dejando el resultado donde tiene que quedar: la ficha en el inventario
    #: durable, los archivos copiados a la carpeta de destino. Es lo último y es
    #: lo que corre después de que la barra de páginas llegue al 100 %, así que
    #: sin anunciarlo el trabajo parece terminado y quieto.
    DELIVERING = "delivering"
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
    #: Cuánto lleva hecho esta etapa y de cuánto. Aparte de ``page_number`` y
    #: ``page_count`` porque no todas las etapas cuentan páginas: escribir los
    #: PDF cuenta archivos y escribir el FUID cuenta filas, y llamar "página" a
    #: un archivo obligaría a la pantalla a saber en qué etapa está para
    #: entender el número.
    done: int | None = None
    total: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "stage": str(self.stage),
            "page_number": self.page_number,
            "page_count": self.page_count,
            "provenance": self.provenance,
            "code": self.code,
            "failed": self.failed,
            "detail": self.detail,
            "done": self.done,
            "total": self.total,
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
