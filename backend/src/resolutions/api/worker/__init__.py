"""Lo que se le pide a un PDF, hecho en un proceso worker.

Un paquete con un módulo por habilidad, y las cuatro con la misma silueta:

1. **el taller** -- de dónde viene el PDF, a dónde va, por dónde avisa y con
   qué lee (`taller.py`);
2. **decidir los grupos** -- lo único que de verdad distingue una ruta de otra:
   por el número impreso (`resoluciones.py`), por el registro leído
   (`registros.py`), por continuidad (`correspondencia.py`) o sin cortar nada
   (`inventario.py`);
3. **entregar** -- describir, comprobar, escribir e inventariar, por el mismo
   camino para todas (`application/entrega.py`);
4. **las planillas** -- la del documento y el FUID (`planillas.py`);
5. **el informe**.

Aquí sólo vive el despachador: decide a qué habilidad va cada trabajo leyendo
lo que está impreso en una muestra de páginas, nunca el nombre del archivo.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...application.progress import Stage
from .correspondencia import _segment_job
from .inventario import _inventory_file_job, _inventory_job
from .planillas import FUID_SUFFIX, _escribir_fuid, _escribir_planilla
from .registros import _record_split_job
from .resoluciones import _split_job
from .taller import Taller, _anunciar, _boundary_oracle, _control, _reportero, _ubicacion

__all__ = [
    "FUID_SUFFIX",
    "Taller",
    "process_document_job",
    "_anunciar",
    "_boundary_oracle",
    "_control",
    "_escribir_fuid",
    "_escribir_planilla",
    "_inventory_file_job",
    "_inventory_job",
    "_record_split_job",
    "_reportero",
    "_segment_job",
    "_split_job",
    "_ubicacion",
]

logger = logging.getLogger(__name__)

#: Que nadie ha preguntado todavía qué documento es. Distinto de `None`, que es
#: el reconocedor diciendo que no pudo, y de `DESCONOCIDO`, que es el papel
#: diciendo que no es nada de lo que este sistema sabe partir.
_SIN_RECONOCER = object()


def process_document_job(payload: dict) -> dict:
    """Do what was asked of one PDF, and say what it cost.

    El contador de consumo se crea aquí, antes de elegir ruta, y vive en el
    payload para que el taller de cualquier ruta lo encuentre. Al volver el
    informe se le adjunta el total: cuántas páginas se pagaron, cuántos tokens,
    cuántas veces el proveedor pidió esperar. Es lo que permite mirar una
    carpeta de doscientos archivos y saber qué costó producirla.
    """
    from ...application.consumo import Consumo

    consumo = Consumo(
        precio_por_pagina=(payload.get("settings") or {}).get("precio_ocr_por_pagina")
    )
    payload["consumo"] = consumo
    report = _despachar(payload)
    if isinstance(report, dict):
        report["consumo"] = consumo.as_dict()
    return report


def _despachar(payload: dict) -> dict:
    """Do what was asked of one PDF, in a worker process, so it stays picklable.

    Two things can be asked. Splitting writes one document per unit and is what
    the system always did. Inventorying reads the document and writes only its
    FUID, leaving the original whole -- which is the only option for a bound
    book of diploma registrations, because nobody is going to unbind it.
    """
    from ...application.task import TaskKind

    task = TaskKind.parse(payload.get("task"))

    # Inventariar el archivo entero no necesita reconocer nada antes: la unidad
    # documental es el PDF, y qué es se lee de su propio encabezado al pasar por
    # él. Va delante de todo lo demás porque preguntarle a esta ruta de qué tipo
    # es el documento sería justo el paso que no hace falta.
    if task is TaskKind.INVENTORY_FILE:
        return _inventory_file_job(payload)

    if not task.writes_documents:
        return _inventory_job(payload)

    from ...application.tipo_pedido import TipoPedido
    from ...domain.doctype import DocumentType

    # Lo que el operador declaró estar cargando, que manda sobre todo lo demás.
    declarado = TipoPedido.parse(payload.get("tipo")).document_type

    # Incluso sobre la acción, y esto hay que justificarlo porque pisa una
    # elección suya. Declarar "esto es un libro de diplomas" y pedir "sepáralo
    # por continuidad" son dos instrucciones incompatibles: la segunda ruta no
    # lee el papel, así que no puede saber de quién es cada hoja ni nombrar el
    # archivo con su cédula, y devuelve el libro cortado por donde la estructura
    # alcanzó. Medido sobre el libro 7, tres corridas seguidas: 199 documentos
    # con el tipo equivocado y numerados 001, 002, 003 en vez de por su
    # graduado. De las dos instrucciones, la que dice **qué es** el documento es
    # más específica que la que dice cómo trocearlo, así que gana ella.
    #
    # No en silencio: se avisa, porque una elección que se cambia sin decirlo es
    # la forma más rápida de que alguien deje de fiarse de la pantalla.
    if declarado is DocumentType.DIPLOMA and task is TaskKind.SEGMENT:
        aviso = (
            "se declaró un libro de diplomas: se parte por folio leyendo cada cara, "
            "no por continuidad, que no lee el papel y no sabría de quién es cada hoja"
        )
        logger.info("%s: %s", payload.get("filename"), aviso)
        _anunciar(payload, Stage.IDENTIFYING, detail=aviso)
        return _record_split_job(payload, TaskKind.SPLIT)

    # Separar por continuidad no necesita saber qué documento es -- corta por
    # dónde acaba una hoja y empieza la otra, no por lo que digan -- pero el
    # operador sí necesita saber si eligió mal. Un legajo de resoluciones
    # separado por continuidad devuelve el doble de unidades y media caja en
    # revisión, porque lo único que distingue una resolución de la siguiente es
    # justo el número impreso que esta ruta no lee. Se reconoce, se avisa, y se
    # hace lo que pidió: la elección es suya.
    if task is TaskKind.SEGMENT:
        return _segment_job(
            payload, task, avisos=_aviso_de_ruta(payload, declarado or _SIN_RECONOCER)
        )

    # Un libro de folios no se parte por herencia sino uno a uno, y un legajo
    # de matrículas se parte por persona, así que hay que saber qué documento es
    # antes de elegir cómo partirlo. Averiguarlo cuesta una muestra de doce
    # páginas -- y en un escaneo sin capa de texto, doce pasadas de OCR -- que
    # hasta ahora transcurrían sin que la pantalla dijera absolutamente nada,
    # justo al principio del trabajo.
    from ...application.inventory_document import SAMPLE_PAGES

    # Si el operador dijo qué está cargando, se le cree y no se reconoce nada.
    # No es sólo ahorrarse la muestra: es que una muestra equivocada condena el
    # archivo entero, y quien tiene el libro delante sabe lo que es antes de
    # subirlo.
    if declarado is DocumentType.DIPLOMA:
        _anunciar(
            payload,
            Stage.IDENTIFYING,
            detail="libro de diplomas, declarado por el operador",
            done=SAMPLE_PAGES,
            total=SAMPLE_PAGES,
        )
        return _record_split_job(payload, task)

    _anunciar(
        payload,
        Stage.IDENTIFYING,
        detail="reconociendo de qué documento se trata",
        done=0,
        total=SAMPLE_PAGES,
    )

    reconocido = _recognise(payload)
    # Los dos van al mismo sitio, y no por comodidad: los dos se parten por lo
    # que dice cada hoja de sí misma -- un folio por cara en el libro de
    # diplomas, una persona por carátula en el legajo de matrículas -- y de las
    # dos lecturas sale ya la agrupación hecha.
    if reconocido in (DocumentType.DIPLOMA, DocumentType.MATRICULA):
        return _record_split_job(payload, task)

    # Y aquí el desvío que evita el peor resultado posible de esta pantalla. Si
    # las páginas no dicen que sean resoluciones, diplomas ni matrículas, partir
    # por código impreso no tiene sobre qué trabajar: busca un número que manda
    # hasta que aparece otro, no encuentra ninguno -- o encuentra uno suelto a
    # media caja -- y entrega el expediente entero como un solo documento con el
    # resto de las hojas en revisión. Es exactamente lo que devolvió una caja de
    # correspondencia de 125 páginas: un documento de la 37 a la 125 y 37 hojas
    # a revisar.
    #
    # Sólo desde «Dividir en documentos». «Dividir e inventariar» se queda donde
    # está: separar por continuidad no levanta FUID -- el formulario pide asunto
    # y tipo documental, que son preguntas sobre un documento que ya tiene
    # bordes -- y desviarlo en silencio dejaría al operador sin el inventario que
    # pidió, sin decírselo.
    if reconocido is DocumentType.DESCONOCIDO and task is TaskKind.SPLIT:
        logger.info(
            "las páginas no reconocen ningún tipo; se separa por continuidad "
            "en vez de agrupar por código"
        )
        _anunciar(
            payload,
            Stage.IDENTIFYING,
            detail="sin tipo reconocible: se separa por continuidad",
            done=SAMPLE_PAGES,
            total=SAMPLE_PAGES,
        )
        return _segment_job(
            payload, TaskKind.SEGMENT, avisos=_aviso_de_ruta(payload, reconocido)
        )

    return _split_job(payload, task)


def _recognise(payload: dict):
    """Qué dice el papel que es este documento.

    Devuelve el tipo, `DESCONOCIDO` si las páginas no dicen ser nada de lo que
    el sistema sabe partir, o `None` si el reconocedor no pudo pronunciarse.

    Se decide sobre una muestra y sobre lo que está impreso en las páginas,
    nunca sobre el nombre del archivo. No reconocer nada es una respuesta, no un
    fallo: es la que manda una caja revuelta al camino que sabe cortarla.
    """
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...adapters.tesseract_ocr import HeaderAndPageOcr
    from ...application.inventory_document import InventoryDocument

    settings = payload["settings"]
    source = PyMuPDFPageSource(Path(payload["source"]), payload.get("filename"))
    try:
        verdict = InventoryDocument(
            ocr=HeaderAndPageOcr(language=settings["ocr_language"])
        ).identify(source)
    except Exception:  # noqa: BLE001 - no reconocerlo no es motivo para fallar
        # `None` y no un tipo: una avería no es un veredicto. Quien enruta la
        # trata como el camino de siempre y quien avisa se calla, que es lo que
        # cada uno debe hacer sin que el otro tenga que adivinarlo.
        logger.warning("no se pudo reconocer el tipo de documento", exc_info=True)
        return None
    finally:
        source.close()
    return verdict.document_type


def _aviso_de_ruta(payload: dict, recognised: object) -> list[str]:
    """Si el papel dice ser otra cosa de la que el operador pidió separar.

    Avisa y no impide nada. Elegir la acción es del operador y hay motivos para
    separar por continuidad un legajo que se reconoce -- un lote mal armado, una
    tanda de pruebas -- pero no hay ninguno para enterarse veinte minutos después
    y por el resultado.
    """
    from ...application.inventory_document import SAMPLE_PAGES
    from ...domain.doctype import DocumentType

    if recognised is _SIN_RECONOCER:
        try:
            recognised = _recognise(payload)
        except Exception:  # noqa: BLE001 - un aviso que se cae no cancela el trabajo
            # `_recognise` protege la lectura pero no la apertura del archivo, y
            # esta ruta no dependía del reconocedor hasta que este aviso llegó.
            # Que un PDF ilegible por él impidiera separar la caja sería cambiar
            # una comodidad por una avería.
            logger.warning("no se pudo avisar de la ruta elegida", exc_info=True)
            return []
    if recognised is None or recognised is DocumentType.DESCONOCIDO:
        return []

    aviso = (
        f"las páginas dicen ser {recognised.label.lower()}; separar por "
        "continuidad no lee el número impreso que las distingue, y "
        "«Dividir en documentos» agruparía por él"
    )
    logger.info("%s: %s", payload.get("filename"), aviso)
    _anunciar(payload, Stage.IDENTIFYING, detail=aviso, done=SAMPLE_PAGES, total=SAMPLE_PAGES)
    return [aviso]
