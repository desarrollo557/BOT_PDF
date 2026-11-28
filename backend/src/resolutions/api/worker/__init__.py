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
lo que está impreso -- en una muestra de páginas, o gratis en la capa de texto
del PDF entero --, y el nombre del archivo sólo cuando el papel no dice nada.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

from ...application.progress import Stage

# Cuántas veces más hojas de su núcleo necesita otro tipo para contradecir lo
# que declaró el operador cuando lo declarado también aparece: vive con el
# resto del patrón (``domain/patrones.py``) y se reexporta aquí.
from ...domain.patrones import VECES_PARA_CONTRADECIR
from .correspondencia import _segment_job
from .inventario import _acta_consejo_job, _inventory_file_job, _inventory_job
from .kingspan import _kingspan_job
from .planillas import FUID_SUFFIX, _escribir_fuid, _escribir_indice, _escribir_planilla
from .registros import _record_split_job
from .resoluciones import _split_job
from .taller import Taller, _anunciar, _boundary_oracle, _control, _reportero, _ubicacion

__all__ = [
    "FUID_SUFFIX",
    "VECES_PARA_CONTRADECIR",
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
    # El latido del trabajo (2026-11-27): cada petición que vuelve, cada
    # lectura de Tesseract y cada página que se renderiza le dicen al vigilante
    # que el trabajo sigue vivo, sin cambiar la etapa de la pantalla. Antes,
    # cientos de lecturas de la IA dentro de una misma etapa eran «sin
    # novedades» y a los 20 minutos el libro se daba por atascado.
    from ...application import latido

    latido.activar(lambda: _anunciar(payload, Stage.LATIDO))
    # El primero, en cuanto el trabajo tiene proceso: desde aquí el vigilante
    # sabe que empezó y cuenta su silencio de verdad; antes era la espera en la
    # cola del pool, que no es un atasco (``api/ejecucion._esperar``).
    _anunciar(payload, Stage.LATIDO)
    try:
        report = _despachar(payload)
    finally:
        latido.desactivar()
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
    pedido = TipoPedido.parse(payload.get("tipo"))

    # Un acta de consejo declarada va a su habilidad con cualquier acción: cada
    # PDF es un acta entera, no hay nada que partir, y lo que se pide de ella
    # es su fila del inventario. Pedirle que la divida no tiene respuesta
    # distinta, así que se hace lo único que tiene sentido y se dice.
    if pedido is TipoPedido.ACTA_CONSEJO:
        # Antes de creerle, una mirada gratis al patrón del contenido: en una
        # carpeta con actas de consejo y actas de grado mezcladas, declarar
        # «actas de consejo» mandaba las de grado a una habilidad que no es la
        # suya.
        otro = _lo_que_contradice(payload, pedido)
        if otro is not None:
            return _a_su_habilidad(payload, task, otro, declarado=pedido)
        if task.writes_documents:
            _anunciar(
                payload,
                Stage.IDENTIFYING,
                detail="un acta de consejo no se parte: se inventaría entera",
            )
        return _acta_consejo_job(payload)

    # Las actas de grado declaradas van a su habilidad con cualquier acción,
    # como las de consejo: inventariar, o dividir e inventariar. Salvo que el
    # papel diga con fuerza otra cosa -- un libro de calificaciones, un tomo de
    # resoluciones -- en una corrida declarada entera como actas (2026-11-27).
    if pedido is TipoPedido.ACTA:
        otro = _lo_que_contradice(payload, pedido)
        if otro is not None:
            return _a_su_habilidad(payload, task, otro, declarado=pedido)
        return _actas_de_grado(payload)

    # Historias académicas o calificaciones declaradas: un PDF por estudiante y
    # su fila en el FUID, sin pasar por el reconocedor, que las toma por
    # matrículas. Las dos las parte la misma habilidad; el papel dice cuál es.
    if pedido in (TipoPedido.HISTORIA, TipoPedido.CALIFICACIONES):
        otro = _lo_que_contradice(payload, pedido)
        if otro is not None:
            return _a_su_habilidad(payload, task, otro, declarado=pedido)
        from .historias import historias_academicas_job

        return historias_academicas_job(payload)

    # Los libros de nómina declarados (2026-11-06): un PDF por persona o por
    # paquete y su fila en el FUID, con cualquier acción.
    if TipoPedido.parse(payload.get("tipo")) is TipoPedido.NOMINA:
        from .nominas import nominas_job

        return nominas_job(payload)

    # Los certificados de tiempo de servicio declarados (2026-11-06): un PDF por
    # certificado con sus anexos, y su fila en el FUID.
    if TipoPedido.parse(payload.get("tipo")) is TipoPedido.CERTIFICADO_TIEMPO:
        from .certificados import certificados_job

        return certificados_job(payload)

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

    # Sin tipo declarado, lo primero: el patrón gratis de la capa de texto y del
    # nombre (``sugerir``). Si dice acta de consejo, va a su habilidad antes que
    # a ninguna otra. Odontología, 2026-11-11, con «No estoy seguro» y «Solo
    # inventariar»: seis actas se fueron dos a «Historias académicas» -- sus
    # anexos con el membrete de la Universidad parecían hojas sueltas, y salieron
    # siete filas «MATRICULA ACADEMICA» -- y cuatro a «Archivos ya separados»
    # con un asunto de basura de OCR, porque «Solo inventariar» sólo mira los
    # marcadores. El patrón decía acta de consejo en las 64 de la carpeta, y en
    # ningún PDF de historias, nóminas, certificados ni grados de las otras
    # siete carpetas de la Universidad.
    parece = None
    capa: list[str] | None = None
    if pedido is TipoPedido.AUTO:
        from ...domain.doctype import DocumentType as _Tipo

        # Lo primero, un libro de calificaciones: su evidencia es la más
        # específica de todas -- la lista de la promoción y cinco alumnos o más
        # con su constancia o su record en un tercio de las hojas -- y su record
        # es la misma ficha de las historias, cuyo «Acta Nº» además se lee como
        # el encabezado de un acta de consejo. Los de 1995-1997 no tenían
        # habilidad y se partían como resoluciones; los de 1998, 1999 y 2003 se
        # partían como historias (2026-11-27). La caja de correspondencia
        # («por continuidad») no pasa por aquí: lo que pidió es justo no leerlo.
        if task is not TaskKind.SEGMENT:
            capa = _capa_de_texto(payload)
        if capa and (evidencia := _libro_de_calificaciones(capa, payload)):
            from .historias import historias_academicas_job

            _anunciar(payload, Stage.IDENTIFYING, detail="libro de calificaciones: se procesa con «Calificaciones»")
            payload["reconocimiento"] = {
                "tipo": str(TipoPedido.CALIFICACIONES),
                "etiqueta": TipoPedido.CALIFICACIONES.label,
                "decidido_por": "patron",
                "por": "contenido",
                "motivo": evidencia,
            }
            # La habilidad que lo parte sabe así qué libro tiene, como si el
            # operador lo hubiera declarado.
            payload["tipo"] = str(TipoPedido.CALIFICACIONES)
            return historias_academicas_job(payload)

        parece = _reconocimiento_gratis(payload)
        if parece is not None and parece.tipo is _Tipo.ACTA_CONSEJO:
            _anunciar(
                payload,
                Stage.IDENTIFYING,
                detail="actas de consejo: se inventarían enteras, sin partir nada",
            )
            payload["reconocimiento"] = {
                "tipo": str(parece.tipo),
                "etiqueta": parece.tipo.label,
                "decidido_por": "patron",
                "por": parece.por,
                "motivo": parece.motivo,
            }
            return _acta_consejo_job(payload)

    # Después, si es de la familia de las historias académicas -- Medicina,
    # Enfermería, las hojas sueltas de matrícula --, va a esa habilidad. El
    # reconocedor general las toma por matrículas y la ruta vieja entregaba 9
    # PDF donde había 60 estudiantes. Lo pidió el operador el 2026-11-03: «que
    # sepa detectar la habilidad automáticamente».
    if pedido is TipoPedido.AUTO and (familia := _familia_de_historias(payload, capa)):
        from .historias import historias_academicas_job

        _anunciar(payload, Stage.IDENTIFYING, detail=f"{familia}: se procesa con «Historias académicas»")
        payload["reconocimiento"] = {"tipo": "historia-academica", "por": "contenido", "motivo": familia}
        return historias_academicas_job(payload)

    # Un manuscrito cuya capa de texto es basura: ningún tipo tiene evidencia en
    # ninguna hoja, y sólo la ruta dice lo que es. Los libros de actas de grado
    # de Odontología de 1952-1959 y 1960-1965 (y los exámenes de la caja 3362)
    # llegaban igual a actas de grado por el nombre, pero al final del
    # orquestador, donde una hoja legible -- las tres resoluciones de 1972 con
    # que empieza el de 1960-1965 -- o una página vacía leída con Tesseract
    # podían decidir antes que la ruta (2026-11-27).
    if pedido is TipoPedido.AUTO and capa and (por_la_ruta := _acta_por_la_ruta(capa, payload)):
        payload["reconocimiento"] = {
            "tipo": str(TipoPedido.ACTA),
            "etiqueta": TipoPedido.ACTA.label,
            "decidido_por": "nombre",
            "por": "nombre",
            "motivo": por_la_ruta,
        }
        return _actas_de_grado(payload)

    if not task.writes_documents:
        # Sin tipo declarado, una mirada gratis al patrón antes del inventario:
        # un acta de grado reconocida allí iba al borrador roto de `acta_split`.
        if parece is not None:
            from ...domain.doctype import DocumentType as _Tipo

            if parece.tipo is _Tipo.ACTA:
                return _actas_de_grado(payload)
        return _inventory_job(payload)

    from ...domain.doctype import DocumentType

    # Lo que el operador declaró estar cargando, que manda sobre todo lo demás.
    declarado = pedido.document_type

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
        otro = _lo_que_contradice(payload, pedido)
        if otro is not None:
            return _a_su_habilidad(payload, task, otro, declarado=pedido)
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
    # Sí se mira gratis su capa entera: un libro de calificaciones o de actas
    # de grado dentro de una carpeta declarada «resoluciones» (la PROMOCION
    # 2003 de Odontología vive en RESOLUCIONES\…\UPD3860100) va a lo suyo. El
    # acta de soporte de una resolución no llega a arrollar a sus resoluciones,
    # y el nombre que dice «RESOLUCIONES» sólo cede ante unas calificaciones.
    if declarado is DocumentType.RESOLUCION:
        otro = _lo_que_contradice(payload, pedido)
        if otro is not None:
            return _a_su_habilidad(payload, task, otro, declarado=pedido)
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


#: Cuántas páginas se leen, como mucho, para saber de qué habilidad es un PDF:
#: la capa de texto de un libro de 340 páginas se lee en un segundo.
PAGINAS_PARA_LA_FAMILIA = 600


def _capa_de_texto(payload: dict) -> list[str] | None:
    """La capa de texto del PDF, hasta ``PAGINAS_PARA_LA_FAMILIA`` hojas; ``None`` si no se puede abrir.

    Gratis: sólo el texto que el PDF ya trae, sin leer una imagen. Es lo que
    miran las preguntas que deciden la habilidad sobre el PDF entero -- un libro
    de calificaciones, la familia de las historias, lo que contradice lo
    declarado -- y se lee una sola vez por trabajo.
    """
    from ...adapters.pymupdf_source import PyMuPDFPageSource

    try:
        source = PyMuPDFPageSource(Path(payload["source"]), payload.get("filename"))
    except Exception:  # noqa: BLE001 - no poder mirarlo no es motivo para fallar: sigue lo de siempre
        logger.debug("no se pudo abrir %s para leer su capa de texto", payload.get("filename"), exc_info=True)
        return None
    try:
        hasta = min(source.page_count, PAGINAS_PARA_LA_FAMILIA)
        return [source.text_of(numero) or "" for numero in range(1, hasta + 1)]
    except Exception:  # noqa: BLE001 - una capa que no se deja leer no decide nada
        logger.debug("no se pudo leer la capa de texto de %s", payload.get("filename"), exc_info=True)
        return None
    finally:
        source.close()


def _familia_de_historias(payload: dict, capa: list[str] | None = None) -> str | None:
    """Si el PDF es de los que parte «Historias académicas», y cuál; por su capa de texto, gratis."""
    from ...domain.historia_medicina import familia_de_historias

    textos = capa if capa is not None else _capa_de_texto(payload)
    if textos is None:
        return None
    return familia_de_historias(textos, str(payload.get("filename") or ""))


def _libro_de_calificaciones(capa: list[str], payload: dict) -> str | None:
    """Si el PDF es un libro de calificaciones, lo que lo dice; ``None`` si no lo es."""
    from ...domain.calificaciones import (
        es_libro_de_calificaciones,
        evidencia_de_calificaciones,
    )

    if not es_libro_de_calificaciones(capa, str(payload.get("filename") or "")):
        return None
    cuenta = evidencia_de_calificaciones(capa)
    partes = [
        f"{veces} {nombre}"
        for nombre, veces in (
            ("hoja(s) de la lista de la promoción", cuenta.get("lista", 0)),
            ("constancias de calificaciones", cuenta.get("constancia", 0)),
            ("records académicos", cuenta.get("record", 0)),
        )
        if veces
    ]
    return f"libro de calificaciones: {', '.join(partes) or 'sus hojas'} en {len(capa)} hojas"


def _acta_por_la_ruta(capa: list[str], payload: dict) -> str | None:
    """Si la capa de texto es basura y la ruta dice actas de grado, el motivo; ``None`` si no."""
    from ...domain.doctype import DocumentType
    from ...domain.patrones import (
        capa_que_no_dice_nada,
        hojas_de_cada_tipo,
        pista_del_nombre,
    )

    nombre = str(payload.get("filename") or "")
    if pista_del_nombre(nombre) is not DocumentType.ACTA:
        return None
    if not capa_que_no_dice_nada(capa, hojas_de_cada_tipo(capa)):
        return None
    return (
        f"la capa de texto no dice qué es ({len(capa)} hojas sin evidencia de ningún tipo: un manuscrito); "
        f"la ruta «{nombre}» dice actas de grado. Conviene revisarlo"
    )


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


def _reconocimiento_gratis(payload: dict):
    """Lo que dice el patrón del PDF, sobre su capa de texto y su nombre, con el motivo; ``None`` si falla."""
    from ...adapters.pymupdf_source import PyMuPDFPageSource
    from ...application.sugerencia import sugerir

    try:
        source = PyMuPDFPageSource(Path(payload["source"]), payload.get("filename"))
        try:
            return sugerir(source, str(payload.get("filename") or ""))
        finally:
            source.close()
    except Exception:  # noqa: BLE001 - sin mirar, sigue el camino de siempre
        logger.debug("no se pudo mirar el patrón de %s", payload.get("filename"), exc_info=True)
        return None


def _el_patron_lo_contradice(payload: dict, declarado, capa: list[str] | None = None):
    """El tipo que dice el contenido, si dice claramente que no es el declarado.

    Sólo sobre la capa de texto del PDF entero -- hasta seiscientas hojas ya
    extraídas, sin leer una imagen --, así que cuesta un segundo y no gasta
    nada. Contradice cuando otro tipo arrolla a lo declarado: el triple de sus
    hojas y dos por lo menos (``patrones.lo_que_lo_arrolla``). Ante la duda
    manda lo que dijo el operador, que tiene el papel delante. Un escaneo sin
    capa de texto no contradice nunca: lo dice, si acaso, su nombre.
    """
    from ...domain.patrones import hojas_de_cada_tipo

    textos = capa if capa is not None else _capa_de_texto(payload)
    if textos is None:
        # Sin mirar, manda lo declarado.
        return None
    return _lo_arrolla(hojas_de_cada_tipo(textos), declarado, str(payload.get("filename") or ""))


def _lo_arrolla(hojas, declarado, nombre: str):
    """El tipo que arrolla a lo declarado; sin evidencia de ningún tipo, el que dice el nombre."""
    from ...domain.patrones import lo_que_lo_arrolla, pista_del_nombre

    if not hojas:
        # Sin una sola hoja con evidencia -- un manuscrito sin capa de texto --
        # queda el nombre: «ACTAS DE GRADO 1988-2012» no es un acta de consejo
        # aunque se haya declarado la carpeta entera como tal.
        pista = pista_del_nombre(nombre)
        return pista if pista is not None and pista is not declarado else None
    # Lo declarado manda salvo que otro tipo lo arrolle. Un libro de actas de
    # grado de 1981 tiene tres constancias con forma de acta de sesión entre
    # veinticuatro páginas de grado, y eso no lo convierte en un acta de consejo.
    return lo_que_lo_arrolla(hojas, declarado)


def _lo_que_contradice(payload: dict, pedido):
    """La habilidad que exige el papel en vez de la declarada, o ``None`` si lo declarado se sostiene.

    El operador, 2026-11-27: «que el bot sepa con mucha, pero mucha precisión
    qué habilidad tomar automáticamente en el medio del proceso para procesar
    un PDF con un formato diferente». Con una habilidad declarada para la
    carpeta entera, cada PDF se mira gratis sobre su capa de texto, y sólo se
    desvía con evidencia positiva y dominante, nunca por descarte:

    1. **Un libro de calificaciones** -- la lista de su promoción y cinco alumnos
       o más con su constancia o su record -- es calificaciones aunque se haya
       declarado otra cosa: la PROMOCION 2003 de Odontología vive en la carpeta
       de las resoluciones.
    2. **Historias o calificaciones declaradas** se sostienen con la familia de
       las historias; las calificaciones que no son un libro, pero sí
       historias, van a «Historias académicas».
    3. **Lo que el nombre confirma no se contradice** por el núcleo: un PDF que se
       llama «RESOLUCIONES DE RECTORIA 03272-03275» declarado como resoluciones
       es un legajo de resoluciones aunque traiga actas de consejo de soporte
       (2026-10-29: se fueron a «Actas de consejo»), y uno que se llama
       «HISTORIAS ACADEMICAS 1993» declarado como historias, unas historias.
    4. **El núcleo de otro tipo que arrolla** al declarado en el PDF entero
       (``_el_patron_lo_contradice``), en el orden de «Detectar
       automáticamente»: el acta de consejo primero; sin una sola hoja de lo
       declarado, la familia de las historias -- unas matrículas o unas
       historias van a «Historias académicas», no al legajo de matrículas
       viejo --; y después lo demás.

    Devuelve una ``TipoPedido`` cuando decide algo más que el núcleo -- las
    calificaciones, las historias -- y el ``DocumentType`` del núcleo cuando
    decide él, que va por el mismo camino de siempre (``_a_su_habilidad``).
    """
    from ...application.tipo_pedido import TipoPedido
    from ...domain.calificaciones import es_libro_de_calificaciones
    from ...domain.doctype import DocumentType
    from ...domain.historia_academica import plano
    from ...domain.historia_medicina import NOMBRE_DE_HISTORIAS, familia_de_historias
    from ...domain.patrones import hojas_de_cada_tipo, pista_del_nombre

    capa = _capa_de_texto(payload)
    if capa is None:
        return None
    nombre = str(payload.get("filename") or "")
    familia = None
    if any(texto.strip() for texto in capa):
        if es_libro_de_calificaciones(capa, nombre):
            return None if pedido is TipoPedido.CALIFICACIONES else TipoPedido.CALIFICACIONES
        familia = familia_de_historias(capa, nombre)
        if pedido in (TipoPedido.HISTORIA, TipoPedido.CALIFICACIONES) and familia:
            return None if pedido is TipoPedido.HISTORIA else TipoPedido.HISTORIA
    declarado = pedido.document_type
    lo_confirma = (declarado is not None and pista_del_nombre(nombre) is declarado) or (
        pedido is TipoPedido.HISTORIA and bool(NOMBRE_DE_HISTORIAS.search(plano(nombre)))
    )
    if lo_confirma:
        return None
    hojas = hojas_de_cada_tipo(capa)
    otro = _lo_arrolla(hojas, declarado, nombre)
    # En el orden de «Detectar automáticamente»: el acta de consejo antes que
    # la familia de las historias (sus anexos de matrícula la engañan,
    # 2026-11-11), y la familia antes que lo demás.
    if otro is DocumentType.ACTA_CONSEJO:
        return otro
    if familia and hojas[declarado] == 0:
        return TipoPedido.HISTORIA
    return otro


def _a_su_habilidad(payload: dict, task, tipo, *, declarado) -> dict:
    """Manda un documento a la habilidad de lo que es, y lo dice.

    Se avisa en la consola y en el informe del documento: cambiar lo que pidió
    el operador sin decirlo es la forma más rápida de que deje de fiarse.
    ``tipo`` es la ``TipoPedido`` de las calificaciones o las historias, o el
    ``DocumentType`` que dijo el núcleo; ``declarado``, lo que eligió el operador.
    """
    from ...application.task import TaskKind
    from ...application.tipo_pedido import TipoPedido
    from ...domain.doctype import DocumentType

    if isinstance(tipo, TipoPedido):
        pedido, etiqueta = tipo, tipo.label
    else:
        pedido = next(
            (opcion for opcion in TipoPedido if opcion.document_type is tipo), TipoPedido.AUTO
        )
        etiqueta = tipo.label
    aviso = (
        f"se declaró «{declarado.label}», pero el contenido es de {etiqueta}: "
        f"va a la habilidad de {etiqueta}"
    )
    payload = {**payload, "tipo": str(pedido)}

    if tipo in (TipoPedido.CALIFICACIONES, TipoPedido.HISTORIA):
        # Las dos las parte la habilidad de las historias, que sabe por el
        # tipo qué libro tiene delante.
        from .historias import historias_academicas_job

        def runner(datos):
            return historias_academicas_job(datos)
    elif tipo is DocumentType.ACTA:
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
            "etiqueta": etiqueta,
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
