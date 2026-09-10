from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from ..application.progress import Stage

logger = logging.getLogger(__name__)

#: Cómo se llama el Formato Único de Inventario Documental que queda escrito
#: junto al trabajo. El endpoint de descarga lo busca por este sufijo, así que
#: los dos sitios tienen que decir lo mismo.
FUID_SUFFIX = "__FUID.xlsx"

#: Que nadie ha preguntado todavía qué documento es. Distinto de `None`, que es
#: el reconocedor diciendo que no pudo, y de `DESCONOCIDO`, que es el papel
#: diciendo que no es nada de lo que este sistema sabe partir.
_SIN_RECONOCER = object()


def process_document_job(payload: dict) -> dict:
    """Do what was asked of one PDF, in a worker process, so it stays picklable.

    Two things can be asked. Splitting writes one document per unit and is what
    the system always did. Inventorying reads the document and writes only its
    FUID, leaving the original whole -- which is the only option for a bound
    book of diploma registrations, because nobody is going to unbind it.

    Adapters are imported here rather than at module scope: the API process has
    no business loading MuPDF or Tesseract just to accept an upload.
    """
    from ..application.task import TaskKind

    task = TaskKind.parse(payload.get("task"))
    if not task.writes_documents:
        return _inventory_job(payload)

    # Separar por continuidad no necesita saber qué documento es -- corta por
    # dónde acaba una hoja y empieza la otra, no por lo que digan -- pero el
    # operador sí necesita saber si eligió mal. Un legajo de resoluciones
    # separado por continuidad devuelve el doble de unidades y media caja en
    # revisión, porque lo único que distingue una resolución de la siguiente es
    # justo el número impreso que esta ruta no lee. Se reconoce, se avisa, y se
    # hace lo que pidió: la elección es suya.
    if task is TaskKind.SEGMENT:
        return _segment_job(payload, task)


    # Un libro de folios no se parte por herencia sino uno a uno, y un legajo
    # de matrículas se parte por persona, así que hay que saber qué documento es
    # antes de elegir cómo partirlo. Averiguarlo cuesta una muestra de doce
    # páginas -- y en un escaneo sin capa de texto, doce pasadas de OCR -- que
    # hasta ahora transcurrían sin que la pantalla dijera absolutamente nada,
    # justo al principio del trabajo.
    from ..application.inventory_document import SAMPLE_PAGES

    _anunciar(
        payload,
        Stage.IDENTIFYING,
        detail="reconociendo de qué documento se trata",
        done=0,
        total=SAMPLE_PAGES,
    )
    from ..domain.doctype import DocumentType

    reconocido = _recognise(payload)
    # Los dos van al mismo sitio, y no por comodidad: los dos se parten por lo
    # que dice cada hoja de sí misma -- un folio por cara en el libro de
    # diplomas, una persona por carátula en el legajo de matrículas -- y de las
    # dos lecturas sale ya la agrupación hecha.
    #
    # Las matrículas no llegaban aquí. `matricula_split.group_by_student` estaba
    # escrito y probado, e `InventoryDocument` ya lo llamaba, pero este desvío
    # sólo nombraba a los diplomas: un legajo de matrículas subido con «dividir»
    # se iba al agrupador por código de resolución, que busca en sus páginas un
    # número que no existe.
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
        return _segment_job(payload, TaskKind.SEGMENT, recognised=reconocido)

    return _split_job(payload, task)


def _recognise(payload: dict):
    """Qué dice el papel que es este documento.

    Devuelve el tipo, `DESCONOCIDO` si las páginas no dicen ser nada de lo que
    el sistema sabe partir, o `None` si el reconocedor no pudo pronunciarse.

    Se decide sobre una muestra y sobre lo que está impreso en las páginas,
    nunca sobre el nombre del archivo. No reconocer nada es una respuesta, no un
    fallo: es la que manda una caja revuelta al camino que sabe cortarla.
    """
    from ..adapters.pymupdf_source import PyMuPDFPageSource
    from ..adapters.tesseract_ocr import HeaderAndPageOcr
    from ..application.inventory_document import InventoryDocument

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


