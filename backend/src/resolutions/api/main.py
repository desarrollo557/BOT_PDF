from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing
import os
import shutil
import tempfile
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse

from ..adapters.ledger import InventoryLedger
from ..adapters.mysql_inventory import (
    InventoryUnavailable,
    MySQLInventory,
    settings_from_env,
)
from ..application.control import Cancelled, RunState
from ..application.task import TaskKind
from ..domain.naming import output_filename
from ..domain.resolution_code import ResolutionCode
from . import native_picker
from .folders import FolderError, FolderRunner, SourceDisposition, clean_path
from .janitor import IdleJanitor
from .jobs import IN_FLIGHT, Job, JobRegistry, JobState
from .settings import Settings
from .worker import FUID_SUFFIX, process_document_job

logger = logging.getLogger(__name__)

UPLOAD_CHUNK = 1024 * 1024
HEARTBEAT_SECONDS = 15.0

#: How often coalesced progress is pushed to the browser. A 400-page document
#: emits 400 events; a screen can usefully absorb four frames a second. Batching
#: at this cadence is what lets 50 documents stream at once without a flood.
PUBLISH_INTERVAL = 0.25

#: Cada cuánto se vuelve a publicar un trabajo en curso aunque no haya cambiado
#: nada. Dos segundos: lo bastante seguido para que el reloj de la pantalla se
#: mueva y se note que el proceso vive, lo bastante espaciado para que cincuenta
#: documentos a la vez no supongan tráfico apreciable.
HEARTBEAT_PUBLISH_SECONDS = 2.0
PROGRESS_QUEUE_SIZE = 20_000

#: Bumped whenever this file gains an endpoint the front end depends on.
#:
#: A Python process holds the code it imported at start-up, so a service left
#: running across an update answers 404 to every new route and 405 to every new
#: method -- which reads as a broken request rather than as a stale service.
#: The screen compares this against what it was built for and says so plainly.
API_REVISION = 15

#: What this revision can do, so the screen can name what is missing rather than
#: only that something is.
API_FEATURES = (
    "inventory",
    "inventory-xlsx",
    "inventory-backend",
    "documents",
    "folder-runs",
    "cache-sweep",
    "browse",
    "native-picker",
    "job-delete",
    "output-edit",
    "batch-edit",
    "document-edit",
    "document-bulk-delete",
    "document-detail",
    "inventory-task",
    "job-fuid",
    "job-control",
    # Levantar el FUID de un documento ya procesado, y pedir una carpeta con la
    # misma acción que una subida.
    "job-fuid-make",
    "folder-task",
    # Quitar de la pantalla una carpeta ya terminada, o todas de una vez.
    "folder-run-clear",
)

settings = Settings.from_env()
registry = JobRegistry()
def _open_inventory():
    """MySQL cuando está configurada; el archivo cuando no.

    Se comprueba la conexión al arrancar en vez de descubrirla rota en mitad de
    un lote. Si la base está configurada y no responde, el servicio arranca
    igual contra el archivo y lo dice: perder el registro de lo procesado sería
    peor que perder la base, y quedarse sin arrancar, peor todavía.
    """
    config = settings_from_env()
    if config is None:
        logger.info("inventario en archivo: %s", settings.ledger_path)
        return InventoryLedger(settings.ledger_path), "archivo"

    store = MySQLInventory(config)
    try:
        store.check()
    except InventoryUnavailable as error:
        logger.error("%s -- se sigue con el archivo %s", error, settings.ledger_path)
        return InventoryLedger(settings.ledger_path), "archivo (MySQL no respondió)"
    logger.info("inventario en %s", store.describe)
    return store, store.describe


ledger, inventory_backend = _open_inventory()
janitor = IdleJanitor(registry, settings, referenced=lambda: ledger.job_ids())
#: Bound once the app starts, because the runner needs the same ``_run`` the
#: upload path uses -- one code path for a document, however it arrived.
folders: FolderRunner


@asynccontextmanager
async def lifespan(app: FastAPI):
    global folders
    settings.ensure_directories()
    folders = FolderRunner(registry, settings, _run)

    # One process per document. Sized at cores-1 so the event loop always has a
    # core left to accept uploads while the pool is saturated.
    app.state.pool = ProcessPoolExecutor(max_workers=settings.document_workers)
    app.state.manager = multiprocessing.Manager()
    app.state.progress_queue = app.state.manager.Queue(maxsize=PROGRESS_QUEUE_SIZE)
    # Lo que el worker consulta entre página y página para saber si sigue. Vive
    # en el Manager y no en este proceso porque quien lo lee está en otro.
    app.state.controls = app.state.manager.dict()
    #: Documentos cuyo FUID se está levantando en este momento, y el motivo si
    #: alguno falló. Vive aquí y no en el registro de trabajos porque no es un
    #: trabajo nuevo: es una segunda salida del documento que ya se procesó.
    app.state.fuid_jobs = {}
    app.state.tasks = [
        asyncio.create_task(_drain_progress(app)),
        asyncio.create_task(_publish_progress()),
        asyncio.create_task(janitor.run()),
    ]
    logger.info("worker pool started with %s processes", settings.document_workers)

    try:
        yield
    finally:
        for task in app.state.tasks:
            task.cancel()
        app.state.pool.shutdown(wait=False, cancel_futures=True)
        try:
            app.state.manager.shutdown()
        except Exception:  # noqa: BLE001 - already gone
            pass


app = FastAPI(title="Separador de resoluciones", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "api_revision": API_REVISION,
        "features": list(API_FEATURES),
        "document_workers": settings.document_workers,
        "page_workers": settings.page_workers,
        "vision": "claude" if settings.anthropic_api_key else "disabled",
        "native_picker": native_picker.available(),
        "inventory_backend": inventory_backend,
        "queued": registry.pending,
        "queue_limit": settings.queue_limit,
    }


