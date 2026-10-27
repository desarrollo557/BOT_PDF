"""Correr un trabajo: el único camino por el que un documento se procesa.

Lo usan la subida y la corrida de carpeta, y por eso vive aparte de los dos:
un documento se procesa igual llegue como llegue.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import nullcontext

from ..application.control import Cancelled, RunState
from ..domain.naming import document_folder
from .contexto import Contexto
from .errores import explicar_fallo
from .indices import (
    carpeta_del_lote,
    fuid_general,
    inventario_de_procesos,
    libro_de_indices,
)
from .jobs import Job, JobProgress, JobState
from .reintentos import (
    es_transitorio,
    espera_antes_del_intento,
    merece_otra_vuelta,
    pide_otro_pool,
)

logger = logging.getLogger(__name__)

#: Uno por lote: dos cajas del mismo lote que terminan a la vez no escriben el
#: mismo libro a la vez.
_LIBROS_DE_LOTE: dict[str, asyncio.Lock] = {}


async def _indice_del_lote(ctx: Contexto, batch_id: str) -> None:
    """Rehace los dos inventarios generales del lote, en su carpeta.

    * El de la **habilidad**: para las cajas de correspondencia, el Índice
      Electrónico del cliente con una hoja por PDF procesado.
      Para los libros de diplomas, un solo FUID con una fila por diploma.
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
                fuid_general,
                ctx.settings.output_dir,
                trabajos,
                carpeta,
                destino_de=lambda t: document_folder(t.filename),
            )
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


#: El cupo de cada lote -- o de las cargas sueltas -- cuando el operador eligió
#: cuántos archivos a la vez: (cuántos, semáforo).
_CUPOS: dict[str, tuple[int, asyncio.Semaphore]] = {}


def _cupo(job: Job):
    """El semáforo del lote del trabajo, o nada si se dejó en automático."""
    if not job.paralelo:
        return nullcontext()
    clave = job.batch_id or "sueltos"
    cuantos, semaforo = _CUPOS.get(clave, (0, None))
    if semaforo is None or cuantos != job.paralelo:
        # Otra cifra para el mismo lote: vale para lo que entre desde ahora.
        semaforo = asyncio.Semaphore(job.paralelo)
        _CUPOS[clave] = (job.paralelo, semaforo)
    return semaforo


async def _run(ctx: Contexto, job: Job) -> None:
    # Los archivos a la vez que eligió el operador para su lote: los demás
    # esperan su turno en cola, sin ocupar un proceso del pool.
    try:
        async with _cupo(job):
            corrio = await _run_con_cupo(ctx, job)
        # Los inventarios generales del lote, con este PDF ya contado --
        # también si falló: el general del bot dice qué no salió y por qué --.
        # Fuera del cupo y del turno: rehacerlos relee los de todo el lote, y
        # con la ranura tomada el siguiente PDF esperaba y el planificador
        # repartía los hilos como si éste siguiera leyendo (2026-10-27).
        if corrio and job.batch_id:
            await _indice_del_lote(ctx, job.batch_id)
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 - el trabajo termina, nunca queda en cola
        # Lo que falla antes de llegar al pool -- el canal de control caído, el
        # payload que no se arma -- mataba la tarea de una subida sin que nadie
        # la recogiera: el trabajo se quedaba «en cola» o «en curso» para
        # siempre (2026-10-27). Termina como fallido, con su motivo y con la
        # misma vuelta de reintento que cualquier otro fallo.
        logger.exception("el trabajo %s falló fuera del pool", job.filename)
        if job.state in (JobState.QUEUED, JobState.RUNNING, JobState.PAUSED):
            job.reintentable = merece_otra_vuelta(error)
            ctx.registry.mark_failed(job, explicar_fallo(error))


