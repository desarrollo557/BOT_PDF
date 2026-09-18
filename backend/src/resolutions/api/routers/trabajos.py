"""Los trabajos: subir un PDF, seguirlo, detenerlo y quitarlo de la pantalla."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, UploadFile

from ...application.control import RunState
from ...application.lectura import LecturaChoice
from ...application.oracle import OracleChoice
from ...application.task import TaskKind
from ...application.tipo_pedido import TipoPedido
from ..contexto import Contexto, Ctx
from ..ejecucion import _run
from ..jobs import IN_FLIGHT, Job, JobState

logger = logging.getLogger(__name__)

router = APIRouter()


UPLOAD_CHUNK = 1024 * 1024

@router.post("/api/jobs", status_code=202)
async def enqueue(
    ctx: Ctx,
    file: UploadFile,
    batch_id: str | None = None,
    task: str | None = None,
    oracle: str | None = None,
    lectura: str | None = None,
    tipo: str | None = None,
    x_operator: str | None = Header(default=None),
) -> dict[str, object]:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Solo se aceptan archivos PDF")
    try:
        kind = TaskKind.parse(task)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    # Antes de escribir un solo byte: el cuerpo de esta petición es el archivo, y
    # una caja escaneada son cientos de megabytes. Una elección imposible tiene
    # que costar un 422 y no un archivo en disco que nadie va a procesar.
    choice = _oracle_choice(ctx, oracle)
    lectura_choice = _lectura_choice(ctx, lectura)
    tipo_choice = _tipo_choice(tipo)
    if batch_id and ctx.registry.get_batch(batch_id) is None:
        raise HTTPException(status_code=404, detail="El lote no existe")
    if ctx.registry.pending >= ctx.settings.queue_limit:
        # Push back rather than accumulate. A queue that grows without bound is a
        # queue that lies about how long the work will take.
        raise HTTPException(
            status_code=429, detail="La cola está llena, reintentá en unos instantes"
        )

    destination = ctx.settings.upload_dir / f"{uuid4().hex}.pdf"
    written = await _stream_to_disk(ctx, file, destination)
    if written == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="El archivo llegó vacío")

    job = ctx.registry.create(
        filename=file.filename or destination.name,
        source=destination,
        batch_id=batch_id,
        size=written,
        operator=_operator(x_operator),
        task=str(kind),
        oracle=str(choice),
        lectura=str(lectura_choice),
        tipo=str(tipo_choice),
    )
    ctx.registry.publish(job)
    asyncio.create_task(_run(ctx, job))
    return {
        "id": job.id,
        "batch_id": job.batch_id,
        "state": str(job.state),
        "task": job.task,
        "oracle": job.oracle,
        "lectura": job.lectura,
        "tipo": job.tipo,
        "bytes": written,
    }

def _tipo_choice(value: str | None) -> TipoPedido:
    """Qué declaró el operador estar cargando.

    No se comprueba contra ninguna llave -- declarar un tipo no consume nada --
    pero sí que sea uno de los que el sistema sabe atender: un tipo inventado
    llegaría al despachador como "auto" y el operador creería haber elegido.
    """
    try:
        return TipoPedido.parse(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _lectura_choice(ctx: Contexto, value: str | None) -> LecturaChoice:
    """Con qué motor se pidió leer, o por qué no se puede pedir.

    Se comprueba antes de escribir un byte, igual que la elección de modelo y
    por el mismo motivo: el cuerpo de esta petición es el archivo, y una caja
    escaneada son cientos de megabytes. Descubrir que falta la llave después de
    recibirla sería gastarle al operador la subida entera.
    """
    try:
        choice = LecturaChoice.parse(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if not choice.is_available(ctx.settings.as_worker_payload()):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{choice.label} no está configurado: falta {choice.env_var} en el "
                "entorno del servicio. Elegir un motor de lectura no sustituye por "
                "otro, así que la caja no se procesó."
            ),
        )
    return choice


def _oracle_choice(ctx: Contexto, value: str | None) -> OracleChoice:
    """Qué modelo se pidió, o por qué no se puede pedir.

    Un proveedor sin su llave se rechaza en vez de resolverse con otro. Si
    alguien pide Mistral y el sistema contesta con Gemini, el informe miente
    sobre quién decidió los cortes, y un corte cuya autoría no se puede rastrear
    no sirve para decidir si el criterio funciona.

    El mensaje nombra la variable de entorno que falta: un 422 que sólo dice "no
    configurado" manda al operador a leer el código fuente.
    """
    try:
        choice = OracleChoice.parse(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if not choice.is_available(ctx.settings.as_worker_payload()):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{choice.label} no está configurado: falta {choice.env_var} en el "
                "entorno del servicio. Elegir un modelo no sustituye por otro, así "
                "que la caja no se procesó."
            ),
        )
    return choice

def _steer(ctx: Contexto, job_id: str, state: RunState) -> Job:
    """Cambia el rumbo de un trabajo en curso, o dice por qué no se puede."""
    job = ctx.registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="El documento no existe")
    if job.state not in IN_FLIGHT:
        raise HTTPException(
            status_code=409,
            detail=f"El documento ya terminó ({job.state}); no hay nada que detener",
        )
    ctx.controls[job_id] = str(state)
    return job

@router.post("/api/jobs/{job_id}/pause")
async def pause_job(ctx: Ctx, job_id: str) -> dict[str, object]:
    """Detener el trabajo entre una página y la siguiente.

    No mata nada: el worker sigue vivo con el documento abierto, y por eso
    reanudar continúa por donde iba en vez de empezar de nuevo. La orden tarda
    lo que tarde la página en curso, que con OCR es alrededor de un segundo.
    """
    job = _steer(ctx, job_id, RunState.PAUSED)
    if job.state is JobState.RUNNING:
        ctx.registry.mark_paused(job)
    return {"id": job.id, "state": str(job.state)}

@router.post("/api/jobs/{job_id}/resume")
async def resume_job(ctx: Ctx, job_id: str) -> dict[str, object]:
    job = _steer(ctx, job_id, RunState.RUNNING)
    if job.state is JobState.PAUSED:
        ctx.registry.mark_resumed(job)
    return {"id": job.id, "state": str(job.state)}

@router.post("/api/jobs/{job_id}/cancel")
async def cancel_job(ctx: Ctx, job_id: str) -> dict[str, object]:
    """Abandonar el trabajo. Lo que ya se escribió se conserva y se declara."""
    job = _steer(ctx, job_id, RunState.CANCELLED)
    return {"id": job.id, "state": str(job.state), "cancelling": True}

@router.get("/api/jobs")
async def list_jobs(ctx: Ctx) -> dict[str, object]:
    return {"jobs": [job.as_dict() for job in ctx.registry.list()]}

@router.get("/api/jobs/{job_id}")
async def get_job(ctx: Ctx, job_id: str) -> dict[str, object]:
    job = ctx.registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="El trabajo no existe")
    return job.as_dict()

@router.patch("/api/jobs/{job_id}")
async def rename_job(ctx: Ctx, job_id: str, payload: dict) -> dict[str, object]:
    """Rename a document on screen. The generated files keep their own names."""
    job = ctx.registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="El trabajo no existe")
    filename = str(payload.get("filename") or "").strip()
    if not filename:
        raise HTTPException(status_code=422, detail="El nombre no puede quedar vacio")
    job.filename = filename
    ctx.registry.publish(job)
    return job.as_dict()

@router.delete("/api/jobs")
async def clear_jobs(ctx: Ctx) -> dict[str, object]:
    """Clear the screen: forget finished documents.

    Only done and failed jobs go, so clearing during a batch never costs work
    already under way. The generated PDFs stay on disk and the inventory keeps
    its rows -- this empties a screen, it does not undo the work.
    """
    removed = ctx.registry.remove_finished()
    return {"removed": len(removed), "ids": [job.id for job in removed]}

@router.delete("/api/jobs/{job_id}")
async def delete_job(ctx: Ctx, job_id: str, purge: bool = False) -> dict[str, object]:
    """Forget one document. With ``purge``, delete its generated PDFs as well."""
    job = ctx.registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="El trabajo no existe")
    if ctx.registry.remove(job_id) is None:
        raise HTTPException(
            status_code=409, detail="El documento todavía se está procesando"
        )
    if purge:
        _discard_outputs(ctx, job_id)
    return {"removed": 1, "ids": [job_id], "purged": purge}

def _discard_outputs(ctx: Contexto, job_id: str) -> None:
    """Delete one job's output directory. Never allowed to fail the request."""
    directory = (ctx.settings.output_dir / job_id).resolve()
    if directory.parent != ctx.settings.output_dir.resolve():
        return
    shutil.rmtree(directory, ignore_errors=True)

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

async def _stream_to_disk(ctx: Contexto, file: UploadFile, destination: Path) -> int:
    """Copy the upload in chunks.

    A 400-page scan is comfortably hundreds of megabytes. Reading it into memory
    to write it straight back out would cap concurrent uploads at whatever RAM
    happens to be free.
    """
    written = 0
    with destination.open("wb") as sink:
        while chunk := await file.read(UPLOAD_CHUNK):
            written += len(chunk)
            if written > ctx.settings.max_upload_bytes:
                sink.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="El archivo es demasiado grande")
            sink.write(chunk)
    return written