def _split_job(payload: dict, task) -> dict:
    """Partir el documento en uno por unidad documental."""
    from ..adapters.claude_vision import (
        ClaudeVisionConfig,
        ClaudeVisionOracle,
        NullVisionOracle,
    )
    from ..adapters.file_inventory import FileInventoryStore
    from ..adapters.pymupdf_assembler import PyMuPDFAssembler
    from ..adapters.pymupdf_source import PyMuPDFDocumentStore
    from ..adapters.queue_progress import QueueProgressReporter
    from ..adapters.tesseract_ocr import HeaderAndPageOcr
    from ..application.pipeline import ClassificationPipeline, PipelineConfig
    from ..application.process_document import ProcessDocument
    from ..application.progress import NullProgressReporter

    settings = payload["settings"]
    source = Path(payload["source"])
    destination = Path(settings["output_dir"]) / payload["job_id"]

    queue = payload.get("progress_queue")
    progress = (
        QueueProgressReporter(queue, payload["job_id"]) if queue is not None
        else NullProgressReporter()
    )

    api_key = settings.get("anthropic_api_key")
    if api_key:
        from anthropic import Anthropic

        vision = ClaudeVisionOracle(
            client=Anthropic(api_key=api_key),
            config=ClaudeVisionConfig(model=settings["vision_model"]),
        )
    else:
        vision = NullVisionOracle()

    control = _control(payload)
    pipeline = ClassificationPipeline(
        ocr=HeaderAndPageOcr(language=settings["ocr_language"]),
        vision=vision,
        config=PipelineConfig(
            max_workers=settings["page_workers"],
            mosaic_size=settings["mosaic_size"],
        ),
        progress=progress,
        control=control,
    )

    try:
        from ..adapters.excel_inventory import ExcelInventory

        sheets = ExcelInventory()
    except ImportError:
        # openpyxl is not installed: the document still gets split, it just
        # ships without its spreadsheet.
        sheets = None

    use_case = ProcessDocument(
        store=PyMuPDFDocumentStore(payload.get("filename")),
        pipeline=pipeline,
        assembler=PyMuPDFAssembler(control=control, nombre=payload.get("filename")),
        inventory=FileInventoryStore(),
        progress=progress,
        sheets=sheets,
        control=control,
    )
    resultado = use_case.execute(
        source,
        destination,
        source_name=payload.get("filename"),
        operator=payload.get("operator"),
        delivered_to=payload.get("destination"),
    )
    report = resultado.as_dict()
    report["task"] = str(task)

    if task.writes_inventory:
        from ..application.resolution_fuid import filas_de_resoluciones

        # Sobre la misma lectura: las páginas ya están agrupadas, y el FUID sale
        # de esa agrupación sin volver a abrir el documento.
        _escribir_fuid(
            report,
            filas_de_resoluciones(
                resultado.grouping.groups,
                nombre_del_archivo=payload.get("filename") or source.name,
                ubicacion=_ubicacion(settings),
            ),
            settings=settings,
            destination=destination,
            name=payload.get("filename") or source.name,
            document_type=None,
            control=control,
            payload=payload,
        )
    _anunciar(payload, Stage.DONE)
    return report