async def _run_con_cupo(ctx: Contexto, job: Job) -> bool:
    """Lee el documento con su turno del planificador. ``False`` si no llegó a empezar."""
    # Un trabajo cancelado mientras esperaba en la cola no llega a empezar.
    if ctx.controls.get(job.id) == str(RunState.CANCELLED):
        ctx.registry.mark_cancelled(job)
        if job.owns_source:
            job.source.unlink(missing_ok=True)
        return False

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
    return True


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
        # Y el acta de transferencia del inventario de Kingspan, que tampoco
        # está en el papel.
        "acta": job.acta,
        # Y de qué carpeta salió, cuando viene de una corrida: el inventario de
        # Kingspan toma la caja del nombre de la carpeta donde está el PDF, y
        # si el PDF está suelto en la carpeta elegida, ésa es la carpeta.
        "origen": job.origen,
        # Y qué dijo el operador que es. Va con el trabajo porque decide a qué
        # habilidad entra, que es la decisión más consecuente de todas.
        "tipo": job.tipo,
        # Y la plantilla de inventario que eligió, cuando la eligió: la caja de
        # correspondencia se inventaría de dos maneras distintas y el worker no
        # puede adivinarla sin arriesgar el flujo de las demás habilidades.
        "tipo_documento": job.tipo_documento,
        # Dónde quedará la entrega, cuando el trabajo viene de una carpeta. La
        # planilla lo escribe en su columna de destino.
        "destination": job.destination,
        # Y qué páginas leer, cuando se retoma un libro entregado a medias.
        **({"paginas": list(job.paginas)} if job.paginas else {}),
        "settings": {
            **ctx.settings.as_worker_payload(),
            **({"page_workers": hilos} if hilos else {}),
        },
        "progress_queue": ctx.progress_queue,
        "controls": ctx.controls,
        # El tope común de llamadas a la IA, que comparten todos los procesos.
        "turnos_de_ia": getattr(ctx, "turnos_de_ia", None),
    }
    maximo = 1 + max(0, int(getattr(ctx.settings, "reintentos", 0) or 0))
    futuro = None
    try:
        for intento in range(1, maximo + 1):
            job.intentos = intento
            pool = ctx.pool
            try:
                # Dentro del `try`: con el pool roto, mandar el trabajo ya falla,
                # y antes ese fallo dejaba el trabajo «en curso» para siempre.
                futuro = loop.run_in_executor(pool, ctx.procesar, payload)
                report = await _esperar(ctx, job, futuro, pool)
                break
            except (asyncio.CancelledError, Cancelled, TrabajoSinAvance):
                raise
            except Exception as error:  # noqa: BLE001 - se decide si se reintenta
                if job.state is JobState.CANCELLED or intento >= maximo or not es_transitorio(error):
                    raise
                if pide_otro_pool(error):
                    rehacer = getattr(ctx, "rehacer_pool", None)
                    if rehacer is not None:
                        rehacer(pool)
                espera = espera_antes_del_intento(intento + 1, float(getattr(ctx.settings, "espera_de_reintento", 0) or 0))
                motivo = explicar_fallo(error)
                logger.warning(
                    "%s falló (%s); intento %d de %d en %.0f s", job.filename, motivo, intento + 1, maximo, espera
                )
                job.progress.detail = f"Falló: {motivo} Se reintenta ({intento + 1} de {maximo}) en {espera:.0f} s."
                ctx.registry.publish(job)
                try:
                    await asyncio.sleep(espera)
                except asyncio.CancelledError:
                    # Detuvieron la carpeta mientras esperaba otro intento.
                    ctx.registry.mark_cancelled(job)
                    raise
                if ctx.controls.get(job.id) == str(RunState.CANCELLED):
                    # Y si lo canceló el operador, se queda cancelado.
                    raise Cancelled() from None
                ctx.controls[job.id] = str(RunState.RUNNING)
                # Las páginas se vuelven a contar desde cero en el intento nuevo.
                job.progress = JobProgress()
                ctx.registry.mark_running(job)
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
        job.reintentable = merece_otra_vuelta(error)
        ctx.registry.mark_failed(job, explicar_fallo(error))
    finally:
        # Si se abandonó la espera, limpia `_soltar` cuando el worker suelte el
        # documento: quitar antes la orden de cancelar lo dejaba leyendo.
        if futuro is None or futuro.done():
            _limpiar(ctx, job)


