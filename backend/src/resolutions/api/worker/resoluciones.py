"""Partir un legajo de resoluciones: un número impreso manda hasta que aparece otro.

La ruta más antigua del sistema y la única que usa la cascada de lectura
entera -- capa de texto, OCR de la banda, OCR de la página, contexto y visión
-- porque lo único que distingue una resolución de la siguiente es justo el
número que hay que leer.
"""

from __future__ import annotations

from ...application.progress import Stage
from .planillas import _escribir_fuid, _escribir_planilla
from .taller import Taller, _anunciar


def _split_job(payload: dict, task) -> dict:
    """Partir el documento en uno por resolución, y dejar su FUID si se pidió."""
    from ...adapters.file_inventory import FileInventoryStore
    from ...adapters.pymupdf_assembler import PyMuPDFAssembler
    from ...adapters.pymupdf_source import PyMuPDFDocumentStore
    from ...application.process_document import ProcessDocument

    taller = Taller.desde(payload)

    # 1. Decidir los grupos: la cascada lee el número de cada página y el
    #    agrupador decide quién manda sobre quién. Lo demás -- describir,
    #    comprobar, escribir e inventariar -- lo hace el caso de uso por el
    #    mismo camino que las otras tres rutas.
    use_case = ProcessDocument(
        store=PyMuPDFDocumentStore(taller.name),
        pipeline=taller.pipeline(taller.ocr()),
        assembler=PyMuPDFAssembler(control=taller.control, nombre=taller.name),
        inventory=FileInventoryStore(),
        progress=taller.progress,
        control=taller.control,
    )
    resultado = use_case.execute(taller.source, taller.destination, source_name=taller.name)
    report = resultado.as_dict()
    report["task"] = str(task)

    # 2. Las planillas: el FUID sobre la misma lectura -- las páginas ya están
    #    agrupadas y no hace falta volver a abrir el documento -- y la planilla
    #    del documento, junto a los PDF.
    if task.writes_inventory:
        from ...application.resolution_fuid import filas_de_resoluciones

        _escribir_fuid(
            report,
            filas_de_resoluciones(
                resultado.grouping.groups,
                nombre_del_archivo=taller.name,
                ubicacion=taller.ubicacion(),
            ),
            settings=taller.settings,
            destination=taller.destination,
            name=taller.name,
            document_type=None,
            control=taller.control,
            payload=payload,
        )
    _escribir_planilla(report, taller.destination, payload)

    _anunciar(payload, Stage.DONE)
    return report
