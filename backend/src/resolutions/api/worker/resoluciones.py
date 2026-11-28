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
    """Partir el documento en uno por resolución, y dejar su FUID si se pidió.

    El texto de las páginas da el asunto de cada resolución -- lo que ordena su
    RESUELVE --, que es a la vez el nombre de su PDF y su fila del FUID (el
    estándar único de la UdeC, 2026-11-27). Por eso la fuente se abre antes de
    escribir y se cierra al terminar, y las dos cosas lo piden a la misma
    función, ``asunto_del_grupo``: no pueden decir dos cosas distintas.
    """
    from ...adapters.pymupdf_source import PyMuPDFDocumentStore

    taller = Taller.desde(payload)
    fuente = PyMuPDFDocumentStore(taller.name).open(taller.source)
    try:
        return _partir_y_fichar(payload, task, taller, fuente)
    finally:
        fuente.close()


def _partir_y_fichar(payload: dict, task, taller: Taller, fuente) -> dict:
    """La división y el FUID de ``_split_job``, con la fuente de los asuntos abierta."""
    from ...adapters.file_inventory import FileInventoryStore
    from ...adapters.huellas_pdf import huellas_de
    from ...adapters.pymupdf_assembler import PyMuPDFAssembler
    from ...adapters.pymupdf_source import PyMuPDFDocumentStore
    from ...application.process_document import ProcessDocument
    from ...application.resolution_fuid import asunto_del_grupo

    # 1. Decidir los grupos: la cascada lee el número de cada página y el
    #    agrupador decide quién manda sobre quién. Lo demás -- describir,
    #    comprobar, escribir e inventariar -- lo hace el caso de uso por el
    #    mismo camino que las otras tres rutas.
    use_case = ProcessDocument(
        store=PyMuPDFDocumentStore(taller.name),
        pipeline=taller.pipeline(taller.ocr()),
        assembler=PyMuPDFAssembler(
            control=taller.control,
            nombre=taller.name,
            # Cada PDF se llama como su fila del FUID, con el orden delante:
            # «01_RESOLUCION 007-1998 - FIJAR LA FECHA….pdf».
            asunto_de=lambda grupo: asunto_del_grupo(grupo, fuente.text_of, nombre_del_archivo=taller.name),
            # Y recortado para caber en la carpeta a la que la corrida lo copia.
            entregado_en=taller.delivered_to,
        ),
        inventory=FileInventoryStore(),
        progress=taller.progress,
        control=taller.control,
        # Cada PDF escrito, vuelto a abrir y casado con el original.
        huellas=huellas_de,
        # Lo que el revisor deja fuera del margen, a la IA si se eligió.
        juez=taller.juez_de_costuras(),
    )
    resultado = use_case.execute(taller.source, taller.destination, source_name=taller.name)
    report = resultado.as_dict()
    report["task"] = str(task)

    # 2. Las planillas: el FUID sobre la misma lectura -- las páginas ya están
    #    agrupadas y no hace falta volver a abrir el documento -- y la planilla
    #    del documento, junto a los PDF. El revisor de fechas corre también al
    #    sólo dividir (2026-11-17): la planilla que va junto a los PDF lleva la
    #    fecha de cada resolución, y el operador pidió asegurarla «sin importar
    #    la habilidad». El FUID, sólo si se pidió.
    if task.writes_inventory or task.writes_documents:
        from ...application.fuid import con_los_archivos
        from ...application.resolution_fuid import filas_de_resoluciones
        from ...domain.fechas_extremas import EXPEDICION
        from .fechas_aseguradas import (
            asegurar_las_filas_del_fuid,
            juez_del_trabajo,
            regla_de,
        )

        archivos = (
            {item.first_page: item.file_name for item in resultado.inventory.items}
            if resultado.inventory is not None
            else {}
        )
        filas = filas_de_resoluciones(
            resultado.grouping.groups,
            nombre_del_archivo=taller.name,
            ubicacion=taller.ubicacion(),
            texto_de=fuente.text_of,
        )
        # El revisor de fechas (2026-11-10), con la fuente todavía abierta: la
        # fecha de cada resolución contra su fórmula «Dada en…», en el mismo
        # texto de sus páginas con que se fechó y se le leyó el asunto (la
        # fuente lo guarda: no se relee). La de la serie, que no está en su
        # papel, va a Revisión con su motivo.
        filas = asegurar_las_filas_del_fuid(
            report,
            filas,
            resultado.grouping.groups,
            fuente.text_of,
            regla=regla_de("resoluciones", EXPEDICION),
            juez=juez_del_trabajo(taller),
            # «Detener» entre una fila y la siguiente (2026-11-10).
            control=taller.control,
            archivos=archivos,
        )
        # Cada fila diciendo cómo se llama su archivo, cuando se escribió alguno.
        # El inventario y la carpeta son las dos mitades de la misma entrega, y
        # esto es lo que permite cruzarlas sin contar filas.
        if archivos:
            filas = con_los_archivos(filas, archivos)

        if task.writes_inventory:
            _escribir_fuid(
                report,
                filas,
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