# -- batches ------------------------------------------------------------------


@app.post("/api/batches", status_code=201)
async def create_batch(payload: dict | None = None) -> dict[str, object]:
    name = (payload or {}).get("name") or "Lote sin nombre"
    batch = registry.create_batch(str(name))
    return {"id": batch.id, "name": batch.name, "created_at": batch.created_at}


@app.get("/api/batches")
async def list_batches() -> dict[str, object]:
    return {"batches": [registry.batch_summary(batch) for batch in registry.list_batches()]}


@app.get("/api/batches/{batch_id}")
async def get_batch(batch_id: str) -> dict[str, object]:
    batch = registry.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="El lote no existe")
    return registry.batch_summary(batch)


@app.patch("/api/batches/{batch_id}")
async def rename_batch(batch_id: str, payload: dict) -> dict[str, object]:
    batch = registry.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="El lote no existe")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="El nombre no puede quedar vacio")
    batch.name = name
    for job_id in batch.job_ids:
        job = registry.get(job_id)
        if job is not None:
            registry.publish(job)
    return registry.batch_summary(batch)


@app.delete("/api/batches/{batch_id}")
async def delete_batch(batch_id: str, purge: bool = False) -> dict[str, object]:
    """Clear a whole batch off the screen. Documents still running are kept."""
    batch = registry.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="El lote no existe")

    removed: list[str] = []
    for job_id in list(batch.job_ids):
        if registry.remove(job_id) is None:
            continue
        removed.append(job_id)
        if purge:
            _discard_outputs(job_id)
    return {"removed": len(removed), "ids": removed, "purged": purge}


# -- jobs ---------------------------------------------------------------------


@app.post("/api/jobs", status_code=202)
async def enqueue(
    file: UploadFile,
    batch_id: str | None = None,
    task: str | None = None,
    x_operator: str | None = Header(default=None),
) -> dict[str, object]:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Solo se aceptan archivos PDF")
    try:
        kind = TaskKind.parse(task)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if batch_id and registry.get_batch(batch_id) is None:
        raise HTTPException(status_code=404, detail="El lote no existe")
    if registry.pending >= settings.queue_limit:
        # Push back rather than accumulate. A queue that grows without bound is a
        # queue that lies about how long the work will take.
        raise HTTPException(
            status_code=429, detail="La cola está llena, reintentá en unos instantes"
        )

    destination = settings.upload_dir / f"{uuid4().hex}.pdf"
    written = await _stream_to_disk(file, destination)
    if written == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="El archivo llegó vacío")

    job = registry.create(
        filename=file.filename or destination.name,
        source=destination,
        batch_id=batch_id,
        size=written,
        operator=_operator(x_operator),
        task=str(kind),
    )
    registry.publish(job)
    asyncio.create_task(_run(job))
    return {
        "id": job.id,
        "batch_id": job.batch_id,
        "state": str(job.state),
        "task": job.task,
        "bytes": written,
    }


def _steer(job_id: str, state: RunState) -> Job:
    """Cambia el rumbo de un trabajo en curso, o dice por qué no se puede."""
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="El documento no existe")
    if job.state not in IN_FLIGHT:
        raise HTTPException(
            status_code=409,
            detail=f"El documento ya terminó ({job.state}); no hay nada que detener",
        )
    app.state.controls[job_id] = str(state)
    return job


@app.post("/api/jobs/{job_id}/pause")
async def pause_job(job_id: str) -> dict[str, object]:
    """Detener el trabajo entre una página y la siguiente.

    No mata nada: el worker sigue vivo con el documento abierto, y por eso
    reanudar continúa por donde iba en vez de empezar de nuevo. La orden tarda
    lo que tarde la página en curso, que con OCR es alrededor de un segundo.
    """
    job = _steer(job_id, RunState.PAUSED)
    if job.state is JobState.RUNNING:
        registry.mark_paused(job)
    return {"id": job.id, "state": str(job.state)}


@app.post("/api/jobs/{job_id}/resume")
async def resume_job(job_id: str) -> dict[str, object]:
    job = _steer(job_id, RunState.RUNNING)
    if job.state is JobState.PAUSED:
        registry.mark_resumed(job)
    return {"id": job.id, "state": str(job.state)}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, object]:
    """Abandonar el trabajo. Lo que ya se escribió se conserva y se declara."""
    job = _steer(job_id, RunState.CANCELLED)
    return {"id": job.id, "state": str(job.state), "cancelling": True}


@app.post("/api/batches/{batch_id}/{action}")
async def steer_batch(batch_id: str, action: str) -> dict[str, object]:
    """Lo mismo para un lote entero, que es como se procesa de verdad.

    Pausar de uno en uno cincuenta documentos no es una función, es un castigo.
    """
    estados = {
        "pause": RunState.PAUSED,
        "resume": RunState.RUNNING,
        "cancel": RunState.CANCELLED,
    }
    if action not in estados:
        raise HTTPException(status_code=404, detail=f"Acción desconocida: {action}")

    batch = registry.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="El lote no existe")

    afectados: list[str] = []
    for job_id in list(batch.job_ids):
        job = registry.get(job_id)
        if job is None or job.state not in IN_FLIGHT:
            continue
        app.state.controls[job_id] = str(estados[action])
        if action == "pause" and job.state is JobState.RUNNING:
            registry.mark_paused(job)
        elif action == "resume" and job.state is JobState.PAUSED:
            registry.mark_resumed(job)
        afectados.append(job_id)
    return {"batch_id": batch_id, "action": action, "jobs": afectados}


@app.get("/api/jobs")
async def list_jobs() -> dict[str, object]:
    return {"jobs": [job.as_dict() for job in registry.list()]}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, object]:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="El trabajo no existe")
    return job.as_dict()


