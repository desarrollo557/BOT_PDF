"""Partir por registro leído: un folio de diplomas, un expediente de matrícula.

Una sola lectura para las dos salidas. Los registros que salen de leer el
documento son a la vez las filas del inventario y los grupos de páginas que
el escritor convierte en archivos.

Sirve a los dos tipos porque `InventoryDocument` ya devuelve la agrupación
hecha para ambos, y lo que queda por hacer -- escribir un PDF por grupo y, si
se pidió, el FUID -- no depende de cuál de los dos sea.
"""

from __future__ import annotations

from ...application.progress import Stage
from .planillas import _escribir_fuid, _escribir_planilla
from .taller import Taller, _anunciar


def _record_split_job(payload: dict, task) -> dict:
    """Un PDF por folio o por expediente, más el FUID si se pidió."""
    from ...adapters.pymupdf_assembler import PyMuPDFAssembler
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...application.entrega import Destino, entregar
    from ...application.inventory_document import InventoryDocument
    from ...domain.doctype import DocumentType

    taller = Taller.desde(payload)

    # 1. Decidir los grupos: leer el libro registro a registro. De la lectura
    #    sale ya la agrupación hecha -- un folio por cara, una persona por
    #    carátula -- y las filas del FUID.
    use_case = InventoryDocument(
        ocr=taller.ocr(),
        progress=taller.progress,
        control=taller.control,
        # Cuántas páginas se leen a la vez. Es el mismo ajuste con el que las
        # otras rutas reparten sus páginas, porque mide lo mismo: cuánto trabajo
        # de espera aguanta esta máquina a la vez.
        workers=int(taller.settings.get("page_workers") or 8),
    )
    source = PyMuPDFPageSource(taller.source, taller.name)
    try:
        outcome = use_case.execute(
            source, document_name=taller.name, ubicacion=taller.ubicacion()
        )
        # Qué clase de papel es cada folio o expediente, con la fuente todavía
        # abierta. Lo hace `entregar` más abajo, pero necesita el texto y la
        # fuente se cierra aquí, así que se le guarda el lector.
        agrupacion = outcome.grouping
        textos = (
            {p: source.text_of(p) for grupo in agrupacion.groups for p in grupo.page_numbers}
            if agrupacion is not None
            else {}
        )
    finally:
        source.close()

    report = outcome.as_dict()
    report["task"] = str(task)

    # 2. Entregar: el mismo tramo que las otras rutas -- describir, comprobar,
    #    escribir e inventariar. Lo que aquí cambia es cómo se llaman los
    #    archivos: sin prefijo y con el título dentro, porque la unidad de un
    #    libro de folios es un folio y la de un legajo de matrículas un
    #    expediente -- ninguna es una resolución -- y el título dice de quién
    #    es, que es lo que alguien va a buscar.
    #    "1128047041_juan-perez_DOCUMENTO-DE-IDENTIDAD.pdf" se lee sin abrirlo.
    #
    #    Sin heredar el tipo del vecino: en un legajo homogéneo -- un libro de
    #    folios es cien veces el mismo papel -- el contexto no aporta nada que
    #    no se supiera ya, y heredar sólo taparía los folios que no se dejaron
    #    leer.
    if task.writes_documents and agrupacion is not None:
        _anunciar(
            payload,
            Stage.ASSEMBLING,
            detail="preparando la escritura",
            done=0,
            total=len(agrupacion.groups),
        )
        entregado = entregar(
            agrupacion,
            origen=taller.source,
            nombre=taller.name,
            paginas=outcome.page_count,
            destino=Destino(directorio=taller.destination, entregado_en=taller.delivered_to),
            assembler=PyMuPDFAssembler(
                control=taller.control,
                progress=taller.progress,
                naming_prefix=None,
                # El nombre de un diploma es la cédula y el tipo, y nada más:
                # "7882907_DIPLOMA.pdf". Lo pidió así el operador y además es lo
                # que sale limpio -- el nombre del graduando y su título están
                # escritos a mano sobre un formulario impreso, y lo que el OCR
                # entrega mezcla los dos: "alberto-fernandez-pucela-le-expide-el
                # -presente-diploma-al". Un nombre de archivo con media leyenda
                # del formulario dentro no se busca ni se lee.
                #
                # Lo leído no se pierde: el graduando va a su columna del FUID,
                # que es donde se busca por texto, y la cédula del nombre basta
                # para encontrar el archivo en el disco.
                #
                # Un legajo de matrículas conserva el título, que ahí es el
                # nombre del expediente y llega impreso y limpio.
                con_titulo=outcome.document_type is not DocumentType.DIPLOMA,
                nombre=taller.name,
            ),
            en_revision=[
                int(item["page"]) for item in outcome.review_queue if item.get("page")
            ],
            estadisticas=report.get("stats") or {},
            texto_de=textos.get,
            heredar_tipo=False,
        )
        report["inventory"] = entregado.inventario.as_dict()
        report["outputs"] = entregado.salidas
        report["unwritable_pages"] = entregado.ilegibles

    # 3. Las planillas: el FUID si se pidió, y la misma planilla del documento
    #    para un libro de folios o un legajo de matrículas -- quien recibe la
    #    carpeta necesita el listado, se haya cortado como se haya cortado.
    if task.writes_inventory:
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
    _escribir_planilla(report, taller.destination, payload)

    _anunciar(payload, Stage.DONE)
    return report
