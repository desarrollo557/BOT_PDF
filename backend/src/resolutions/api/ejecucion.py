"""Correr un trabajo: el único camino por el que un documento se procesa.

Lo usan la subida y la corrida de carpeta, y por eso vive aparte de los dos:
un documento se procesa igual llegue como llegue.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext

from ..application.control import Cancelled, RunState
from ..domain.naming import document_folder
from .contexto import Contexto
from .errores import explicar_fallo
from .indices import carpeta_del_lote, inventario_de_procesos, libro_de_indices
from .jobs import Job, JobState

logger = logging.getLogger(__name__)

#: Uno por lote: dos cajas del mismo lote que terminan a la vez no escriben el
#: mismo libro a la vez.
_LIBROS_DE_LOTE: dict[str, asyncio.Lock] = {}


async def _indice_del_lote(ctx: Contexto, batch_id: str) -> None:
    """Rehace los dos inventarios generales del lote, en su carpeta.

    * El de la **habilidad**: para las cajas de correspondencia, el Índice
      Electrónico del cliente con una hoja por PDF procesado.
    * El **general del bot**: una fila por cada PDF del lote -- qué habilidad
      lo atendió, con qué lectura, qué salió y cuánto costó --, termine bien o
      falle.

    El servicio no sabe cuántos PDF trae un lote -- llegan de uno en uno --, así
    que los libros se rehacen cada vez que termina uno. Siempre dicen todo lo
    terminado, y con el último quedan completos. Que fallen no toca la entrega
    de cada PDF, que ya está en el disco.
    """
    lote = ctx.registry.get_batch(batch_id)
    if lote is None:
        return
    trabajos = [t for job_id in lote.job_ids if (t := ctx.registry.get(job_id)) is not None]
    con_indice = [
        t.id for t in trabajos if t.state is JobState.DONE and (t.report or {}).get("indice_electronico")
    ]
    carpeta = carpeta_del_lote(ctx.settings.output_dir, batch_id)
    candado = _LIBROS_DE_LOTE.setdefault(batch_id, asyncio.Lock())
    async with candado:
        try:
            if con_indice:
                await asyncio.to_thread(libro_de_indices, ctx.settings.output_dir, con_indice, carpeta)
            await asyncio.to_thread(
                inventario_de_procesos,
                trabajos,
                carpeta,
                origen=lote.name,
                clase_de_origen="Lote",
                operador=next((t.operator for t in trabajos if t.operator), None),
                destino_de=lambda t: document_folder(t.filename),
            )
        except Exception:  # noqa: BLE001 - los PDF ya están entregados
            logger.warning("no se pudieron escribir los inventarios del lote %s", batch_id, exc_info=True)


async def _run(ctx: Contexto, job: Job) -> None:
    # Un trabajo cancelado mientras esperaba en la cola no llega a empezar.
    if ctx.controls.get(job.id) == str(RunState.CANCELLED):
        ctx.registry.mark_cancelled(job)
        if job.owns_source:
            job.source.unlink(missing_ok=True)
        return

    # El planificador dice cuántos hilos de OCR le tocan con lo que ya corre:
    # uno solo usa todos los configurados; varios a la vez se los reparten.
    planificador = getattr(ctx, "planificador", None)
    turno = (
        planificador.documento()
        if planificador is not None
        else nullcontext(getattr(ctx.settings, "page_workers", None))
    )
    with turno as hilos:
        await _correr(ctx, job, hilos)


async def _correr(ctx: Contexto, job: Job, hilos: int | None) -> None:
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
        # Con qué leer. Viaja con el trabajo y no se toma de los ajustes del
        # servicio: el operador lo eligió para este documento, y dos documentos
        # de la misma cola pueden querer motores distintos.
        "lectura": job.lectura,
        "corte": job.corte,
        # Qué se entrega como un archivo en una caja de correspondencia.
        "agrupar": job.agrupar,
        # Y la territorial que va al encabezado del Índice Electrónico.
        "territorial": job.territorial,
        # Y qué dijo el operador que es. Va con el trabajo porque decide a qué
        # habilidad entra, que es la decisión más consecuente de todas.
        "tipo": job.tipo,
        # Dónde quedará la entrega, cuando el trabajo viene de una carpeta. La
        # planilla lo escribe en su columna de destino.
        "destination": job.destination,
        "settings": {
            **ctx.settings.as_worker_payload(),
            **({"page_workers": hilos} if hilos else {}),
        },
        "progress_queue": ctx.progress_queue,
        "controls": ctx.controls,
        # El tope común de llamadas a la IA, que comparten todos los procesos.
        "turnos_de_ia": getattr(ctx, "turnos_de_ia", None),
    }
    futuro = loop.run_in_executor(ctx.pool, ctx.procesar, payload)
    try:
        try:
            # Protegido: si quien espera se va -- detener una carpeta cancela su
            # tarea --, el documento no puede quedarse leyéndose en el worker
            # sin nadie que lo mire. Se le da la orden de parar y otro se queda
            # esperando a que la atienda, que es cuestión de décimas.
            report = await asyncio.shield(futuro)
        except asyncio.CancelledError:
            ctx.controls[job.id] = str(RunState.CANCELLED)
            ctx.registry.mark_cancelled(job)
            loop.create_task(_soltar(ctx, job, futuro))
            raise
        if job.state is JobState.CANCELLED:
            # El operador lo canceló y el worker terminó antes de enterarse: se
            # queda cancelado, que es lo que la pantalla ya le enseñó.
            return
        # Con el informe viaja de qué carpeta o lote salió, que es lo que el
        # inventario anota para que el Archivo pueda reunirlos después.
        if job.origen and isinstance(report, dict):
            report.setdefault("origen", job.origen)
        ctx.registry.mark_done(job, report)
        try:
            ctx.ledger.record(job.id, report, operator=job.operator, source_bytes=job.bytes)
        except Exception:  # noqa: BLE001 - the split succeeded either way
            logger.warning("could not record %s in the inventory", job.filename, exc_info=True)
    except Cancelled:
        # No es un fallo: es lo que el operador pidió. Se distingue de un error
        # porque un lote con documentos cancelados no está roto.
        logger.info("job %s cancelled by the operator", job.id)
        if job.state is not JobState.CANCELLED:
            ctx.registry.mark_cancelled(job)
    except Exception as error:  # noqa: BLE001 - surfaced to the operator verbatim
        if job.state is JobState.CANCELLED:
            return
        # One document failing is one document failing. The batch carries on.
        logger.exception("job %s failed", job.id)
        ctx.registry.mark_failed(job, explicar_fallo(error))
    finally:
        # Si se abandonó la espera, limpia `_soltar` cuando el worker suelte el
        # documento: quitar antes la orden de cancelar lo dejaba leyendo.
        if futuro.done():
            _limpiar(ctx, job)
    # Los inventarios generales del lote, con este PDF ya contado -- también si
    # falló: el general del bot dice qué no salió y por qué --.
    if job.batch_id:
        await _indice_del_lote(ctx, job.batch_id)


async def _soltar(ctx: Contexto, job: Job, futuro) -> None:
    """Espera a que el worker suelte un documento abandonado, y limpia."""
    try:
        await futuro
    except BaseException:  # noqa: BLE001 - lo que diga ya no le importa a nadie
        logger.debug("el trabajo %s soltado terminó con error", job.id, exc_info=True)
    finally:
        _limpiar(ctx, job)


def _limpiar(ctx: Contexto, job: Job) -> None:
    ctx.controls.pop(job.id, None)
    if job.owns_source:
        job.source.unlink(missing_ok=True)