def _inventory_job(payload: dict) -> dict:
    """Levantar el inventario sin escribir un solo PDF de salida."""
    from ..adapters.claude_vision import (
        ClaudeVisionConfig,
        ClaudeVisionOracle,
        NullVisionOracle,
    )
    from ..adapters.pymupdf_source import PyMuPDFPageSource
    from ..adapters.queue_progress import QueueProgressReporter
    from ..adapters.tesseract_ocr import HeaderAndPageOcr
    from ..application.inventory_document import InventoryDocument
    from ..application.pipeline import ClassificationPipeline, PipelineConfig
    from ..application.progress import NullProgressReporter
    from ..application.task import TaskKind

    settings = payload["settings"]
    source_path = Path(payload["source"])
    destination = Path(settings["output_dir"]) / payload["job_id"]
    name = payload.get("filename") or source_path.name

    queue = payload.get("progress_queue")
    progress = (
        QueueProgressReporter(queue, payload["job_id"]) if queue is not None
        else NullProgressReporter()
    )

    ocr = HeaderAndPageOcr(language=settings["ocr_language"])

    api_key = settings.get("anthropic_api_key")
    if api_key:
        from anthropic import Anthropic

        vision = ClaudeVisionOracle(
            client=Anthropic(api_key=api_key),
            config=ClaudeVisionConfig(model=settings["vision_model"]),
        )
    else:
        vision = NullVisionOracle()

    control = _control(payload)
    use_case = InventoryDocument(
        ocr=ocr,
        # Hace falta para inventariar resoluciones: la agrupación es la que
        # decide qué es una unidad documental, aunque no salga ningún PDF.
        pipeline=ClassificationPipeline(
            ocr=ocr,
            vision=vision,
            config=PipelineConfig(
                max_workers=settings["page_workers"],
                mosaic_size=settings["mosaic_size"],
            ),
            progress=progress,
            control=control,
        ),
        progress=progress,
        control=control,
    )

    source = PyMuPDFPageSource(source_path, name)
    try:
        outcome = use_case.execute(
            source, document_name=name, ubicacion=_ubicacion(settings)
        )
    finally:
        source.close()

    report = outcome.as_dict()
    report["task"] = str(TaskKind.INVENTORY)

    _escribir_fuid(
        report,
        outcome.rows,
        settings=settings,
        destination=destination,
        name=name,
        document_type=outcome.document_type,
        control=control,
        payload=payload,
    )
    _anunciar(payload, Stage.DONE)
    return report


def _control(payload: dict):
    """Lo que este trabajo consulta para saber si debe seguir.

    El diccionario viene de un Manager, así que leerlo cruza a otro proceso.
    Por eso se consulta una vez por página y no dentro del bucle de una: a esa
    cadencia el coste es invisible y la orden llega en un segundo.
    """
    from ..application.control import FlagRunControl, NullRunControl

    controls = payload.get("controls")
    if controls is None:
        return NullRunControl()
    job_id = payload["job_id"]
    return FlagRunControl(lambda: controls.get(job_id))


def _anunciar(
    payload: dict,
    stage,
    page_count: int | None = None,
    *,
    detail: str | None = None,
    done: int | None = None,
    total: int | None = None,
) -> None:
    """Decir en qué va el trabajo, sin que un fallo del aviso lo interrumpa.

    El detalle y el contador no son adorno: una etapa que sólo dice su nombre
    dice lo mismo en el primer archivo que en el número 287, y desde la pantalla
    eso es indistinguible de estar colgado.
    """
    from ..adapters.queue_progress import QueueProgressReporter
    from ..application.progress import ProgressEvent

    queue = payload.get("progress_queue")
    if queue is None:
        return
    try:
        QueueProgressReporter(queue, payload["job_id"]).emit(
            ProgressEvent(
                stage=stage, page_count=page_count, detail=detail, done=done, total=total
            )
        )
    except Exception:  # noqa: BLE001 - la telemetría nunca rompe el trabajo
        logger.debug("no se pudo anunciar la etapa %s", stage, exc_info=True)


def _reportero(payload: dict):
    """El canal por el que un adaptador informa de su avance.

    Devuelve un reportero nulo cuando no hay cola -- en las pruebas y en los
    scripts -- para que escribir PDF o planillas no dependa de que alguien esté
    mirando.
    """
    from ..adapters.queue_progress import QueueProgressReporter
    from ..application.progress import NullProgressReporter

    queue = payload.get("progress_queue")
    if queue is None:
        return NullProgressReporter()
    return QueueProgressReporter(queue, payload["job_id"])


def _ubicacion(settings: dict):
    """La ubicación física del lote, que el PDF no puede saber."""
    from ..application.fuid import Ubicacion

    return Ubicacion(
        caja=settings.get("fuid_caja") or "N/A",
        otro=settings.get("fuid_otro") or "N/A",
        codigo_trd=settings.get("fuid_codigo_trd") or "N/A",
    )