@app.patch("/api/jobs/{job_id}")
async def rename_job(job_id: str, payload: dict) -> dict[str, object]:
    """Rename a document on screen. The generated files keep their own names."""
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="El trabajo no existe")
    filename = str(payload.get("filename") or "").strip()
    if not filename:
        raise HTTPException(status_code=422, detail="El nombre no puede quedar vacio")
    job.filename = filename
    registry.publish(job)
    return job.as_dict()


@app.delete("/api/jobs")
async def clear_jobs() -> dict[str, object]:
    """Clear the screen: forget finished documents.

    Only done and failed jobs go, so clearing during a batch never costs work
    already under way. The generated PDFs stay on disk and the inventory keeps
    its rows -- this empties a screen, it does not undo the work.
    """
    removed = registry.remove_finished()
    return {"removed": len(removed), "ids": [job.id for job in removed]}


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str, purge: bool = False) -> dict[str, object]:
    """Forget one document. With ``purge``, delete its generated PDFs as well."""
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="El trabajo no existe")
    if registry.remove(job_id) is None:
        raise HTTPException(
            status_code=409, detail="El documento todavía se está procesando"
        )
    if purge:
        _discard_outputs(job_id)
    return {"removed": 1, "ids": [job_id], "purged": purge}


def _discard_outputs(job_id: str) -> None:
    """Delete one job's output directory. Never allowed to fail the request."""
    directory = (settings.output_dir / job_id).resolve()
    if directory.parent != settings.output_dir.resolve():
        return
    shutil.rmtree(directory, ignore_errors=True)


# -- local folders --------------------------------------------------------------


@app.post("/api/folder-runs", status_code=201)
async def start_folder_run(
    payload: dict, x_operator: str | None = Header(default=None)
) -> dict[str, object]:
    """Drain a local source folder into a local destination folder.

    Nothing is uploaded: the service reads and writes the machine it runs on,
    one document at a time, and reports which file it is on as it goes.
    """
    raw = str(payload.get("disposition") or "leave")
    try:
        disposition = SourceDisposition(raw)
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"Destino del original desconocido: {raw}"
        ) from None

    # Una carpeta puede pedir lo mismo que una subida. Hasta ahora sólo sabía
    # dividir, así que un libro de diplomas tomado de una carpeta no podía dejar
    # su inventario sin volver a subirlo a mano.
    try:
        kind = TaskKind.parse(payload.get("task"))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    try:
        run = folders.start(
            str(payload.get("source") or ""),
            str(payload.get("destination") or ""),
            disposition=disposition,
            watch=bool(payload.get("watch")),
            operator=_operator(x_operator),
            task=str(kind),
        )
    except FolderError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return run.as_dict()


@app.get("/api/folder-runs")
async def list_folder_runs() -> dict[str, object]:
    return {"runs": [run.as_dict() for run in folders.list()]}


@app.get("/api/folder-runs/{run_id}")
async def get_folder_run(run_id: str) -> dict[str, object]:
    run = folders.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="El proceso de carpeta no existe")
    return run.as_dict()


@app.post("/api/folder-runs/{run_id}/stop")
async def stop_folder_run(run_id: str) -> dict[str, object]:
    if folders.get(run_id) is None:
        raise HTTPException(status_code=404, detail="El proceso de carpeta no existe")
    run = folders.stop(run_id)
    if run is None:
        raise HTTPException(status_code=409, detail="Ese proceso ya habia terminado")
    return run.as_dict()


@app.delete("/api/folder-runs")
async def clear_folder_runs() -> dict[str, object]:
    """Vaciar la pantalla de carpetas ya terminadas.

    Sólo se van las que terminaron, pararon o fallaron, así que hacer esto con
    una carpeta en marcha nunca cuesta trabajo empezado. Lo entregado sigue en
    la carpeta de destino y el archivo conserva sus filas: esto vacía una
    pantalla, no deshace nada.
    """
    removed = folders.forget_finished()
    return {"removed": len(removed), "ids": [run.id for run in removed]}


@app.delete("/api/folder-runs/{run_id}")
async def forget_folder_run(run_id: str) -> dict[str, object]:
    """Quitar de la pantalla una carpeta concreta que ya terminó."""
    if folders.get(run_id) is None:
        raise HTTPException(status_code=404, detail="El proceso de carpeta no existe")
    run = folders.forget(run_id)
    if run is None:
        raise HTTPException(
            status_code=409,
            detail="Ese proceso sigue en marcha; hay que detenerlo antes de quitarlo",
        )
    return {"removed": 1, "ids": [run.id]}


# -- resolutions ----------------------------------------------------------------


@app.patch("/api/jobs/{job_id}/outputs/{name}")
async def rename_output(job_id: str, name: str, payload: dict) -> dict[str, object]:
    """Correct a resolution: its number, its title, or both.

    OCR gets a digit wrong often enough that an operator needs to fix it without
    running the document again. The file on disk, the report on screen and the
    inventory row all move together, because a correction that lands in only one
    of them is worse than no correction at all.
    """
    current = _output_path(job_id, name)

    row = next(
        (
            item
            for item in ledger.rows()
            if item.get("job_id") == job_id and item.get("file_name") == name
        ),
        None,
    )
    code = str(payload.get("code") or (row or {}).get("code") or "").strip()
    if not code:
        raise HTTPException(
            status_code=422, detail="El numero de resolucion no puede quedar vacio"
        )
    raw_title = payload.get("title")
    title = None if raw_title is None else str(raw_title).strip() or None

    parsed = ResolutionCode.try_parse(code)
    if parsed is None:
        raise HTTPException(
            status_code=422, detail=f"{code} no es un numero de resolucion valido"
        )

    new_name = output_filename(parsed, title)
    target = current
    if new_name != name:
        target = (settings.output_dir / job_id / new_name).resolve()
        if target.exists():
            raise HTTPException(
                status_code=409, detail=f"Ya existe un archivo llamado {new_name}"
            )
        current.rename(target)

    ledger.update(job_id, name, {"code": parsed.value, "title": title, "file_name": target.name})
    _amend_report(job_id, name, code=parsed.value, title=title, file_name=target.name)
    return {"file_name": target.name, "code": parsed.value, "title": title}


