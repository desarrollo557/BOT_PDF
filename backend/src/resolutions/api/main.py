from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from .jobs import Job, JobRegistry
from .settings import Settings
from .worker import process_document_job

logger = logging.getLogger(__name__)

UPLOAD_CHUNK = 1024 * 1024
HEARTBEAT_SECONDS = 15.0

#: How often coalesced progress is pushed to the browser. A 400-page document
#: emits 400 events; a screen can usefully absorb four frames a second. Batching
#: at this cadence is what lets 50 documents stream at once without a flood.
PUBLISH_INTERVAL = 0.25
PROGRESS_QUEUE_SIZE = 20_000

settings = Settings.from_env()
registry = JobRegistry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_directories()

    # One process per document. Sized at cores-1 so the event loop always has a
    # core left to accept uploads while the pool is saturated.
    app.state.pool = ProcessPoolExecutor(max_workers=settings.document_workers)
    app.state.manager = multiprocessing.Manager()
    app.state.progress_queue = app.state.manager.Queue(maxsize=PROGRESS_QUEUE_SIZE)
    app.state.tasks = [
        asyncio.create_task(_drain_progress(app)),
        asyncio.create_task(_publish_progress()),
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
        "document_workers": settings.document_workers,
        "page_workers": settings.page_workers,
        "vision": "claude" if settings.anthropic_api_key else "disabled",
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


# -- jobs ---------------------------------------------------------------------


@app.post("/api/jobs", status_code=202)
async def enqueue(file: UploadFile, batch_id: str | None = None) -> dict[str, object]:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Solo se aceptan archivos PDF")
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
        filename=file.filename or destination.name, source=destination, batch_id=batch_id
    )
    registry.publish(job)
    asyncio.create_task(_run(job))
    return {"id": job.id, "batch_id": job.batch_id, "state": str(job.state), "bytes": written}


@app.get("/api/jobs")
async def list_jobs() -> dict[str, object]:
    return {"jobs": [job.as_dict() for job in registry.list()]}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, object]:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="El trabajo no existe")
    return job.as_dict()


_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".json": "application/json",
    ".csv": "text/csv",
}


@app.get("/api/jobs/{job_id}/outputs/{name}")
async def download(job_id: str, name: str) -> FileResponse:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="El trabajo no existe")

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
            for job in registry.list():
                yield _sse(job.as_dict())
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
    """Push whatever changed, at a cadence a browser can actually render."""
    while True:
        await asyncio.sleep(PUBLISH_INTERVAL)
        try:
            registry.flush()
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
    registry.mark_running(job)
    loop = asyncio.get_running_loop()
    payload = {
        "job_id": job.id,
        "source": str(job.source),
        "settings": settings.as_worker_payload(),
        "progress_queue": app.state.progress_queue,
    }
    try:
        report = await loop.run_in_executor(app.state.pool, process_document_job, payload)
        registry.mark_done(job, report)
    except Exception as error:  # noqa: BLE001 - surfaced to the operator verbatim
        # One document failing is one document failing. The batch carries on.
        logger.exception("job %s failed", job.id)
        registry.mark_failed(job, f"{type(error).__name__}: {error}")
    finally:
        job.source.unlink(missing_ok=True)
