from __future__ import annotations

import logging
from pathlib import Path

from ..application.progress import Stage

logger = logging.getLogger(__name__)

#: Cómo se llama el Formato Único de Inventario Documental que queda escrito
#: junto al trabajo. El endpoint de descarga lo busca por este sufijo, así que
#: los dos sitios tienen que decir lo mismo.
FUID_SUFFIX = "__FUID.xlsx"


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

    # Antes de reconocer nada: una caja revuelta no tiene un tipo que reconocer.
    # No es un libro de folios ni un legajo de resoluciones, es un montón de
    # papeles distintos metidos en el mismo PDF. Preguntarle a la muestra de doce
    # páginas qué documento es cuesta doce pasadas de OCR para una respuesta que
    # este camino no va a usar.
    if task is TaskKind.SEGMENT:
        return _segment_job(payload, task)

    # Un libro de folios no se parte por herencia sino uno a uno, así que hay
    # que saber qué documento es antes de elegir cómo partirlo. Averiguarlo
    # cuesta una muestra de doce páginas -- y en un escaneo sin capa de texto,
    # doce pasadas de OCR -- que hasta ahora transcurrían sin que la pantalla
    # dijera absolutamente nada, justo al principio del trabajo.
    from ..application.inventory_document import SAMPLE_PAGES

    _anunciar(
        payload,
        Stage.IDENTIFYING,
        detail="reconociendo de qué documento se trata",
        done=0,
        total=SAMPLE_PAGES,
    )
    if _looks_like_a_diploma_book(payload):
        return _diploma_split_job(payload, task)
    return _split_job(payload, task)


def _looks_like_a_diploma_book(payload: dict) -> bool:
    """Si el documento es un libro de registro de diplomas.

    Se decide sobre una muestra y sobre lo que está impreso en las páginas,
    nunca sobre el nombre del archivo. Un error aquí no pierde nada: cae en el
    camino de resoluciones, que es el que el sistema hacía siempre.
    """
    from ..adapters.pymupdf_source import PyMuPDFPageSource
    from ..adapters.tesseract_ocr import HeaderAndPageOcr
    from ..application.inventory_document import InventoryDocument
    from ..domain.doctype import DocumentType

    settings = payload["settings"]
    source = PyMuPDFPageSource(Path(payload["source"]), payload.get("filename"))
    try:
        verdict = InventoryDocument(
            ocr=HeaderAndPageOcr(language=settings["ocr_language"])
        ).identify(source)
    except Exception:  # noqa: BLE001 - no reconocerlo no es motivo para fallar
        logger.warning("no se pudo reconocer el tipo de documento", exc_info=True)
        return False
    finally:
        source.close()
    return verdict.document_type is DocumentType.DIPLOMA


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


def _diploma_split_job(payload: dict, task) -> dict:
    """Partir un libro de folios uno a uno, y su FUID si se pidió.

    Una sola lectura para las dos salidas. Los registros que salen de leer el
    libro son a la vez las filas del inventario y los grupos de una página que
    el escritor convierte en archivos.
    """
    from ..adapters.pymupdf_assembler import PyMuPDFAssembler
    from ..adapters.pymupdf_source import PyMuPDFPageSource
    from ..adapters.queue_progress import QueueProgressReporter
    from ..adapters.tesseract_ocr import HeaderAndPageOcr
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
    finally:
        source.close()

    report = outcome.as_dict()
    report["task"] = str(task)

    if task.writes_documents and outcome.grouping is not None:
        _anunciar(
            payload,
            Stage.ASSEMBLING,
            detail="preparando la escritura",
            done=0,
            total=len(outcome.grouping.groups),
        )
        # Sin prefijo: la unidad de un libro de folios es un folio, no una
        # resolución, y llamar "RESOLUCION_728" a un registro de diploma sería
        # escribir en el disco algo que no es verdad.
        assembly = PyMuPDFAssembler(
            control=control, progress=progress, naming_prefix=None, nombre=name
        ).write(
            source_path, outcome.grouping, destination
        )
        report["outputs"] = [path.name for path in assembly.outputs]
        report["unwritable_pages"] = {
            str(page): error for page, error in assembly.unwritable_pages.items()
        }

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
    _anunciar(payload, Stage.DONE)
    return report