@app.delete("/api/jobs/{job_id}/outputs/{name}")
async def delete_output(job_id: str, name: str) -> dict[str, object]:
    """Delete one generated resolution: the file and its inventory row."""
    target = _output_path(job_id, name)
    target.unlink(missing_ok=True)
    removed = ledger.remove(job_id, name)
    _amend_report(job_id, name, drop=True)
    return {"deleted": name, "was_recorded": removed is not None}


def _output_path(job_id: str, name: str) -> Path:
    directory = (settings.output_dir / job_id).resolve()
    target = (directory / name).resolve()
    # The job id and the file name both arrive from the client.
    if not target.is_file() or directory not in target.parents:
        raise HTTPException(status_code=404, detail="El archivo no existe")
    return target


def _amend_report(
    job_id: str,
    name: str,
    *,
    code: str | None = None,
    title: str | None = None,
    file_name: str | None = None,
    drop: bool = False,
) -> None:
    """Keep the on-screen report in step with the file that was just changed.

    The job may already have been cleared from the screen, in which case the
    ledger is the whole record and there is nothing here to update.
    """
    job = registry.get(job_id)
    report = job.report if job else None
    if not report:
        return

    inventory = report.get("inventory") or {}
    items = inventory.get("items") or []
    match = next((item for item in items if item.get("file_name") == name), None)
    if match is None:
        return

    previous_code = match.get("code")
    if drop:
        inventory["items"] = [item for item in items if item is not match]
        report["groups"] = [g for g in report.get("groups", []) if g.get("code") != previous_code]
        report["outputs"] = [output for output in report.get("outputs", []) if output != name]
    else:
        match.update({"code": code, "title": title, "file_name": file_name})
        for group in report.get("groups", []):
            if group.get("code") == previous_code:
                group["code"] = code
                group["title"] = title
        report["outputs"] = [
            file_name if output == name else output for output in report.get("outputs", [])
        ]

    inventory["generated_files"] = len(inventory.get("items") or [])
    registry.publish(job)


@app.get("/api/folders")
async def browse(path: str | None = None) -> dict[str, object]:
    """Lista las carpetas de una ruta, para el selector del navegador.

    El navegador no puede entregar una ruta absoluta: por seguridad, ni el
    selector de carpetas ni `webkitdirectory` la exponen. Pero el servicio corre
    en la misma máquina que las carpetas, así que el explorador lo pone él.

    Sólo directorios, nunca el contenido de un archivo. Es un servicio local; si
    algún día escucha fuera de esta máquina, esta ruta es la primera que hay que
    cerrar.
    """
    if not path:
        return {"path": None, "parent": None, "drives": _drives(), "folders": []}

    try:
        current = Path(clean_path(path)).expanduser().resolve(strict=True)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail=f"La carpeta no existe: {path}") from None
    if not current.is_dir():
        raise HTTPException(status_code=422, detail="Eso no es una carpeta")

    folders: list[dict[str, object]] = []
    try:
        for entry in sorted(current.iterdir(), key=lambda item: item.name.lower()):
            # Las ocultas y las del sistema sólo estorban en un selector.
            if entry.name.startswith((".", "$")):
                continue
            try:
                if entry.is_dir():
                    folders.append({"name": entry.name, "path": str(entry)})
            except OSError:
                continue
    except PermissionError:
        raise HTTPException(
            status_code=403, detail="Sin permiso para leer esa carpeta"
        ) from None
    except OSError as error:
        raise HTTPException(status_code=422, detail=f"No se pudo leer: {error}") from None

    parent = str(current.parent) if current.parent != current else None
    return {
        "path": str(current),
        "parent": parent,
        "drives": _drives(),
        "folders": folders,
    }


@app.post("/api/folders/pick")
async def pick_folder(payload: dict | None = None) -> dict[str, object]:
    """Abre el explorador de carpetas de Windows y devuelve lo que se eligió.

    Un navegador no puede hacer esto: ninguna API web entrega una ruta absoluta,
    por diseño. El servicio sí puede, porque corre en la misma máquina que el
    escritorio donde aparece la ventana -- y por eso mismo esto deja de tener
    sentido el día que el servicio se mueva a un servidor: el diálogo se abriría
    allá, sin nadie delante. Cuando no se puede, la respuesta lo dice y la
    pantalla cae en su propio explorador.
    """
    options = payload or {}
    title = str(options.get("title") or "Seleccione una carpeta")[:120]
    initial = clean_path(str(options.get("initial") or "")) or None

    try:
        # Fuera del bucle de eventos: el diálogo bloquea mientras esté abierto y
        # el servicio tiene que seguir sirviendo el resto de la aplicación.
        chosen = await asyncio.to_thread(native_picker.ask_directory, title, initial)
    except native_picker.PickerUnavailable as error:
        raise HTTPException(status_code=501, detail=str(error)) from None

    return {"path": chosen, "cancelled": chosen is None}


