"""Levantar el inventario de un documento sin partirlo.

Es la única opción para un libro empastado de registros de diplomas: nadie lo
va a desencuadernar. Se lee entero, se reconoce qué es, y lo único que queda
escrito es su FUID.
"""

from __future__ import annotations

from ...application.progress import Stage
from .planillas import _escribir_fuid
from .taller import Taller, _anunciar


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