def _escribir_fuid(
    report: dict,
    filas: list,
    *,
    settings: dict,
    destination: Path,
    name: str,
    document_type,
    control=None,
    payload: dict | None = None,
) -> None:
    """Deja el FUID junto a lo demás que produjo el trabajo.

    Que falle no invalida la lectura: el documento se leyó igual y su informe
    sirve. Se anota el motivo en vez de perder el trabajo entero.
    """
    if not filas:
        return
    if payload is not None:
        _anunciar(
            payload,
            Stage.INVENTORYING,
            detail="preparando la planilla",
            done=0,
            total=len(filas),
        )
    if control is not None:
        # Escribir el FUID es lo último que hace el trabajo. Si a estas alturas
        # ya se canceló, no tiene sentido dejar una planilla de un trabajo que
        # el operador dio por abandonado.
        control.check()

    from ..adapters.fuid_inventory import FuidInventory
    from ..application.fuid import Cabecera
    from ..application.inventory_document import default_template, template_for
    from ..domain.naming import sheet_filename

    # La plantilla la decide el tipo de documento que se reconoció, no un ajuste
    # global: en una caja mezclada, cada PDF necesita la suya.
    por_tipo = template_for(document_type) if document_type is not None else default_template()
    plantilla = Path(settings.get("fuid_template") or por_tipo)

    # El nombre que le puso el operador, no el generado con que se almacenó la
    # subida: un FUID llamado "6ea93142663d..." no le dice a nadie de qué libro
    # salió. Recortado a lo que la ruta admite, porque la carpeta de salida ya
    # lleva un identificador de 32 caracteres.
    destino = destination / sheet_filename(
        name, FUID_SUFFIX, directory_length=len(str(destination))
    )
    try:
        escrito = FuidInventory(plantilla, progress=_reportero(payload)).write(
            filas,
            destino,
            cabecera=Cabecera(oficina_productora=settings.get("fuid_oficina")),
        )
        report["fuid"] = escrito.name
    except Exception as error:  # noqa: BLE001 - la lectura sirvió igual
        logger.warning("no se pudo escribir el FUID", exc_info=True)
        report["fuid_error"] = f"{type(error).__name__}: {error}"