def _drives() -> list[dict[str, str]]:
    """Puntos de partida: las unidades en Windows, la raíz y el hogar fuera."""
    home = Path.home()
    roots: list[dict[str, str]] = [{"name": "Escritorio", "path": str(home / "Desktop")}]
    roots.append({"name": "Carpeta personal", "path": str(home)})

    if os.name == "nt":
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = Path(f"{letter}:\\")
            try:
                if drive.exists():
                    roots.append({"name": f"Disco {letter}:", "path": str(drive)})
            except OSError:
                continue
    else:
        roots.append({"name": "Raíz", "path": "/"})
    return [root for root in roots if Path(root["path"]).is_dir()]


# -- inventory ----------------------------------------------------------------


@app.get("/api/inventory")
async def inventory(q: str | None = None, limit: int = 500, offset: int = 0) -> dict[str, object]:
    """Every resolution PDF ever produced, newest first.

    The ledger outlives the job registry, so this still answers "which document
    did 00086 come from" long after the screen was cleared.
    """
    rows = ledger.rows()
    if q:
        needle = q.strip().lower()
        rows = [row for row in rows if _matches(row, needle)]

    limit = max(1, min(limit, 5_000))
    window = rows[offset : offset + limit]
    return {
        "rows": window,
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "summary": ledger.summary(),
    }


@app.get("/api/documents")
async def documents(q: str | None = None, limit: int = 500, offset: int = 0) -> dict[str, object]:
    """Every source document ever processed, newest first.

    Read from the ledger rather than from the registry, so the history survives
    clearing the screen and restarting the service -- which is the whole point
    of a record.
    """
    rows = ledger.documents()
    if q:
        needle = q.strip().lower()
        # A document carries only a handful of codes as a sample, so a search
        # for a number must go to the rows themselves. Matching the sample only
        # would answer "no" for a resolution that is demonstrably in there.
        matched_jobs = {
            row.get("job_id")
            for row in ledger.rows()
            if needle in str(row.get("code") or "").lower()
            or needle in str(row.get("title") or "").lower()
        }
        rows = [
            row
            for row in rows
            if needle in str(row.get("source_document") or "").lower()
            or row.get("job_id") in matched_jobs
        ]

    limit = max(1, min(limit, 5_000))
    return {
        "documents": rows[offset : offset + limit],
        "total": len(rows),
        "offset": offset,
        "limit": limit,
    }


@app.get("/api/documents/{job_id}")
async def document_detail(job_id: str) -> dict[str, object]:
    """Un documento ya procesado, tal como lo recuerda el inventario.

    La pantalla de detalle se dibujaba sólo desde el trabajo en memoria, así que
    en cuanto el área de trabajo se limpiaba el documento quedaba en un callejón
    sin salida: la ficha decía "archivado" y no llevaba a ninguna parte. El
    inventario sí lo recuerda -- es lo que lo hace un inventario -- y esto es
    esa memoria, servida para que la ficha vuelva a poder abrirse.

    No devuelve lo mismo que el trabajo en memoria, y no debe fingir que sí: el
    reparto por peldaños, la cinta de páginas y las correcciones de OCR viven en
    el informe del proceso y no se guardan. Lo que queda es lo que se produjo,
    que es justamente lo que un archivo tiene que poder responder meses después.
    """
    entrada = next(
        (item for item in ledger.documents() if item.get("job_id") == job_id), None
    )
    filas = [row for row in ledger.rows() if row.get("job_id") == job_id]
    if entrada is None and not filas:
        raise HTTPException(status_code=404, detail="El documento no está en el inventario")

    return {
        **(entrada or {"job_id": job_id}),
        "rows": filas,
        # Si además sigue en pantalla, la pantalla tiene más que contar y es ella
        # la que manda. Se dice aquí para que el cliente no tenga que adivinarlo.
        "on_screen": registry.get(job_id) is not None,
    }


@app.patch("/api/documents/{job_id}")
async def rename_document(job_id: str, payload: dict) -> dict[str, object]:
    """Rename a processed document wherever it is remembered.

    The name is on every inventory row of the document and, while the job is
    still on screen, on the job as well. Both are corrected in the same request:
    a rename that landed in only one of them would show the document twice in
    the archive, once under each name.

    The generated PDFs keep their own names, which come from the resolution
    number and not from the document that carried it.
    """
    name = str(payload.get("source_document") or payload.get("filename") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="El nombre no puede quedar vacío")
    if len(name) > 255:
        raise HTTPException(
            status_code=422, detail="El nombre no puede pasar de 255 caracteres"
        )
    # Es un nombre que se dibuja en la pantalla, no una ruta: una barra
    # convertiría un renombre en un salto a otra carpeta.
    if "/" in name or "\\" in name or not name.isprintable():
        raise HTTPException(
            status_code=422, detail="El nombre no puede contener barras"
        )

    rows = ledger.rename_document(job_id, name)
    job = registry.get(job_id)
    if job is not None:
        job.filename = name
        registry.publish(job)
    if rows == 0 and job is None:
        raise HTTPException(status_code=404, detail="El documento no existe")
    return {"job_id": job_id, "source_document": name, "rows": rows}


#: Cuántos documentos admite un borrado en lote. El tope no es una limitación
#: de la máquina sino del gesto: quinientos son más de los que nadie marca a
#: mano, y una petición mayor casi siempre es un error de quien la construyó.
MAX_BULK_DELETE = 500


def _erase_document(job_id: str) -> dict[str, object]:
    """Borrar un documento entero: sus PDF, sus filas y su ficha.

    Devuelve lo que se borró, y levanta ``HTTPException`` cuando no se puede.
    El borrado de uno solo la deja pasar para responder con el código correcto;
    el borrado en lote la captura y la convierte en el motivo de esa fila.
    """
    job = registry.get(job_id)
    directory = settings.output_dir / job_id
    recorded = job_id in ledger.job_ids()
    if job is None and not recorded and not directory.is_dir():
        raise HTTPException(status_code=404, detail="El documento no existe")

    # Se comprueba antes de borrar nada: un documento a medio procesar todavía
    # está escribiendo en esa carpeta.
    if job is not None and registry.remove(job_id) is None:
        raise HTTPException(
            status_code=409, detail="El documento todavía se está procesando"
        )

    rows = ledger.remove_document(job_id)
    _discard_outputs(job_id)
    return {"job_id": job_id, "rows": rows, "from_screen": job is not None}


