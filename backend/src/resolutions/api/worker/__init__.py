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
import pickle
from pathlib import Path

from ...application.progress import Stage
from .correspondencia import _segment_job
from .inventario import _acta_consejo_job, _inventory_file_job, _inventory_job
from .kingspan import _kingspan_job
from .planillas import FUID_SUFFIX, _escribir_fuid, _escribir_indice, _escribir_planilla
from .registros import _record_split_job
from .resoluciones import _split_job
from .taller import Taller, _anunciar, _boundary_oracle, _control, _reportero, _ubicacion

__all__ = [
    "FUID_SUFFIX",
    "Taller",
    "process_document_job",
    "_acta_consejo_job",
    "_anunciar",
    "_boundary_oracle",
    "_control",
    "_escribir_fuid",
    "_escribir_indice",
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


class ErrorDelWorker(RuntimeError):
    """Un fallo del worker que no podía viajar tal cual al proceso principal.

    El resultado de un proceso del pool vuelve serializado, y las excepciones
    nativas de MuPDF no se dejan serializar: «cannot pickle SwigPyObject». El
    trabajo fallaba con ese TypeError y el motivo de verdad -- «FzErrorFormat:
    cannot find startxref» -- se perdía. Aquí viaja su clase y su texto.
    """

    para_el_operador = True


def _viaja(error: BaseException) -> bool:
    try:
        pickle.loads(pickle.dumps(error))
    except Exception:  # noqa: BLE001 - lo que sea que impida el viaje
        return False
    return True


def process_document_job(payload: dict) -> dict:
    """El trabajo de un PDF en el worker, con su fallo siempre legible al volver."""
    try:
        return _process_document_job(payload)
    except Exception as error:
        if _viaja(error):
            raise
        detalle = " ".join(str(error).split())[:300] or "sin detalle"
        raise ErrorDelWorker(
            f"El lector del PDF falló ({type(error).__name__}): {detalle}"
        ) from None


def _process_document_job(payload: dict) -> dict:
    """Do what was asked of one PDF, and say what it cost.

    El contador de consumo se crea aquí, antes de elegir ruta, y vive en el
    payload para que el taller de cualquier ruta lo encuentre. Al volver el
    informe se le adjunta el total: cuántas páginas se pagaron, cuántos tokens,
    cuántas veces el proveedor pidió esperar. Es lo que permite mirar una
    carpeta de doscientos archivos y saber qué costó producirla.
    """
    from ...application.consumo import Consumo

    # Un trabajo cancelado mientras esperaba turno en el pool no empieza: la
    # orden llegó antes que él.
    _control(payload).check()

    ajustes = payload.get("settings") or {}
    consumo = Consumo(
        precio_por_pagina=ajustes.get("precio_ocr_por_pagina"),
        # El tope viaja con el trabajo igual que el precio. Se pone aquí, en el
        # contador que comparten todos los adaptadores de este trabajo, y no en
        # cada adaptador: lo que se limita es lo que **el trabajo** gasta, y un
        # tope por adaptador se multiplicaría por los que hubiera.
        tope_de_paginas=ajustes.get("tope_paginas_ocr"),
    )
    payload["consumo"] = consumo
    report = _despachar(payload)
    if isinstance(report, dict):
        report["consumo"] = consumo.as_dict()
        if consumo.ocr_local_fallido:
            # Pagado por un fallo del equipo, no por el papel: que se vea.
            report.setdefault("notices", []).append(
                f"Tesseract falló en {consumo.ocr_local_fallido} lectura(s) y se leyeron con el OCR "
                "de pago. Revise que Tesseract esté instalado y que el equipo no esté saturado."
            )
        # Y cómo se eligió la ruta, cuando hubo que reconocer el documento: el
        # mismo lugar para las cuatro rutas, igual que el consumo.
        if "reconocimiento" in payload:
            report.setdefault("reconocimiento", payload["reconocimiento"])
    return report


def _despachar(payload: dict) -> dict:
    """Do what was asked of one PDF, in a worker process, so it stays picklable.

    Two things can be asked. Splitting writes one document per unit and is what
    the system always did. Inventorying reads the document and writes only its
    FUID, leaving the original whole -- which is the only option for a bound
    book of diploma registrations, because nobody is going to unbind it.
    """
    from ...application.task import TaskKind
    from ...application.tipo_pedido import TipoPedido

    task = TaskKind.parse(payload.get("task"))

    # Un acta de consejo declarada va a su habilidad con cualquier acción: cada
    # PDF es un acta entera, no hay nada que partir, y lo que se pide de ella
    # es su fila del inventario. Pedirle que la divida no tiene respuesta
    # distinta, así que se hace lo único que tiene sentido y se dice.
    if TipoPedido.parse(payload.get("tipo")) is TipoPedido.ACTA_CONSEJO:
        from ...domain.doctype import DocumentType as _Tipo

        # Antes de creerle, una mirada gratis al patrón del contenido: en una
        # carpeta con actas de consejo y actas de grado mezcladas, declarar
        # «actas de consejo» mandaba las de grado a una habilidad que no es la
        # suya.
        otro = _el_patron_lo_contradice(payload, _Tipo.ACTA_CONSEJO)
        if otro is not None:
            return _a_su_habilidad(payload, task, otro, declarado=_Tipo.ACTA_CONSEJO)
        if task.writes_documents:
            _anunciar(
                payload,
                Stage.IDENTIFYING,
                detail="un acta de consejo no se parte: se inventaría entera",
            )
        return _acta_consejo_job(payload)

    # Las actas de grado declaradas van a su habilidad con cualquier acción,
    # como las de consejo: inventariar, o dividir e inventariar.
    if TipoPedido.parse(payload.get("tipo")) is TipoPedido.ACTA:
        return _actas_de_grado(payload)

    # Historias académicas declaradas: un PDF por estudiante y su fila en el
    # FUID, sin pasar por el reconocedor, que las toma por matrículas.
    if TipoPedido.parse(payload.get("tipo")) is TipoPedido.HISTORIA:
        from .historias import historias_academicas_job

        return historias_academicas_job(payload)

    # Inventariar el archivo entero no necesita reconocer nada antes: la unidad
    # documental es el PDF, y qué es se lee de su propio encabezado al pasar por
    # él. Va delante de todo lo demás porque preguntarle a esta ruta de qué tipo
    # es el documento sería justo el paso que no hace falta.
    if task is TaskKind.INVENTORY_FILE:
        return _inventory_file_job(payload)

    # Inventario Kingspan: sólo cuando el operador lo eligió como plantilla de
    # la caja de correspondencia. Antes se detectaba por la presencia de
    # ``agrupar``, que viaja con *todos* los trabajos y vale «documento» por
    # omisión: cualquier «Solo inventariar» de cualquier habilidad caía aquí y
    # fallaba por falta de parámetros que esta ruta nunca tuvo.
    if payload.get("tipo_documento") == "kingspan":
        if task not in (TaskKind.INVENTORY, TaskKind.BOTH):
            raise ValueError(
                "el inventario Kingspan se inventaría o se divide e inventaría; "
                f"no admite la acción {task}"
            )
        return _kingspan_job(payload, task)

    if not task.writes_documents:
        # Sin tipo declarado, una mirada gratis al patrón antes del inventario:
        # un acta de grado reconocida allí iba al borrador roto de `acta_split`.
        if TipoPedido.parse(payload.get("tipo")) is TipoPedido.AUTO:
            from ...domain.doctype import DocumentType as _Tipo

            if _lo_que_parece(payload) is _Tipo.ACTA:
                return _actas_de_grado(payload)
        return _inventory_job(payload)

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
        return _record_split_job(payload, TaskKind.SPLIT, tipo=declarado)

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
        otro = _el_patron_lo_contradice(payload, DocumentType.DIPLOMA)
        if otro is not None:
            return _a_su_habilidad(payload, task, otro, declarado=DocumentType.DIPLOMA)
        _anunciar(
            payload,
            Stage.IDENTIFYING,
            detail="libro de diplomas, declarado por el operador",
            done=SAMPLE_PAGES,
            total=SAMPLE_PAGES,
        )
        return _record_split_job(payload, task, tipo=declarado)

    # Un legajo de resoluciones declarado se parte por su número, sin muestra:
    # reconocido, una resolución que traía un acta de soporte acababa en
    # «Actas de consejo», inventariada entera y con la IA pagada (2026-10-29).
    if declarado is DocumentType.RESOLUCION:
        _anunciar(
            payload,
            Stage.IDENTIFYING,
            detail="legajo de resoluciones, declarado por el operador",
            done=SAMPLE_PAGES,
            total=SAMPLE_PAGES,
        )
        return _split_job(payload, task)

    _anunciar(
        payload,
        Stage.IDENTIFYING,
        detail="reconociendo de qué documento se trata",
        done=0,
        total=SAMPLE_PAGES,
    )

    reconocido = _recognise(payload)
    if reconocido is DocumentType.ACTA:
        # Un acta de grado reconocida no se parte como un legajo de
        # resoluciones, que es adonde caía: va a su habilidad.
        return _actas_de_grado(payload)
    # Unas actas de consejo no se parten nunca: cada PDF se inventaría entero,
    # una fila con su acta, su fecha, sus folios y su resumen. Sin este desvío,
    # una carpeta de actas cargada con «No estoy seguro» acababa separada por
    # continuidad -- «01_DOCUMENTO.pdf», «07_DOCUMENTO-DE-IDENTIDAD.pdf» -- y con
    # un inventario de pedazos en vez del de las actas (carpeta UPD3859771).
    if reconocido is DocumentType.ACTA_CONSEJO:
        _anunciar(
            payload,
            Stage.IDENTIFYING,
            detail="actas de consejo: se inventarían enteras, sin partir nada",
            done=SAMPLE_PAGES,
            total=SAMPLE_PAGES,
        )
        return _acta_consejo_job(payload)
    # Los dos van al mismo sitio, y no por comodidad: los dos se parten por lo
    # que dice cada hoja de sí misma -- un folio por cara en el libro de
    # diplomas, una persona por carátula en el legajo de matrículas -- y de las
    # dos lecturas sale ya la agrupación hecha.
    if reconocido in (DocumentType.DIPLOMA, DocumentType.MATRICULA):
        # Y se le pasa lo reconocido, para que la lectura no vuelva a
        # muestrear el libro que el despachador acaba de muestrear.
        return _record_split_job(payload, task, tipo=reconocido)

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

    Lo decide el orquestador de habilidades (`application.orquestador`). Si los
    marcadores impresos de la muestra deciden, se hace lo de siempre y no se
    gasta nada más; si no, se consulta a todas las habilidades y gana la única
    que compruebe algo, leyendo enteras unas pocas páginas si la banda superior
    no bastó. Todo con Tesseract: reconocer nunca paga a un proveedor.

    Cómo se decidió queda en ``payload["reconocimiento"]``, para que el informe
    pueda decir por qué el documento fue a la ruta a la que fue.
    """
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...adapters.tesseract_ocr import HeaderAndPageOcr
    from ...application import inventory_document
    from ...application.orquestador import DecididoPor, Orquestador

    def primera_mirada(fuente, motor):
        # La primera pregunta sigue siendo la del inventario, por el mismo
        # camino de siempre: lo que reconoce «Solo inventariar» y lo que
        # reconoce este despachador no pueden discrepar sobre el mismo papel.
        return inventory_document.InventoryDocument(ocr=motor).identify(fuente)

    settings = payload["settings"]
    source = PyMuPDFPageSource(Path(payload["source"]), payload.get("filename"))
    try:
        eleccion = Orquestador(
            HeaderAndPageOcr(language=settings["ocr_language"]),
            primera_mirada=primera_mirada,
        ).elegir(source, nombre=str(payload.get("filename") or ""))
    except Exception:  # noqa: BLE001 - no reconocerlo no es motivo para fallar
        # `None` y no un tipo: una avería no es un veredicto. Quien enruta la
        # trata como el camino de siempre y quien avisa se calla, que es lo que
        # cada uno debe hacer sin que el otro tenga que adivinarlo.
        logger.warning("no se pudo reconocer el tipo de documento", exc_info=True)
        return None
    finally:
        source.close()

    payload["reconocimiento"] = eleccion.as_dict()
    if eleccion.decidido_por is not DecididoPor.MARCADORES:
        # Lo nuevo no puede pasar en silencio: que la ruta la eligiera una
        # habilidad, o que no la eligiera nadie, se dice con su motivo.
        logger.info("%s: %s", payload.get("filename"), eleccion.motivo)
        if eleccion.decidido_por is DecididoPor.HABILIDAD:
            _anunciar(
                payload,
                Stage.IDENTIFYING,
                detail=f"el orquestador eligió {eleccion.motivo}",
            )
    return eleccion.tipo


def _actas_de_grado(payload: dict) -> dict:
    """Un acta de grado, con su habilidad: el inventario de actas sin resumen.

    Es el trabajo de las actas de consejo con el perfil de grado -- su
    encabezado, su fecha, sus folios, y un PDF por acta si se pidió dividir --,
    y el mismo Excel sin la columna del resumen.
    """
    _anunciar(payload, Stage.IDENTIFYING, detail="actas de grado: una fila por acta")
    return _acta_consejo_job(payload, grado=True)


def _lo_que_parece(payload: dict):
    """El tipo que dice el patrón del PDF, sobre su capa de texto; ``None`` si falla."""
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...application.sugerencia import sugerir

    try:
        source = PyMuPDFPageSource(Path(payload["source"]), payload.get("filename"))
        try:
            return sugerir(source, str(payload.get("filename") or "")).tipo
        finally:
            source.close()
    except Exception:  # noqa: BLE001 - sin mirar, sigue el camino de siempre
        logger.debug("no se pudo mirar el patrón de %s", payload.get("filename"), exc_info=True)
        return None


#: Cuántas veces más páginas de su núcleo necesita otro tipo para contradecir
#: lo que declaró el operador cuando lo declarado también aparece.
VECES_PARA_CONTRADECIR = 3


def _el_patron_lo_contradice(payload: dict, declarado):
    """El tipo que dice el contenido, si dice claramente que no es el declarado.

    Sólo sobre la capa de texto -- veinticuatro páginas ya extraídas, sin leer
    una imagen --, así que cuesta milisegundos y no gasta nada. Sólo contradice
    cuando el declarado no tiene una sola página de su núcleo y otro tipo lo
    tiene en varias: ante la duda manda lo que dijo el operador, que tiene el
    papel delante. Un escaneo sin capa de texto no contradice nunca.
    """
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...application.orquestador import muestrear
    from ...domain.patrones import (
        PAGINAS_DEL_NUCLEO,
        PAGINAS_PARA_VETAR,
        paginas_con_nucleo,
    )

    try:
        source = PyMuPDFPageSource(Path(payload["source"]), payload.get("filename"))
        try:
            textos = [texto for _n, texto in muestrear(source, None, paginas=PAGINAS_DEL_NUCLEO)]
        finally:
            source.close()
    except Exception:  # noqa: BLE001 - sin mirar, manda lo declarado
        logger.debug("no se pudo mirar el patrón de %s", payload.get("filename"), exc_info=True)
        return None
    nucleo = paginas_con_nucleo(textos)
    if not nucleo:
        # Sin un solo núcleo -- un manuscrito sin capa de texto -- queda el
        # nombre: «ACTAS DE GRADO 1988-2012» no es un acta de consejo aunque se
        # haya declarado la carpeta entera como tal.
        from ...domain.patrones import pista_del_nombre

        pista = pista_del_nombre(str(payload.get("filename") or ""))
        return pista if pista is not None and pista is not declarado else None
    # Lo declarado manda salvo que otro tipo lo arrolle: el triple de páginas
    # con su núcleo. Un libro de actas de grado de 1981 tiene tres constancias
    # con forma de acta de sesión entre veinticuatro páginas de grado, y eso no
    # lo convierte en un acta de consejo.
    propio = nucleo[declarado]
    rivales = [
        (veces, str(tipo), tipo)
        for tipo, veces in nucleo.items()
        if tipo is not declarado
        and veces >= PAGINAS_PARA_VETAR
        and veces >= VECES_PARA_CONTRADECIR * propio
    ]
    return max(rivales)[2] if rivales else None


def _a_su_habilidad(payload: dict, task, tipo, *, declarado) -> dict:
    """Manda un documento a la habilidad de lo que es, y lo dice.

    Se avisa en la consola y en el informe del documento: cambiar lo que pidió
    el operador sin decirlo es la forma más rápida de que deje de fiarse.
    """
    from ...application.task import TaskKind
    from ...application.tipo_pedido import TipoPedido
    from ...domain.doctype import DocumentType

    pedido = next(
        (opcion for opcion in TipoPedido if opcion.document_type is tipo), TipoPedido.AUTO
    )
    aviso = (
        f"se declaró «{declarado.label}», pero el contenido es de {tipo.label}: "
        f"va a la habilidad de {tipo.label}"
    )
    payload = {**payload, "tipo": str(pedido)}

    if tipo is DocumentType.ACTA:
        # Las actas de grado, a su habilidad: el inventario de actas sin resumen.

        def runner(datos):
            return _actas_de_grado(datos)
    elif tipo in (DocumentType.DIPLOMA, DocumentType.MATRICULA):
        def runner(datos):
            return _record_split_job(
                datos, task if task.writes_documents else TaskKind.SPLIT, tipo=tipo
            )
    elif tipo is DocumentType.ACTA_CONSEJO:
        runner = _acta_consejo_job
    elif task.writes_documents:
        def runner(datos):
            return _split_job(datos, task)
    else:
        runner = _inventory_job

    logger.info("%s: %s", payload.get("filename"), aviso)
    _anunciar(payload, Stage.IDENTIFYING, detail=aviso)
    report = runner(payload)
    if isinstance(report, dict):
        report.setdefault("notices", []).append(aviso)
        report["reconocimiento"] = {
            "tipo": str(tipo),
            "etiqueta": tipo.label,
            "decidido_por": "patron",
            "motivo": aviso,
            "declarado": str(declarado),
        }
    return report


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
