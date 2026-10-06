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
from pathlib import Path

from ...application.progress import Stage
from .planillas import _escribir_fuid, _escribir_fuid_de_archivo
from .taller import Taller, _anunciar

logger = logging.getLogger(__name__)


def _inventory_job(payload: dict) -> dict:
    """Leer el documento y dejar sólo su FUID, con el original intacto."""
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...application.inventory_document import InventoryDocument
    from ...application.task import TaskKind
    from ...application.tipo_pedido import TipoPedido

    taller = Taller.desde(payload)

    # 1. Leer: la misma cascada que parte resoluciones, puesta a reconocer
    #    registros. De ahí salen las filas del inventario. Con los mismos
    #    ajustes con que se partiría el libro -- el criterio de corte, el
    #    rastreo local de la cédula, el mosaico de la lectura de ahorro --,
    #    porque inventariar sin partir es la misma lectura sin escribir PDF, y
    #    leerla distinto daría un inventario que no cuadra con la carpeta que
    #    saldría del mismo libro.
    ocr = taller.ocr()
    use_case = InventoryDocument(
        ocr=ocr,
        pipeline=taller.pipeline(ocr),
        progress=taller.progress,
        control=taller.control,
        workers=int(taller.settings.get("page_workers") or 8),
        criterio=taller.criterio(),
        rastreo=taller.rastreo(),
        mosaico=taller.mosaico(),
        # Y la repesca de la cédula en franjas, para lo que la lectura
        # entera deje sin ella.
        mosaico_de_cedulas=taller.mosaico_de_cedulas(),
        # Y la repesca de la fecha en el pie del diploma.
        mosaico_de_fechas=taller.mosaico_de_fechas(),
        lectura_de_ahorro=taller.lectura_de_ahorro(),
        # Resúmenes de actas con Mistral
        mistral_summary=taller.mistral_summary(),
    )
    source = PyMuPDFPageSource(taller.source, taller.name)
    try:
        outcome = use_case.execute(
            source,
            document_name=taller.name,
            ubicacion=taller.ubicacion(),
            # Si el operador dijo qué es, no se muestrea: se le cree.
            declarado=TipoPedido.parse(payload.get("tipo")).document_type,
        )
    finally:
        source.close()

    # Si lo que se reconoció son actas de consejo, su inventario es el de actas:
    # una fila por PDF con el acta, la fecha, los folios y el resumen.
    from ...domain.doctype import DocumentType

    if outcome.document_type is DocumentType.ACTA_CONSEJO:
        return _acta_consejo_job(payload)

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


def _acta_consejo_job(payload: dict) -> dict:
    """Inventariar las actas de consejo de un PDF: una fila por acta en un Excel sencillo.

    Si además se pidió dividir -- la acción «Dividir e inventariar» --, cada
    sesión sale en su propio PDF con su portada, su citación, su asistencia, su
    acta y sus anexos dentro. El reparto sale del mismo texto que ya se leyó
    para el inventario, así que dividir no cuesta ninguna lectura más, ni de
    pago ni de casa.

    No el FUID: una tabla con la carpeta, el archivo, las páginas, el acta, su
    fecha, el folio inicial y el final, cuántos folios son y el resumen. Un PDF
    de un acta da una fila; un libro, una por cada acta que trae. Queda junto al
    trabajo, donde la busca el botón «Excel de esta acta», y en una corrida de
    carpeta se junta con los demás PDF en un solo Excel. El original no se toca.
    """
    from ...adapters.excel_actas import SUFIJO, escribir_inventario_de_actas
    from ...adapters.pymupdf_assembler import PyMuPDFAssembler
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...adapters.tesseract_ocr import HeaderAndPageOcr
    from ...application.acta_consejo import (
        SIN_IA,
        InventariarActa,
        dividir_actas,
        resultado_de_cada_acta,
    )
    from ...application.task import TaskKind
    from ...domain.naming import sheet_filename

    taller = Taller.desde(payload)
    # La carpeta del PDF -- la UPD -- cuando viene de una corrida de carpeta,
    # que es cuando el original sigue en su sitio. Una subida está en la
    # carpeta de subidas, que no dice nada.
    carpeta = taller.source.parent.name if payload.get("destination") else ""

    source = PyMuPDFPageSource(taller.source, taller.name)
    try:
        outcome = InventariarActa(
            # El OCR de casa y nada más para leer el texto, elija lo que elija
            # el operador: el acta es mecanografiada, y la ayuda de pago entra
            # sólo para lo que el de casa no sabe leer -- el folio manuscrito --
            # y para escribir el resumen a partir del texto ya leído.
            ocr=HeaderAndPageOcr(language=taller.settings["ocr_language"]),
            resumidor=taller.resumidor(),
            lector_de_folios=taller.lector_de_folios(),
            progress=taller.progress,
            control=taller.control,
            workers=int(taller.settings.get("page_workers") or 8),
            motivo_sin_resumidor=taller.motivo_sin_resumidor(),
        ).execute(source, document_name=Path(taller.name).name, carpeta=carpeta)
    finally:
        source.close()

    # Dividir sólo lo que hay que dividir: un libro con varias actas. Un PDF
    # que ya es un acta -- porque alguien lo dividió antes -- se inventaría y
    # nada más; partirlo daría el mismo PDF con otro nombre.
    pidio_dividir = payload.get("task") in (str(TaskKind.SPLIT), str(TaskKind.BOTH))
    division = None
    if pidio_dividir and outcome.reparto.es_libro:
        # En una carpeta con el nombre del PDF de origen, como las demás
        # habilidades: con varios libros en el mismo trabajo, cada uno en la
        # suya.
        sesiones = len(outcome.sesiones)
        _anunciar(
            payload, Stage.ASSEMBLING, detail=f"escribiendo {sesiones} PDF", done=0, total=sesiones
        )
        division = dividir_actas(
            outcome,
            assembler=PyMuPDFAssembler(
                control=taller.control,
                progress=taller.progress,
                naming_prefix=None,
                nombre=taller.name,
            ),
            source=taller.source,
            destino=taller.destination / Path(taller.name).stem,
            raiz=taller.destination,
        )
    outcome.filas = resultado_de_cada_acta(
        outcome.filas, division.salidas if division else None, pidio_dividir=pidio_dividir
    )

    report = outcome.as_dict()
    # Para el libro mayor es un archivo inventariado entero, que es lo que es:
    # así aparece en la pantalla de Archivo con su acta y su fecha.
    report["task"] = str(TaskKind.INVENTORY_FILE)
    report["tipo"] = "acta-consejo"
    if division is not None:
        report["outputs"] = division.salidas
        report["unwritable_pages"] = division.ilegibles
        report["dividido"] = True

    _anunciar(payload, Stage.INVENTORYING, detail="escribiendo el Excel", done=0, total=1)
    taller.control.check()
    destino = taller.destination / sheet_filename(
        taller.name, SUFIJO, directory_length=len(str(taller.destination))
    )
    try:
        report["inventario"] = escribir_inventario_de_actas(
            outcome.filas, destino, nota=None if taller.con_ia() else SIN_IA
        ).name
    except Exception as error:  # noqa: BLE001 - la lectura sirvió igual
        logger.warning("no se pudo escribir el inventario del acta", exc_info=True)
        report["inventario_error"] = f"{type(error).__name__}: {error}"
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