class TrabajoSinAvance(TimeoutError):
    """Un documento que lleva demasiado sin avanzar una página."""

    para_el_operador = True


#: Cada cuánto se mira, como mucho, si el documento sigue avanzando.
_VIGILANCIA = 30.0


async def _esperar(ctx: Contexto, job: Job, futuro, pool=None) -> dict:
    """El informe del worker, vigilando que el documento avance.

    Una página que el lector nativo no suelta, o una lectura de la red que no
    vuelve, dejaban el documento «en curso» para siempre y su ranura ocupada:
    unas pocas así paraban la carpeta entera sin un error que mirar. Si pasan
    ``minutos_sin_avance`` sin una página nueva, se le ordena parar, se
    abandona la espera y el documento falla diciendo por qué.
    """
    loop = asyncio.get_running_loop()
    limite = float(getattr(ctx.settings, "minutos_sin_avance", 0) or 0) * 60
    inicio = time.monotonic()
    try:
        while True:
            # `wait` no cancela lo que espera: si quien llama se va, el
            # documento sigue en el worker hasta que atienda la orden.
            hecho, _ = await asyncio.wait({futuro}, timeout=min(_VIGILANCIA, limite) if limite else None)
            if hecho:
                return futuro.result()
            # Desde la última noticia del worker, o desde que empezó si aún no
            # dio ninguna: uno que se atasca al abrir el PDF no avisa nunca.
            silencio = (
                job.progress.silent_seconds
                if job.progress.last_event_monotonic is not None
                else time.monotonic() - inicio
            )
            if limite and job.state is JobState.RUNNING and silencio >= limite:
                ctx.controls[job.id] = str(RunState.CANCELLED)
                loop.create_task(_soltar(ctx, job, futuro))
                if _pool_congelado(ctx, job, limite):
                    # No es este PDF: ninguno de los que corren avanza. Se matan
                    # los procesos y se levanta otro pool; los demás fallan con
                    # «pool roto», que se reintenta en el acto con el nuevo.
                    logger.error(
                        "ningún documento avanza desde hace %.0f min: se cambia el pool de procesos",
                        limite / 60,
                    )
                    rehacer = getattr(ctx, "rehacer_pool", None)
                    if rehacer is not None and pool is not None:
                        rehacer(pool, matar=True)
                raise TrabajoSinAvance(
                    f"El documento lleva {limite / 60:.0f} minutos sin avanzar una página y se "
                    "dio por atascado. Suele ser una página dañada o la red; vuelva a "
                    "procesarlo y, si se repite, revise el PDF."
                )
    except asyncio.CancelledError:
        ctx.controls[job.id] = str(RunState.CANCELLED)
        ctx.registry.mark_cancelled(job)
        loop.create_task(_soltar(ctx, job, futuro))
        raise


def _pool_congelado(ctx: Contexto, job: Job, limite: float) -> bool:
    """Si, además de este, ninguno de los documentos en curso avanza desde hace rato.

    El 2026-10-19 cinco libros de actas de grado se quedaron a la vez con todas
    sus páginas leídas y sin avanzar más: no era un PDF, era el pool. Con uno
    solo en curso no se sabe, y no se toca el pool.
    """
    listar = getattr(getattr(ctx, "registry", None), "snapshot", None)
    if listar is None:
        return False
    otros = [
        otro
        for otro in listar()
        if otro.id != job.id and otro.state is JobState.RUNNING and otro.progress.last_event_monotonic is not None
    ]
    return bool(otros) and all(otro.progress.silent_seconds >= limite / 2 for otro in otros)


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
