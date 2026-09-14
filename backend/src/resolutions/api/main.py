"""La API del separador: el arranque, el estado compartido y los routers.

Aquí quedan tres cosas: construir el contexto con el que se atiende cada
petición, el ciclo de vida del servicio -- el pool de procesos, la cola de
progreso, el barrendero -- y los manejadores de error. Cada familia de rutas
vive en su router bajo `routers/`, y todos leen el estado del mismo sitio.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..adapters.ledger import InventoryLedger
from ..adapters.mysql_inventory import (
    InventoryUnavailable,
    MySQLInventory,
    settings_from_env,
)
from ..adapters.user_store import FileUserStore
from ..application.usuarios import Usuarios
from .contexto import Contexto
from .ejecucion import _run
from .errores import explicar_validacion
from .folders import FolderRunner
from .janitor import IdleJanitor
from .jobs import JobRegistry
from .routers import (
    archivo,
    carpetas,
    eventos,
    fuid,
    lotes,
    mantenimiento,
    salidas,
    salud,
    trabajos,
    usuarios,
)
from .settings import Settings
from .worker import process_document_job

logger = logging.getLogger(__name__)

#: How often folded progress is pushed to browsers. Four times a second is
#: smooth enough for a bar and cheap enough that 50 documents at once do not
#: drown the event loop in SSE frames.
PUBLISH_INTERVAL = 0.25
#: Cada cuánto se repite lo que no ha cambiado. Un trabajo dentro de una fase
#: larga no ensucia nada durante decenas de segundos, así que sin este pulso
#: la pantalla se queda con la última trama y ninguna forma de saber si sigue
#: vivo.
HEARTBEAT_PUBLISH_SECONDS = 2.0
PROGRESS_QUEUE_SIZE = 20_000


def _open_inventory(settings: Settings):
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


def _arrancar() -> Contexto:
    """El contexto con el que arranca el servicio, leído del entorno."""
    settings = Settings.from_env()
    registry = JobRegistry()
    ledger, backend = _open_inventory(settings)
    return Contexto(
        settings=settings,
        registry=registry,
        ledger=ledger,
        inventory_backend=backend,
        janitor=IdleJanitor(registry, settings, referenced=lambda: ledger.job_ids()),
        usuarios=Usuarios(FileUserStore(settings.users_path)),
        procesar=process_document_job,
    )


#: El estado del servicio. Es el mismo objeto que cuelga de `app.state`, y las
#: pruebas cambian sobre él lo que necesitan antes de levantar el cliente.
contexto = _arrancar()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ctx: Contexto = app.state.contexto
    ctx.settings.ensure_directories()
    # El mismo `_run` para la corrida de carpeta que para la subida: un solo
    # camino para un documento, llegue como llegue.
    ctx.folders = FolderRunner(ctx.registry, ctx.settings, lambda job: _run(ctx, job))

    # One process per document. Sized at cores-1 so the event loop always has a
    # core left to accept uploads while the pool is saturated.
    ctx.pool = ProcessPoolExecutor(max_workers=ctx.settings.document_workers)
    ctx.manager = multiprocessing.Manager()
    ctx.progress_queue = ctx.manager.Queue(maxsize=PROGRESS_QUEUE_SIZE)
    # Lo que el worker consulta entre página y página para saber si sigue. Vive
    # en el Manager y no en este proceso porque quien lo lee está en otro.
    ctx.controls = ctx.manager.dict()
    ctx.fuid_jobs = {}
    app.state.tasks = [
        asyncio.create_task(_drain_progress(ctx)),
        asyncio.create_task(_publish_progress(ctx)),
        asyncio.create_task(ctx.janitor.run()),
    ]
    logger.info("worker pool started with %s processes", ctx.settings.document_workers)

    try:
        yield
    finally:
        for task in app.state.tasks:
            task.cancel()
        ctx.pool.shutdown(wait=False, cancel_futures=True)
        try:
            ctx.manager.shutdown()
        except Exception:  # noqa: BLE001 - ya no está, que es lo que se quería
            logger.debug("el Manager ya había cerrado", exc_info=True)


app = FastAPI(title="Separador de resoluciones", version="0.2.0", lifespan=lifespan)
app.state.contexto = contexto
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def _entrada_invalida(request: Request, error: RequestValidationError) -> JSONResponse:
    """Un parámetro mal escrito se contesta con una frase, no con una lista.

    FastAPI responde por defecto con la lista de errores de pydantic -- `loc`,
    `msg`, `type`, en inglés y anidados -- y la pantalla enseña `detail` tal
    cual, así que el operador veía «[object Object]» por escribir una letra
    donde iba un número. Aquí se convierte en una oración en español que dice
    qué parámetro, qué se esperaba y qué llegó.
    """
    return JSONResponse(
        status_code=422, content={"detail": explicar_validacion(error.errors())}
    )


@app.exception_handler(Exception)
async def _fallo_interno(request: Request, error: Exception) -> JSONResponse:
    """Lo que nadie previó se registra entero y se cuenta a medias.

    Entero en el registro del servicio, con la ruta y el traceback, que es
    donde alguien lo va a buscar. A medias en la respuesta: el texto de una
    excepción lleva rutas del disco y nombres internos que no le sirven a quien
    está delante de la pantalla y sí a quien no debería verlos.
    """
    logger.exception("fallo sin atender en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": (
                f"El servicio falló al atender {request.url.path}. "
                "Revise el registro del backend."
            )
        },
    )


for router in (
    salud.router,
    lotes.router,
    trabajos.router,
    carpetas.router,
    salidas.router,
    archivo.router,
    fuid.router,
    mantenimiento.router,
    eventos.router,
    usuarios.router,
):
    app.include_router(router)


async def _drain_progress(ctx: Contexto) -> None:
    """Move worker events onto the registry as fast as they arrive.

    The queue read is blocking, so it runs on a thread; folding the event into
    registry state is cheap and stays on the loop.
    """
    loop = asyncio.get_running_loop()
    queue = ctx.progress_queue
    while True:
        try:
            event = await loop.run_in_executor(None, queue.get)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - el Manager se fue durante el apagado
            logger.debug("la cola de progreso se cerró", exc_info=True)
            return
        if event is None:
            return
        ctx.registry.apply_progress(event)


async def _publish_progress(ctx: Contexto) -> None:
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
            ctx.registry.flush()
            desde_el_latido += PUBLISH_INTERVAL
            if desde_el_latido >= HEARTBEAT_PUBLISH_SECONDS:
                desde_el_latido = 0.0
                ctx.registry.heartbeat()
        except Exception:  # noqa: BLE001 - never let the ticker die
            logger.debug("progress flush failed", exc_info=True)
