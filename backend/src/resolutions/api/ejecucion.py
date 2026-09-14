"""Correr un trabajo: el único camino por el que un documento se procesa.

Lo usan la subida y la corrida de carpeta, y por eso vive aparte de los dos:
un documento se procesa igual llegue como llegue.
"""

from __future__ import annotations

import asyncio
import logging

from ..application.control import Cancelled, RunState
from .contexto import Contexto
from .jobs import Job

logger = logging.getLogger(__name__)


async def _run(ctx: Contexto, job: Job) -> None:
    # Un trabajo cancelado mientras esperaba en la cola no llega a empezar.
    if ctx.controls.get(job.id) == str(RunState.CANCELLED):
        ctx.registry.mark_cancelled(job)
        if job.owns_source:
            job.source.unlink(missing_ok=True)
        return

    ctx.controls[job.id] = str(RunState.RUNNING)
    ctx.registry.mark_running(job)
    loop = asyncio.get_running_loop()
    payload = {
        "job_id": job.id,
        "source": str(job.source),
        # The name the operator gave it, not the generated one it is stored as.
        "filename": job.filename,
        "operator": job.operator,
        "task": job.task,
        "oracle": job.oracle,
        # Dónde quedará la entrega, cuando el trabajo viene de una carpeta. La
        # planilla lo escribe en su columna de destino.
        "destination": job.destination,
        "settings": ctx.settings.as_worker_payload(),
        "progress_queue": ctx.progress_queue,
        "controls": ctx.controls,
    }
    try:
        report = await loop.run_in_executor(ctx.pool, ctx.procesar, payload)
        ctx.registry.mark_done(job, report)
        try:
            ctx.ledger.record(job.id, report, operator=job.operator, source_bytes=job.bytes)
        except Exception:  # noqa: BLE001 - the split succeeded either way
            logger.warning("could not record %s in the inventory", job.filename, exc_info=True)
    except Cancelled:
        # No es un fallo: es lo que el operador pidió. Se distingue de un error
        # porque un lote con documentos cancelados no está roto.
        logger.info("job %s cancelled by the operator", job.id)
        ctx.registry.mark_cancelled(job)
    except Exception as error:  # noqa: BLE001 - surfaced to the operator verbatim
        # One document failing is one document failing. The batch carries on.
        logger.exception("job %s failed", job.id)
        ctx.registry.mark_failed(job, f"{type(error).__name__}: {error}")
    finally:
        ctx.controls.pop(job.id, None)
        if job.owns_source:
            job.source.unlink(missing_ok=True)