def _boundary_oracle(settings: dict):
    """Quién juzga las costuras que la estructura no pudo decidir.

    Claude primero cuando está su llave: de los dos es el único que puede
    cachear las instrucciones, y en una caja las instrucciones se pagan una vez
    por página. Gemini cuando es lo único que hay. Y sin ninguna llave se
    devuelve el oráculo nulo en vez de fallar: la caja se separa igual por todo
    lo que la estructura decide sola -- en un expediente con paginación impresa,
    la mayor parte -- y lo demás va a revisión.
    """
    from ..adapters.boundary_prompt import NullBoundaryOracle

    anthropic_key = settings.get("anthropic_api_key")
    if anthropic_key:
        from anthropic import Anthropic

        from ..adapters.claude_boundary import ClaudeBoundaryOracle

        return ClaudeBoundaryOracle(client=Anthropic(api_key=anthropic_key))

    gemini_key = settings.get("gemini_api_key")
    if gemini_key:
        from ..adapters.gemini_boundary import GeminiBoundaryOracle

        return GeminiBoundaryOracle(api_key=gemini_key)

    return NullBoundaryOracle()


def _segment_job(payload: dict, task) -> dict:
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
    from ..application.segment_document import SegmentDocument
    from ..application.segment_split import group_by_segment
    from ..domain.naming import DOCUMENT_PREFIX
    from ..domain.segmentation import Verdict

    settings = payload["settings"]
    source_path = Path(payload["source"])
    destination = Path(settings["output_dir"]) / payload["job_id"]
    name = payload.get("filename") or source_path.name

    progress = _reportero(payload)
    control = _control(payload)

    source = PyMuPDFPageSource(source_path, name)
    try:
        page_count = source.page_count
        segmentacion = SegmentDocument(
            oracle=_boundary_oracle(settings), reporter=progress, control=control
        ).run(source)
    finally:
        source.close()

    grupos = group_by_segment(segmentacion.segments)
    # Antes de escribir un solo archivo. Una separación que pierde o repite una
    # hoja se ve idéntica a una correcta mirando la carpeta de salida.
    grupos.verify_integrity(total_pages=page_count)

    _anunciar(
        payload,
        Stage.ASSEMBLING,
        detail="preparando la escritura",
        done=0,
        total=len(grupos.groups),
    )
    # Con "DOCUMENTO" y no con el prefijo de resoluciones: lo que sale de aquí
    # todavía no sabe qué es, y llamarlo "RESOLUCION_01" sería escribir en el
    # disco algo que nadie comprobó.
    assembly = PyMuPDFAssembler(
        control=control, progress=progress, naming_prefix=DOCUMENT_PREFIX, nombre=name
    ).write(source_path, grupos, destination)

    dudosas = [b for b in segmentacion.boundaries if b.verdict is Verdict.UNDECIDED]
    del_modelo = [b for b in segmentacion.boundaries if not b.deterministic]

    report = {
        "document": name,
        "page_count": page_count,
        "groups": [
            {
                "code": group.code.value,
                "title": group.title,
                "pages": group.page_numbers,
                "size": group.size,
            }
            for group in grupos.groups
        ],
        # Una caja no deja páginas huérfanas: toda hoja pertenece al documento
        # que se estuviera leyendo, aunque todavía no se sepa cuál es.
        "quarantine": [],
        "repairs": [],
        # La costura que nadie pudo decidir se cortó -- cortar de más se ve y se
        # arregla en segundos, soldar dos documentos esconde el segundo donde
        # nadie lo busca -- pero el corte queda declarado para que alguien mire.
        "review_queue": [
            {
                "page": boundary.right,
                "reason": "no hay evidencia de si esta hoja abre un documento nuevo",
            }
            for boundary in dudosas
        ],
        "outputs": [path.name for path in assembly.outputs],
        "unwritable_pages": {
            str(page): error for page, error in assembly.unwritable_pages.items()
        },
        # Lo que hace falta para saber si la caja salió cara o barata, y por qué.
        # Las tres últimas reparten las costuras: lo que decidió el papel, lo que
        # decidió el modelo y lo que quedó sin decidir.
        "stats": {
            "documents": len(grupos.groups),
            "seams": len(segmentacion.boundaries),
            "settled_free": len(segmentacion.boundaries) - len(dudosas) - len(del_modelo),
            "model_decided": len(del_modelo),
            "undecided": len(dudosas),
        },
        "task": str(task),
    }
    _anunciar(payload, Stage.DONE)
    return report