def _record_split_job(payload: dict, task) -> dict:
    """Partir por registro leído: un folio de diplomas, un expediente de matrícula.

    Una sola lectura para las dos salidas. Los registros que salen de leer el
    documento son a la vez las filas del inventario y los grupos de páginas que
    el escritor convierte en archivos.

    Sirve a los dos tipos porque `InventoryDocument` ya devuelve la agrupación
    hecha para ambos, y lo que queda por hacer -- escribir un PDF por grupo y,
    si se pidió, el FUID -- no depende de cuál de los dos sea. Se llamaba
    `_diploma_split_job` cuando sólo los diplomas llegaban hasta aquí.
    """
    from ..adapters.pymupdf_assembler import PyMuPDFAssembler
    from ..adapters.pymupdf_source import PyMuPDFPageSource
    from ..adapters.queue_progress import QueueProgressReporter
    from ..adapters.tesseract_ocr import HeaderAndPageOcr
    from ..application.entrega import Destino, entregar
    from ..application.inventory_document import InventoryDocument
    from ..application.progress import NullProgressReporter

    settings = payload["settings"]
    source_path = Path(payload["source"])
    destination = Path(settings["output_dir"]) / payload["job_id"]
    name = payload.get("filename") or source_path.name

    queue = payload.get("progress_queue")
    progress = (
        QueueProgressReporter(queue, payload["job_id"]) if queue is not None
        else NullProgressReporter()
    )

    control = _control(payload)
    use_case = InventoryDocument(
        ocr=HeaderAndPageOcr(language=settings["ocr_language"]),
        progress=progress,
        control=control,
    )
    source = PyMuPDFPageSource(source_path, name)
    try:
        outcome = use_case.execute(
            source, document_name=name, ubicacion=_ubicacion(settings)
        )
        # Qué clase de papel es cada folio o expediente, con la fuente todavía
        # abierta. Lo hace `entregar` más abajo, pero necesita el texto y la
        # fuente se cierra aquí, así que se le guarda el lector.
        #
        # Sin heredar del vecino: en un legajo homogéneo -- un libro de folios
        # es cien veces el mismo papel -- el contexto no aporta nada que no se
        # supiera ya, y heredar sólo taparía los folios que no se dejaron leer.
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

    if task.writes_documents and agrupacion is not None:
        _anunciar(
            payload,
            Stage.ASSEMBLING,
            detail="preparando la escritura",
            done=0,
            total=len(agrupacion.groups),
        )
        # El mismo tramo que las otras rutas: describir, comprobar, escribir e
        # inventariar. Lo que aquí cambia es cómo se llaman los archivos.
        #
        # Sin prefijo y con el título dentro: la unidad de un libro de folios es
        # un folio y la de un legajo de matrículas un expediente -- ninguna es
        # una resolución -- y el título dice de quién es, que es lo que alguien
        # va a buscar. "1128047041_juan-perez_DOCUMENTO-DE-IDENTIDAD.pdf" se
        # lee sin abrirlo.
        entregado = entregar(
            agrupacion,
            origen=source_path,
            nombre=name,
            paginas=outcome.page_count,
            destino=Destino(
                directorio=destination, entregado_en=payload.get("destination")
            ),
            assembler=PyMuPDFAssembler(
                control=control,
                progress=progress,
                naming_prefix=None,
                con_titulo=True,
                nombre=name,
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

    if task.writes_inventory:
        _escribir_fuid(
            report,
            outcome.rows,
            settings=settings,
            destination=destination,
            name=name,
            document_type=outcome.document_type,
            control=control,
            payload=payload,
        )
    # La misma planilla para un libro de folios o un legajo de matrículas:
    # quien recibe la carpeta necesita el listado, se haya cortado como se
    # haya cortado.
    _escribir_planilla(report, destination, payload)

    _anunciar(payload, Stage.DONE)
    return report


#: En qué orden prueba la cascada cuando el operador no eligió. Es por costo, no
#: por calidad: Claude cachea las instrucciones, que en una caja se pagan una vez
#: por página; la capa gratuita de Gemini aguanta una caja preguntada de una sola
#: vez; Mistral no trae ninguna de las dos cosas, así que va último.
_CASCADE = ("claude", "gemini", "mistral")


def _boundary_oracle(settings: dict, choice=None):
    """Quién juzga las costuras que la estructura no pudo decidir.

    Con una elección explícita se respeta o no se contesta. Nunca se sustituye:
    si alguien pidió Mistral y el sistema contestara con Gemini, el informe
    mentiría sobre quién decidió los cortes, y un corte cuya autoría no se puede
    rastrear no sirve para decidir si el criterio funciona. Pedir un proveedor
    sin su llave devuelve el oráculo nulo -- la API contesta 422 antes de llegar
    acá, así que esto es la última defensa y no el camino previsto.

    Sin elección se recorre `_CASCADE`, que es el comportamiento que había antes
    de que la elección existiera.

    Y sin ninguna llave se devuelve el oráculo nulo en vez de fallar: la caja se
    separa por todo lo que la estructura decide sola y lo demás va a revisión.

    Eso no es un modo degradado aceptable, y conviene decirlo con el número
    medido en vez de con una impresión. Sobre el expediente de 125 páginas contra
    el que se construyó este camino, la estructura resolvió 32 de 124 costuras
    -- el 25%, no "la mayor parte" -- y las 92 restantes quedaron sin decidir. Al
    tratarse una costura dudosa como corte, la caja salió como 109 documentos, de
    los cuales 100 son de una sola página.

    Dicho de otro modo: en una caja de correspondencia sin paginación impresa el
    modelo no es una optimización, es la pieza que hace utilizable el resultado.
    Sin llave el operador recibe algo que tiene que rearmar a mano casi entero, y
    la cola de revisión se lo dice honestamente, pero se lo dice 92 veces.
    """
    from ..adapters.boundary_prompt import NullBoundaryOracle
    from ..application.oracle import OracleChoice

    eleccion = OracleChoice.AUTO if choice is None else OracleChoice(choice)

    if eleccion is not OracleChoice.AUTO:
        if not eleccion.is_available(settings):
            logger.warning(
                "se pidió %s y no hay %s; las costuras dudosas van a revisión",
                eleccion.value,
                eleccion.env_var,
            )
            return NullBoundaryOracle()
        return _oracle_named(eleccion.value, settings)

    for candidate in _CASCADE:
        if OracleChoice(candidate).is_available(settings):
            return _oracle_named(candidate, settings)

    return NullBoundaryOracle()


def _oracle_named(name: str, settings: dict):
    """Construye un proveedor concreto, ya sabiendo que su llave está puesta.

    Los adaptadores se importan acá y no arriba porque el proceso de la API no
    tiene por qué cargar el SDK de Anthropic para aceptar una subida.
    """
    if name == "claude":
        from anthropic import Anthropic

        from ..adapters.claude_boundary import ClaudeBoundaryOracle

        return ClaudeBoundaryOracle(
            client=Anthropic(api_key=str(settings.get("anthropic_api_key")))
        )

    if name == "gemini":
        from ..adapters.gemini_boundary import GeminiBoundaryOracle

        return GeminiBoundaryOracle(api_key=str(settings.get("gemini_api_key")))

    from ..adapters.mistral_boundary import MistralBoundaryOracle

    return MistralBoundaryOracle(api_key=str(settings.get("mistral_api_key")))


def _escribir_planilla(report: dict, destination: Path, payload: dict) -> None:
    """Deja la planilla del inventario junto a los PDF que describe.

    Se escribe sola, al terminar, sin que nadie la pida. Es lo que el operador
    necesita para entregar la caja: un listado de qué salió, de qué páginas
    salió cada cosa y qué tipo documental resultó ser, en un archivo que se
    abre en Excel. Hasta ahora sólo la escribía la ruta de resoluciones, así
    que quien separaba una caja revuelta o partía un libro de folios se
    quedaba con los PDF y sin el papel que dice qué son.

    Que falle no invalida nada: los PDF ya están escritos y el informe también.
    Se anota y se sigue, igual que con el FUID.
    """
    try:
        from ..adapters.excel_inventory import ExcelInventory
    except ImportError:
        # openpyxl no está instalado: el documento se parte igual, sólo que
        # sin su planilla.
        return
    _anunciar(payload, Stage.INVENTORYING, detail="escribiendo la planilla")
    try:
        ExcelInventory().write(
            report,
            destination,
            # A dónde va la entrega, cuando va a alguna parte. En una subida
            # suelta no hay carpeta de destino que declarar y la columna se
            # queda con su raya; en una corrida sobre carpeta local sí la hay,
            # y es justo el caso en que el operador necesita leerla.
            delivered_to=payload.get("destination"),
            operator=payload.get("operator"),
            processed_at=datetime.now(UTC).isoformat(),
        )
    except Exception:  # noqa: BLE001 - la entrega ya está en el disco
        logger.warning("no se pudo escribir la planilla del inventario", exc_info=True)


def _aviso_de_ruta(payload: dict, recognised: object) -> list[str]:
    """Si el papel dice ser otra cosa de la que el operador pidió separar.

    Avisa y no impide nada. Elegir la acción es del operador y hay motivos para
    separar por continuidad un legajo que se reconoce -- un lote mal armado, una
    tanda de pruebas -- pero no hay ninguno para enterarse veinte minutos después
    y por el resultado.
    """
    from ..application.inventory_document import SAMPLE_PAGES
    from ..domain.doctype import DocumentType

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


def _segment_job(payload: dict, task, *, recognised: object = _SIN_RECONOCER) -> dict:
    """Separar una caja revuelta en los documentos que la forman.

    Sin OCR y sin visión: se decide sobre la capa de texto y sobre dónde están
    los renglones, que es lo que hace que una caja de cien páginas se resuelva
    en segundos y no en minutos. Un escaneo sin capa de texto no rompe nada aquí
    -- las huellas salen vacías, ninguna costura tiene evidencia y todas van a
    revisión -- pero tampoco se separa solo, y eso tiene que verse en el informe
    en vez de descubrirse abriendo los archivos.
    """
    from ..adapters.pymupdf_assembler import PyMuPDFAssembler
    from ..adapters.pymupdf_source import PyMuPDFPageSource
    from ..application.entrega import Destino, entregar
    from ..application.segment_document import SegmentDocument
    from ..application.segment_split import group_by_segment
    from ..domain.fingerprint import nic_de_la_caja
    from ..domain.naming import document_folder
    from ..domain.segmentation import Verdict

    avisos = _aviso_de_ruta(payload, recognised)

    settings = payload["settings"]
    source_path = Path(payload["source"])
    name = payload.get("filename") or source_path.name
    # Los PDF de una caja van juntos y bajo el nombre de la caja. La carpeta del
    # trabajo sigue siendo la de arriba -- es la que la pantalla y la descarga
    # saben encontrar -- pero quien abra el disco ve "UPD2366126" y no un
    # identificador de treinta y dos letras que no le dice de qué documento es.
    carpeta = document_folder(name)
    destination = Path(settings["output_dir"]) / payload["job_id"] / carpeta

    progress = _reportero(payload)
    control = _control(payload)

    source = PyMuPDFPageSource(source_path, name)
    try:
        page_count = source.page_count
        segmentacion = SegmentDocument(
            oracle=_boundary_oracle(settings, payload.get("oracle")),
            reporter=progress,
            control=control,
        ).run(source)
        # Con la fuente todavía abierta, y después del corte y no antes: ahora
        # cada documento tiene bordes, así que preguntarle qué es tiene una sola
        # respuesta posible en vez de una para noventa páginas distintas.
        grupos = group_by_segment(segmentacion.segments, source.text_of)
        # El NIC del suscriptor, que es de la caja entera y no de ninguno de
        # sus documentos. No decide ningún corte -- lo llevan todas las hojas
        # -- pero es con lo que el archivo identifica el expediente, y la
        # entrega en carpeta lo usa para nombrar la carpeta de destino.
        nic = nic_de_la_caja(segmentacion.fingerprints)
    finally:
        source.close()
    _anunciar(
        payload,
        Stage.ASSEMBLING,
        detail="preparando la escritura",
        done=0,
        total=len(grupos.groups),
    )
    dudosas = [b for b in segmentacion.boundaries if b.verdict is Verdict.UNDECIDED]
    # De qué documento es cada anexo. Se calculaba y no salía a ninguna parte,
    # así que un acta con sus cuatro fotografías era indistinguible de un acta de
    # cinco hojas, que es justo la relación que el veredicto ATTACHMENT existe
    # para no perder.
    anexos = {
        grupo.code.value: segmento.attachment_pages
        for grupo, segmento in zip(grupos.groups, segmentacion.segments, strict=False)
        if segmento.attachment_pages
    }
    del_modelo = [b for b in segmentacion.boundaries if not b.deterministic]

    # Lo que hace falta para saber si la caja salió cara o barata, y por qué.
    # Las tres últimas reparten las costuras: lo que decidió el papel, lo que
    # decidió el modelo y lo que quedó sin decidir. Se calculan aquí, y no
    # dentro del informe, porque el inventario del documento las lleva también:
    # una planilla que no dice cómo se decidió el corte no se puede auditar.
    estadisticas = {
        "documents": len(grupos.groups),
        "seams": len(segmentacion.boundaries),
        "settled_free": len(segmentacion.boundaries) - len(dudosas) - len(del_modelo),
        "model_decided": len(del_modelo),
        "undecided": len(dudosas),
    }

    # Y de aquí en adelante, el tramo que es igual para las cuatro rutas:
    # describir cada unidad, comprobar que no falta ni sobra una hoja, escribir
    # los PDF e inventariar lo que quedó en el disco. Lo hace un solo sitio a
    # propósito -- tenerlo repetido cuatro veces es lo que hacía que un arreglo
    # entrara por una ruta y no por las otras tres.
    #
    # Sin prefijo en el nombre: lo forman el puesto en la caja y el tipo, y
    # "DOCUMENTO" es el tipo de lo que nadie reconoció, no una palabra que se
    # anteponga. Llamar "RESOLUCION_01" a lo que sale de aquí sería escribir en
    # el disco algo que nadie comprobó.
    entregado = entregar(
        grupos,
        origen=source_path,
        nombre=name,
        paginas=page_count,
        destino=Destino(
            directorio=destination, carpeta=carpeta,
            entregado_en=payload.get("destination"),
        ),
        assembler=PyMuPDFAssembler(
            control=control, progress=progress, naming_prefix=None, nombre=name
        ),
        en_revision=[boundary.right for boundary in dudosas],
        estadisticas=estadisticas,
        anexos=anexos,
    )
    inventario = entregado.inventario
    assembly = entregado.assembly

    report = {
        "document": name,
        "page_count": page_count,
        "groups": [
            {
                "code": group.code.value,
                "title": group.title,
                # Qué clase de papel resultó ser, con el nombre del catálogo del
                # archivo. Va al informe además de al nombre del archivo porque
                # es lo que alimenta el inventario, y porque un tipo discutible
                # se corrige en la pantalla sin volver a leer la caja.
                "type": group.kind,
                "pages": group.page_numbers,
                "size": group.size,
                "attachments": anexos.get(group.code.value, []),
            }
            for group in grupos.groups
        ],
        # Una caja no deja páginas huérfanas: toda hoja pertenece al documento
        # que se estuviera leyendo, aunque todavía no se sepa cuál es.
        "quarantine": [],
        "repairs": [],
        # La costura que nadie pudo decidir NO se cortó: la hoja se queda en el
        # documento abierto, porque partir una unidad documental no deja rastro
        # de que existió y unir de más deja un archivo que esta cola nombra. Va
        # aquí, hoja por hoja, para que alguien la mire.
        "review_queue": [
            {
                "page": boundary.right,
                "reason": "no hay evidencia de si esta hoja abre un documento nuevo",
            }
            for boundary in dudosas
        ],
        # Del inventario y no de `assembly.outputs`, aunque salgan de lo mismo:
        # dos listas construidas por caminos distintos acaban discrepando, y la
        # que manda es la que dice qué archivo tiene qué páginas. Llevan la
        # carpeta delante porque lo que la descarga recibe es la ruta dentro del
        # trabajo, no sólo el nombre del archivo.
        "outputs": [item.file_name for item in inventario.items],
        "unwritable_pages": {
            str(page): error for page, error in assembly.unwritable_pages.items()
        },
        # Qué salió de esta caja y de qué páginas salió cada cosa. Esta ruta no
        # levanta FUID -- el formulario pide datos que sólo se saben documento a
        # documento -- pero el inventario no es el FUID: es el rastro que
        # permite ir de un archivo a sus páginas de origen y al revés, y la
        # separación por continuidad lo necesita más que ninguna otra ruta,
        # porque sus nombres son un número de orden y no dicen nada por sí solos.
        "inventory": inventario.as_dict(),
        # De qué suscriptor es esta caja. Va al informe para que la entrega en
        # carpeta pueda agrupar por él sin volver a abrir el PDF.
        "nic": nic,
        "stats": estadisticas,
        "task": str(task),
        # Los avisos viven en el informe y no sólo en el progreso: el progreso
        # se ve mientras corre y el informe se lee después, que es cuando el
        # operador se pregunta por qué salieron ochenta documentos.
        "notices": avisos,
    }
    # La planilla, junto a los PDF de la caja y sin que nadie la pida.
    _escribir_planilla(report, destination, payload)

    _anunciar(payload, Stage.DONE)
    return report