@app.delete("/api/documents/{job_id}")
async def delete_document(job_id: str) -> dict[str, object]:
    """Erase a processed document: its PDFs, its inventory rows and its card.

    This is the one deletion that leaves nothing behind, which is why it is a
    separate route from clearing the screen: clearing forgets a job and keeps
    the work, this discards the work itself.
    """
    return _erase_document(job_id)


@app.delete("/api/documents")
async def delete_documents(payload: dict) -> dict[str, object]:
    """Borrar varios documentos de una vez, diciendo qué pasó con cada uno.

    Va uno por uno y sigue adelante cuando alguno falla. No es una transacción y
    no debe parecerlo: borrar un documento son varias operaciones sobre disco y
    sobre el inventario, y fingir que veinte ocurren a la vez sólo serviría para
    que un fallo a la mitad dejara al operador sin saber qué se borró. Cada fila
    del resultado dice lo suyo, y la pantalla las enseña.

    El caso que de verdad importa es el documento que todavía se está
    procesando: se rechaza ése y se borran los demás, en vez de negar el lote
    entero por culpa de uno.
    """
    crudos = payload.get("job_ids")
    if not isinstance(crudos, list) or not crudos:
        raise HTTPException(
            status_code=422, detail="Hay que indicar qué documentos borrar"
        )
    if len(crudos) > MAX_BULK_DELETE:
        raise HTTPException(
            status_code=422,
            detail=f"Demasiados documentos de una vez: el máximo es {MAX_BULK_DELETE}",
        )

    borrados: list[dict[str, object]] = []
    fallidos: list[dict[str, object]] = []

    # Los repetidos se descartan conservando el orden de llegada: la pantalla
    # enseña el resultado en el mismo orden en que se marcaron las casillas.
    vistos: set[str] = set()
    for crudo in crudos:
        job_id = str(crudo or "").strip()
        if not job_id or job_id in vistos:
            continue
        vistos.add(job_id)
        try:
            borrados.append(_erase_document(job_id))
        except HTTPException as error:
            fallidos.append({"job_id": job_id, "reason": str(error.detail)})
        except Exception as error:  # noqa: BLE001 - uno que falla no para el lote
            logger.warning("no se pudo borrar el documento %s", job_id, exc_info=True)
            fallidos.append(
                {"job_id": job_id, "reason": f"{type(error).__name__}: {error}"}
            )

    return {
        "deleted": borrados,
        "failed": fallidos,
        "rows": sum(int(item["rows"] or 0) for item in borrados),
    }


@app.get("/api/inventory.xlsx")
async def inventory_xlsx(q: str | None = None) -> Response:
    """Todo el inventario en un libro con formato, no en un CSV pelado.

    Un CSV se abre en Excel como texto crudo: sin anchos, sin bordes, sin
    encabezado, y con los números de resolución convertidos en números -- que es
    como 00072 se vuelve 72 y deja de servir. El libro llega ya formateado y
    listo para imprimir.
    """
    rows = ledger.rows()
    if q:
        needle = q.strip().lower()
        rows = [row for row in rows if _matches(row, needle)]

    try:
        from ..adapters.excel_inventory import ExcelRunInventory
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="El inventario en Excel necesita openpyxl instalado en el servicio",
        ) from None

    # El adaptador escribe en disco; se le da una carpeta que se borra sola.
    with tempfile.TemporaryDirectory() as folder:
        written = ExcelRunInventory().write(
            rows,
            Path(folder),
            source=f"Inventario completo{f' — filtro: {q}' if q else ''}",
            delivered_to="cada resolución en la carpeta de su documento",
        )
        content = written.read_bytes()

    return Response(
        content=content,
        media_type=XLSX_MEDIA,
        headers={"Content-Disposition": 'attachment; filename="inventario.xlsx"'},
    )


@app.get("/api/inventory.csv")
async def inventory_csv(q: str | None = None) -> Response:
    rows = ledger.rows()
    if q:
        needle = q.strip().lower()
        rows = [row for row in rows if _matches(row, needle)]
    return Response(
        # The BOM is what makes Excel open a UTF-8 CSV without mangling accents,
        # and a spreadsheet is where this file is actually read.
        content="﻿" + ledger.as_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="inventario.csv"'},
    )


MAX_OPERATOR = 60


def _operator(raw: str | None) -> str | None:
    """Accept a name from the browser, trimmed and bounded.

    Percent-encoded on the way in, because HTTP header values are ASCII and
    half the names in this building carry an accent -- Martínez, Muñoz, María.
    Sending one raw throws in the browser before the request is even made.

    It arrives from a field anyone can type into, so it is treated as a label:
    decoded, trimmed, capped, never interpreted. A name is not a credential and
    nothing downstream may act as though it were.
    """
    if not raw:
        return None
    try:
        name = unquote(raw)
    except Exception:  # noqa: BLE001 - a malformed name is still just a label
        name = raw
    return name.strip()[:MAX_OPERATOR] or None


def _matches(row: dict, needle: str) -> bool:
    return any(
        needle in str(row.get(field) or "").lower()
        for field in ("code", "title", "source_document", "file_name", "operator")
    )


# -- housekeeping --------------------------------------------------------------


@app.get("/api/cache")
async def cache_status() -> dict[str, object]:
    return {
        "idle": registry.pending == 0,
        "would_sweep": janitor.should_sweep(),
        "last_sweep": janitor.last.as_dict() if janitor.last else None,
        "interval_seconds": settings.sweep_seconds,
    }


