"""Levantar el inventario de un documento sin partirlo.

Dos maneras de no partir nada, y la diferencia está en qué se considera la
unidad documental.

`_inventory_job` lee un libro empastado de registros de diplomas -- nadie lo va
a desencuadernar -- y saca una fila por registro de dentro. `_inventory_file_job`
lee un PDF que **ya es** un documento y saca una sola fila: la del archivo. Los
dos dejan el original exactamente como llegó y los dos escriben sólo el FUID.

Confundirlos da los dos errores simétricos: un libro de cuatrocientos diplomas
anotado en un renglón, o una nota de ajuste de dos hojas repartida en doce.
"""

from __future__ import annotations

import logging

from ...application.progress import Stage
from .planillas import _escribir_fuid, _escribir_fuid_de_archivo
from .taller import Taller, _anunciar

logger = logging.getLogger(__name__)


def _inventory_job(payload: dict) -> dict:
    """Leer el documento y dejar sólo su FUID, con el original intacto."""
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...application.inventory_document import InventoryDocument
    from ...application.task import TaskKind

    taller = Taller.desde(payload)

    # 1. Leer: la misma cascada que parte resoluciones, puesta a reconocer
    #    registros. De ahí salen las filas del inventario.
    ocr = taller.ocr()
    use_case = InventoryDocument(
        ocr=ocr,
        pipeline=taller.pipeline(ocr),
        progress=taller.progress,
        control=taller.control,
    )
    source = PyMuPDFPageSource(taller.source, taller.name)
    try:
        outcome = use_case.execute(
            source, document_name=taller.name, ubicacion=taller.ubicacion()
        )
    finally:
        source.close()

    # Y aquí el desvío que evita el peor resultado posible de esta pantalla: un
    # trabajo que termina en verde sin haber escrito nada. Esta ruta sólo sabe
    # sacar filas de dentro de un libro de registros de la Universidad; cuando
    # el papel no es ninguno de los que reconoce -- una nota de ajuste, un
    # comprobante de egreso, cualquier PDF que ya es un documento -- devolvía
    # cero filas, y cero filas es un FUID que no se escribe. El operador pedía
    # "solo inventariar", veía las doce páginas pasar, y se quedaba sin
    # inventario y sin un motivo.
    #
    # Lo que se hace en su lugar es lo que el operador pidió, leído de la otra
    # manera: si el documento no se deja repartir en filas, el documento **es**
    # la fila. Es el mismo desvío que ya hace «Dividir en documentos» cuando no
    # reconoce el tipo, y por el mismo motivo.
    if not outcome.rows:
        logger.info(
            "%s: no se reconoció ningún registro que inventariar; se inventaría "
            "el archivo entero como una sola unidad documental",
            taller.name,
        )
        _anunciar(
            payload,
            Stage.IDENTIFYING,
            detail="sin registros reconocibles: se inventaría el archivo entero",
        )
        return _inventory_file_job(payload)

    report = outcome.as_dict()
    report["task"] = str(TaskKind.INVENTORY)

    # 2. La planilla: aquí no hay PDF que escribir, sólo el FUID.
    _escribir_fuid(
        report,
        outcome.rows,
        settings=taller.settings,
        destination=taller.destination,
        name=taller.name,
        document_type=outcome.document_type,
        control=taller.control,
        payload=payload,
    )
    _anunciar(payload, Stage.DONE)
    return report


def _inventory_file_job(payload: dict) -> dict:
    """Anotar el archivo entero en el inventario, sin abrirlo en pedazos.

    Una fila, la del PDF: su asunto, sus fechas extremas -- la más antigua y la
    más reciente que aparezcan en cualquiera de sus hojas -- y sus folios. No se
    escribe ningún PDF y el original no se toca.
    """
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...application.inventory_file import InventoryFile
    from ...application.task import TaskKind

    taller = Taller.desde(payload)

    source = PyMuPDFPageSource(taller.source, taller.name)
    try:
        outcome = InventoryFile(
            ocr=taller.ocr(),
            progress=taller.progress,
            control=taller.control,
        ).execute(
            source, document_name=taller.name, ubicacion=taller.ubicacion()
        )
    finally:
        source.close()

    report = outcome.as_dict()
    report["task"] = str(TaskKind.INVENTORY_FILE)

    _escribir_fuid_de_archivo(
        report,
        outcome.rows,
        settings=taller.settings,
        destination=taller.destination,
        name=taller.name,
        control=taller.control,
        payload=payload,
    )
    _anunciar(payload, Stage.DONE)
    return report
