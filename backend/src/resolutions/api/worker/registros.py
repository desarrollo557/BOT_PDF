"""Partir por registro leído: un folio de diplomas, un expediente de matrícula.

Una sola lectura para las dos salidas. Los registros que salen de leer el
documento son a la vez las filas del inventario y los grupos de páginas que
el escritor convierte en archivos.

Sirve a los dos tipos porque `InventoryDocument` ya devuelve la agrupación
hecha para ambos, y lo que queda por hacer -- escribir un PDF por grupo y, si
se pidió, el FUID -- no depende de cuál de los dos sea.
"""

from __future__ import annotations

import logging

from ...application.progress import Stage
from .planillas import _escribir_fuid, _escribir_planilla
from .taller import Taller, _anunciar

logger = logging.getLogger(__name__)


def _record_split_job(payload: dict, task, tipo=None) -> dict:
    """Un PDF por folio o por expediente, más el FUID si se pidió.

    ``tipo`` es lo que ya se sabe del documento -- declarado por el operador o
    reconocido por el despachador --, para que la lectura no vuelva a
    muestrearlo. ``None`` es no saber nada, y entonces se reconoce.
    """
    from ...adapters.pymupdf_assembler import PyMuPDFAssembler
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...application.diploma_fuid import con_los_archivos
    from ...application.entrega import Destino, entregar
    from ...application.inventory_document import InventoryDocument

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
        criterio=taller.criterio(),
        # La segunda mirada local a la cédula, que corre entre la lectura
        # normal y la IA: lo que recupere aquí no llega a pagarse.
        rastreo=taller.rastreo(),
        # Y, si el operador eligió la lectura de ahorro, quien lee los
        # nombres en mosaico: diez caras por página facturada.
        mosaico=taller.mosaico(),
        # Y la repesca de la cédula en franjas, para lo que la lectura
        # entera deje sin ella.
        mosaico_de_cedulas=taller.mosaico_de_cedulas(),
        lectura_de_ahorro=taller.lectura_de_ahorro(),
        # Resúmenes de actas con Mistral
        mistral_summary=taller.mistral_summary(),
    )
    source = PyMuPDFPageSource(taller.source, taller.name)
    try:
        outcome = use_case.execute(
            source, document_name=taller.name, ubicacion=taller.ubicacion(), declarado=tipo
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
    _dejar_las_lecturas(outcome, taller.destination)
    # Las filas del inventario tal como salieron de la lectura. Si además se
    # escriben los archivos, más abajo se les añade el nombre de cada uno.
    filas = outcome.rows

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
                # La identidad debe quedar visible en el archivo: la cédula si
                # existe y, cuando no, el nombre del graduado. Para un diploma,
                # el título del grupo empieza por el nombre de la persona.
                con_titulo=True,
                mayusculas=True,
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
        # Y con los archivos ya escritos, se les pone el nombre a las filas del
        # inventario. Hasta este punto no se podía: la fila se arma al leer el
        # libro y el nombre del archivo no existe hasta que el escritor
        # terminó de partirlo. Quien recibe la carpeta puede entonces leer una
        # fila del FUID y saber qué PDF abrir, sin contar filas.
        filas = con_los_archivos(
            filas,
            {item.first_page: item.file_name for item in entregado.inventario.items},
        )

    # 3. Las planillas: el FUID si se pidió, y la misma planilla del documento
    #    para un libro de folios o un legajo de matrículas -- quien recibe la
    #    carpeta necesita el listado, se haya cortado como se haya cortado.
    if task.writes_inventory:
        _escribir_fuid(
            report,
            filas,
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


#: Cómo se llama el archivo con lo que el motor de pago contestó de cada cara.
LECTURAS_IA = "_lecturas-ia.jsonl"


def _dejar_las_lecturas(outcome, destination) -> None:
    """Lo que la IA leyó de cada cara, tal cual, junto a la entrega.

    Es lo que permite revisar una hoja sin volver a pagarla: la cola de
    revisión dice qué cara mirar, y este archivo dice qué vio la IA en ella.
    Sin él, averiguar por qué un nombre no salió obligaba a repetir la
    lectura -- y a pagarla -- para ver la respuesta.
    """
    import json

    lecturas = getattr(outcome.reading, "lecturas", None) or {}
    if not lecturas:
        return
    try:
        destination.mkdir(parents=True, exist_ok=True)
        with open(destination / LECTURAS_IA, "w", encoding="utf-8") as archivo:
            for pagina in sorted(lecturas):
                archivo.write(
                    json.dumps({"pagina": pagina, "texto": lecturas[pagina]}, ensure_ascii=False)
                    + "\n"
                )
    except Exception:  # noqa: BLE001 - es un extra para revisar, no la entrega
        logger.warning("no se pudieron dejar las lecturas de la IA", exc_info=True)