@app.post("/api/cache/sweep")
async def sweep_cache() -> dict[str, object]:
    """Run the idle sweep now, if the queue allows it."""
    result = await janitor.sweep_if_idle(force=True)
    if result is None:
        return {"swept": False, "reason": "hay documentos en proceso"}
    return {"swept": True, **result.as_dict()}


#: El tipo que hace que Windows abra el archivo con Excel en vez de preguntar.
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: Cómo se llama la hoja que el adaptador deja junto a los PDF generados. Vive
#: aquí duplicado porque abrir `excel_inventory` exige openpyxl, y el servicio
#: tiene que arrancar igual sin él; una prueba comprueba que los dos coincidan.
SHEET_SUFFIX = "__inventario.xlsx"

_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".json": "application/json",
    ".csv": "text/csv",
    ".xlsx": XLSX_MEDIA,
}


@app.get("/api/jobs/{job_id}/inventory.xlsx")
async def job_inventory(job_id: str) -> FileResponse:
    """El inventario de un solo documento, tal como se dejó junto a sus PDF.

    Es la hoja que el adaptador ya escribió durante el proceso, no una copia
    armada aquí: lo que se descarga es exactamente el archivo que quedó en la
    carpeta de destino, así que nadie tiene que preguntarse cuál de los dos vale.
    """
    directory = (settings.output_dir / job_id).resolve()
    sheets = sorted(directory.glob(f"*{SHEET_SUFFIX}")) if directory.is_dir() else []
    if not sheets:
        raise HTTPException(
            status_code=404,
            detail="Ese documento no tiene inventario en Excel",
        )
    return FileResponse(sheets[0], media_type=XLSX_MEDIA, filename=sheets[0].name)


def _fuid_de(job_id: str) -> Path | None:
    """La planilla FUID escrita para un documento, si la hay."""
    directorio = (settings.output_dir / job_id).resolve()
    if not directorio.is_dir():
        return None
    hojas = sorted(directorio.glob(f"*{FUID_SUFFIX}"))
    return hojas[0] if hojas else None


def _fuente_de(job_id: str) -> Path | None:
    """El PDF del que salió el documento, si todavía está donde estaba.

    Una subida se borra al terminar su trabajo y un original de carpeta puede
    haberse apartado o borrado, según lo que el operador eligiera. Sin él no hay
    nada que leer, y decirlo es mejor que dejar el botón girando.
    """
    job = registry.get(job_id)
    if job is None:
        return None
    return job.source if job.source.is_file() else None


async def _levantar_fuid(job_id: str) -> None:
    """Leer el documento otra vez, sólo para su inventario.

    Es exactamente lo que hace la acción «Solo inventariar» de la pantalla de
    carga -- el mismo worker, la misma plantilla elegida por el tipo de documento
    que se reconozca -- aplicado a un documento que ya se procesó. No crea un
    trabajo nuevo ni toca el informe del que ya existe: deja una planilla más
    junto a los PDF que ese documento produjo.
    """
    job = registry.get(job_id)
    if job is None:
        app.state.fuid_jobs[job_id] = "El documento ya no está en la pantalla"
        return
    payload = {
        "job_id": job.id,
        "source": str(job.source),
        "filename": job.filename,
        "operator": job.operator,
        "task": str(TaskKind.INVENTORY),
        "settings": settings.as_worker_payload(),
        "progress_queue": app.state.progress_queue,
    }
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(app.state.pool, process_document_job, payload)
        app.state.fuid_jobs.pop(job_id, None)
    except Exception as error:  # noqa: BLE001 - se le dice al operador qué pasó
        logger.exception("no se pudo levantar el FUID de %s", job_id)
        app.state.fuid_jobs[job_id] = f"{type(error).__name__}: {error}"


@app.post("/api/jobs/{job_id}/fuid", status_code=202)
async def make_job_fuid(job_id: str) -> dict[str, object]:
    """Levantar el inventario de un documento que ya se procesó.

    El botón que lo llama no elige plantilla: la elige el tipo de documento que
    se reconoce al leerlo, igual que cuando se sube un archivo con la acción
    «Solo inventariar». Un libro de diplomas produce el FUID de diplomas y un
    legajo de resoluciones el genérico, sin que nadie tenga que acertar antes.

    Devuelve enseguida. Leer un libro de cuatrocientos folios son minutos, y
    dejar la petición HTTP abierta todo ese rato es cómo se pierde el resultado
    por un tiempo de espera de un intermediario.
    """
    existente = _fuid_de(job_id)
    if existente is not None:
        # Ya estaba: lo pidió con la acción de inventariar, o alguien pulsó el
        # botón antes. No se vuelve a leer el documento para producir lo mismo.
        return {"ready": True, "name": existente.name, "error": None}

    if job_id in app.state.fuid_jobs and app.state.fuid_jobs[job_id] is None:
        return {"ready": False, "name": None, "error": None}

    if _fuente_de(job_id) is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "El documento de origen ya no está disponible, así que no se "
                "puede volver a leer para inventariarlo. Vuelva a cargarlo con "
                "la acción «Solo inventariar»."
            ),
        )

    app.state.fuid_jobs[job_id] = None
    asyncio.create_task(_levantar_fuid(job_id))
    return {"ready": False, "name": None, "error": None}


@app.get("/api/jobs/{job_id}/fuid")
async def job_fuid_status(job_id: str) -> dict[str, object]:
    """Si el inventario de un documento ya está escrito, y si algo falló."""
    error = app.state.fuid_jobs.get(job_id)
    hoja = _fuid_de(job_id)
    return {
        "ready": hoja is not None,
        "name": hoja.name if hoja else None,
        "error": error,
        "working": job_id in app.state.fuid_jobs and error is None and hoja is None,
    }


@app.get("/api/jobs/{job_id}/fuid.xlsx")
async def job_fuid(job_id: str) -> FileResponse:
    """El Formato Único de Inventario Documental de un documento inventariado.

    Es la planilla oficial que el worker rellenó al procesarlo, no una armada
    aquí: se descarga el archivo que quedó escrito, para que lo que se firma y
    lo que está en disco no puedan discrepar.
    """
    directory = (settings.output_dir / job_id).resolve()
    hojas = sorted(directory.glob(f"*{FUID_SUFFIX}")) if directory.is_dir() else []
    if not hojas:
        raise HTTPException(
            status_code=404,
            detail=(
                "Ese documento no tiene un FUID. Sólo lo tienen los que se "
                "procesaron con la acción «Solo inventariar»."
            ),
        )
    return FileResponse(hojas[0], media_type=XLSX_MEDIA, filename=hojas[0].name)


@app.get("/api/jobs/{job_id}/outputs/{name}")
async def download(job_id: str, name: str) -> FileResponse:
    # Deliberately not gated on the job still being in the registry: the
    # inventory outlives the screen, and its rows link straight at these files.
    # Containment below is what makes serving by id alone safe.
    directory = (settings.output_dir / job_id).resolve()
    target = (directory / name).resolve()
    # Containment check: the job id and file name both arrive from the client.
    if not target.is_file() or directory not in target.parents:
        raise HTTPException(status_code=404, detail="El archivo no existe")

    media_type = _MEDIA_TYPES.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(target, media_type=media_type, filename=target.name)


# -- live stream --------------------------------------------------------------


@app.get("/api/events")
async def events() -> StreamingResponse:
    queue = registry.subscribe()

    async def stream():
        try:
            # Replay current state on connect, so a tab that reconnects after a
            # dropped socket resynchronises without any extra request.
            for job in registry.list():
                yield _sse(job.as_dict())
            for run in folders.list():
                yield _sse(run.as_dict())
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(payload)
        finally:
            registry.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _drain_progress(app: FastAPI) -> None:
    """Move worker events onto the registry as fast as they arrive.

    The queue read is blocking, so it runs on a thread; folding the event into
    registry state is cheap and stays on the loop.
    """
    loop = asyncio.get_running_loop()
    queue = app.state.progress_queue
    while True:
        try:
            event = await loop.run_in_executor(None, queue.get)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - manager gone during shutdown
            return
        if event is None:
            return
        registry.apply_progress(event)


async def _publish_progress() -> None:
    """Push whatever changed, at a cadence a browser can actually render.

    Y, más despacio, lo que no ha cambiado. Un trabajo dentro de una fase larga
    no ensucia nada durante decenas de segundos, así que sin este segundo pulso
    la pantalla se queda con la última trama que recibió: el reloj detenido y
    ninguna forma de saber si el proceso sigue vivo.
    """
    desde_el_latido = 0.0
    while True:
        await asyncio.sleep(PUBLISH_INTERVAL)
        try:
            registry.flush()
            desde_el_latido += PUBLISH_INTERVAL
            if desde_el_latido >= HEARTBEAT_PUBLISH_SECONDS:
                desde_el_latido = 0.0
                registry.heartbeat()
        except Exception:  # noqa: BLE001 - never let the ticker die
            logger.debug("progress flush failed", exc_info=True)


# -- plumbing -----------------------------------------------------------------


async def _stream_to_disk(file: UploadFile, destination: Path) -> int:
    """Copy the upload in chunks.

    A 400-page scan is comfortably hundreds of megabytes. Reading it into memory
    to write it straight back out would cap concurrent uploads at whatever RAM
    happens to be free.
    """
    written = 0
    with destination.open("wb") as sink:
        while chunk := await file.read(UPLOAD_CHUNK):
            written += len(chunk)
            if written > settings.max_upload_bytes:
                sink.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="El archivo es demasiado grande")
            sink.write(chunk)
    return written


async def _run(job: Job) -> None:
    # Un trabajo cancelado mientras esperaba en la cola no llega a empezar.
    if app.state.controls.get(job.id) == str(RunState.CANCELLED):
        registry.mark_cancelled(job)
        if job.owns_source:
            job.source.unlink(missing_ok=True)
        return

    app.state.controls[job.id] = str(RunState.RUNNING)
    registry.mark_running(job)
    loop = asyncio.get_running_loop()
    payload = {
        "job_id": job.id,
        "source": str(job.source),
        # The name the operator gave it, not the generated one it is stored as.
        "filename": job.filename,
        "operator": job.operator,
        "task": job.task,
        "settings": settings.as_worker_payload(),
        "progress_queue": app.state.progress_queue,
        "controls": app.state.controls,
    }
    try:
        report = await loop.run_in_executor(app.state.pool, process_document_job, payload)
        registry.mark_done(job, report)
        try:
            ledger.record(job.id, report, operator=job.operator, source_bytes=job.bytes)
        except Exception:  # noqa: BLE001 - the split succeeded either way
            logger.warning("could not record %s in the inventory", job.filename, exc_info=True)
    except Cancelled:
        # No es un fallo: es lo que el operador pidió. Se distingue de un error
        # porque un lote con documentos cancelados no está roto.
        logger.info("job %s cancelled by the operator", job.id)
        registry.mark_cancelled(job)
    except Exception as error:  # noqa: BLE001 - surfaced to the operator verbatim
        # One document failing is one document failing. The batch carries on.
        logger.exception("job %s failed", job.id)
        registry.mark_failed(job, f"{type(error).__name__}: {error}")
    finally:
        app.state.controls.pop(job.id, None)
        if job.owns_source:
            job.source.unlink(missing_ok=True)
