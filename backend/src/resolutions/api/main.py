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
import os
import time
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..adapters import red_smb
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
from .errores import explicar_validacion, fallo_conocido
from .folders import FolderRunner
from .janitor import IdleJanitor
from .jobs import JobRegistry
from .planificador import Planificador
from .registro_en_consola import configurar, configurar_worker
from .routers import (
    archivo,
    carpetas,
    eventos,
    fuid,
    lotes,
    mantenimiento,
    reconocer,
    red,
    salidas,
    salud,
    trabajos,
    usuarios,
)
from .settings import Settings
from .worker import process_document_job

logger = logging.getLogger(__name__)

# Antes de arrancar nada: lo primero que se hace es dejar la consola escuchando.
configurar()

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


def _nuevo_pool(settings: Settings) -> ProcessPoolExecutor:
    """El pool de procesos, con cada proceso cambiado tras ``documentos_por_proceso``.

    En días de corrida, la memoria que el código nativo no devuelve se
    acumula en los mismos pocos procesos; uno nuevo empieza limpio. Reciclar
    exige arrancar los procesos con «spawn», que es lo que Windows hace siempre.
    """
    reciclar = max(0, int(getattr(settings, "documentos_por_proceso", 0) or 0))
    return ProcessPoolExecutor(
        max_workers=settings.document_workers,
        # Cada proceso hijo configura su propio registro al nacer: en Windows
        # no hereda los manejadores del padre, y es en los hijos donde ocurre
        # todo lo que interesa ver.
        initializer=configurar_worker,
        **(
            {"max_tasks_per_child": reciclar, "mp_context": multiprocessing.get_context("spawn")}
            if reciclar
            else {}
        ),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    ctx: Contexto = app.state.contexto
    ctx.settings.ensure_directories()
    # El mismo `_run` para la corrida de carpeta que para la subida: un solo
    # camino para un documento, llegue como llegue.
    ctx.planificador = Planificador(
        documentos_de_carpeta=ctx.settings.folder_documents,
        hilos_por_documento=ctx.settings.page_workers,
        procesos=ctx.settings.document_workers,
    )
    ctx.folders = FolderRunner(
        ctx.registry,
        ctx.settings,
        lambda job: _run(ctx, job),
        planificador=ctx.planificador,
    )

    # One process per document. Sized at cores-1 so the event loop always has a
    # core left to accept uploads while the pool is saturated.
    ctx.pool = _nuevo_pool(ctx.settings)

    def rehacer_pool(roto, matar: bool = False) -> None:
        """Otro pool en lugar del que se rompió, una sola vez aunque fallen varios.

        Un proceso que muere -- memoria, un fallo nativo de MuPDF -- deja el
        pool entero inservible, y antes todos los PDF que quedaban en la
        carpeta fallaban en segundos hasta reiniciar el servicio. Quien llega
        con el pool ya cambiado no hace nada: otro trabajo lo rehízo antes.

        ``matar`` es para el pool congelado (ningún documento avanza): sus
        procesos siguen vivos pero no devuelven nada, así que se terminan; lo
        que tenían dentro falla como «pool roto» y se reintenta en el nuevo.
        """
        if ctx.pool is not roto:
            return
        logger.error("el pool de procesos se %s; se levanta otro", "congeló" if matar else "rompió")
        ctx.pool = _nuevo_pool(ctx.settings)
        if matar:
            for proceso in list((getattr(roto, "_processes", None) or {}).values()):
                try:
                    proceso.terminate()
                except Exception:  # noqa: BLE001 - el que ya no está, no hace falta
                    logger.debug("no se pudo terminar un proceso del pool", exc_info=True)
        try:
            roto.shutdown(wait=False, cancel_futures=True)
        except Exception:  # noqa: BLE001 - ya estaba roto
            logger.debug("no se pudo cerrar el pool roto", exc_info=True)

    ctx.rehacer_pool = rehacer_pool
    ctx.manager = multiprocessing.Manager()
    ctx.progress_queue = ctx.manager.Queue(maxsize=PROGRESS_QUEUE_SIZE)
    # Lo que el worker consulta entre página y página para saber si sigue. Vive
    # en el Manager y no en este proceso porque quien lo lee está en otro.
    ctx.controls = ctx.manager.dict()
    ctx.turnos_de_ia = ctx.manager.BoundedSemaphore(ctx.settings.ia_a_la_vez)
    ctx.fuid_jobs = {}
    app.state.tasks = [
        asyncio.create_task(_drain_progress(ctx)),
        asyncio.create_task(_publish_progress(ctx)),
        asyncio.create_task(ctx.janitor.run()),
    ]
    logger.info(
        "worker pool started with %s processes; %s documentos de carpeta a la vez; "
        "%s llamadas a la IA a la vez",
        ctx.settings.document_workers,
        ctx.settings.folder_documents,
        ctx.settings.ia_a_la_vez,
    )

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


@app.middleware("http")
async def registrar_cada_peticion(request: Request, call_next):
    """Una línea por petición, con lo que tardó y lo que contestó.

    Sustituye al registro de acceso de uvicorn, que dice la ruta y el código
    pero no cuánto tardó ni qué se pidió en la query -- y la query es donde
    viajan la acción, el tipo y el motor de lectura, que es lo que hace falta
    para saber a qué habilidad fue cada documento sin abrir el informe.
    """
    inicio = time.perf_counter()
    respuesta = await call_next(request)
    tardo = (time.perf_counter() - inicio) * 1000
    destino = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    logger.info("%s %s -> %s en %.0f ms", request.method, destino, respuesta.status_code, tardo)
    return respuesta

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


@app.exception_handler(red_smb.CredencialesDeRed)
async def _credenciales_de_red(request: Request, error: red_smb.CredencialesDeRed) -> JSONResponse:
    """La carpeta de red pide usuario y clave: una pregunta para el operador, no un fallo.

    Con un código que la pantalla reconoce, para que abra el cuadro de usuario
    y clave, conecte y repita lo que estaba haciendo.
    """
    return JSONResponse(
        status_code=401,
        content={
            "detail": {
                "codigo": "credenciales_de_red",
                "recurso": error.recurso,
                "mensaje": f"{error.motivo}: {error.recurso}",
            }
        },
    )


@app.exception_handler(red_smb.RedNoDisponible)
async def _red_no_disponible(request: Request, error: red_smb.RedNoDisponible) -> JSONResponse:
    """El servidor de red no contesta o el recurso no existe: se dice tal cual."""
    return JSONResponse(status_code=503, content={"detail": str(error)})


@app.exception_handler(Exception)
async def _fallo_interno(request: Request, error: Exception) -> JSONResponse:
    """Lo que nadie previó se registra entero y se cuenta a medias.

    Entero en el registro del servicio, con la ruta y el traceback, que es
    donde alguien lo va a buscar. A medias en la respuesta: el texto de una
    excepción lleva rutas del disco y nombres internos que no le sirven a quien
    está delante de la pantalla y sí a quien no debería verlos.
    """
    # Un código corto en la respuesta y en el registro: con él se encuentra el
    # traceback exacto entre miles de líneas sin pedirle a nadie la hora.
    referencia = uuid4().hex[:8]
    logger.exception(
        "fallo sin atender [%s] en %s %s", referencia, request.method, request.url.path
    )
    # Lo que se sabe explicar -- un Excel abierto, el disco lleno -- se dice con
    # qué hacer; lo demás, sin interioridades.
    explicacion = fallo_conocido(error) or f"El servicio falló al atender {request.url.path}."
    return JSONResponse(
        status_code=500,
        content={
            "detail": (
                f"{explicacion} Referencia del error: {referencia} "
                "(búsquela en el registro del backend)."
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
    reconocer.router,
    red.router,
):
    app.include_router(router)

def _frontend_root() -> Path:
    """La carpeta del front compilado en el contenedor.

    En el entorno de desarrollo el código vive en la raíz del repo; en Docker se
    instala como paquete Python y el acceso a ``__file__`` cambia. Por eso el
    punto de verdad es una ruta explícita del contenedor y un override por
    variable de entorno, que es lo que deja el servicio funcionando igual con
    código fuente o con una imagen ya preparada.
    """
    candidates = [
        Path(os.environ.get("BOTPDF_WEB_ROOT", "/app/web/build")),
        Path(__file__).resolve().parents[4] / "web" / "build",
        Path("/app/web/build"),
        Path.cwd() / "web" / "build",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


class _Pantalla(StaticFiles):
    """El front compilado, con la página única para cualquier ruta suya.

    La pantalla es una aplicación de una sola página: «/archivo» o
    «/revision» no son archivos del disco sino rutas que resuelve el navegador.
    Recargarlas devolvía un 404; ahora devuelven ``index.html`` y la pantalla
    sigue donde estaba. Lo que va a ``/api`` nunca cae aquí: un endpoint que no
    existe sigue siendo un 404 de la API.
    """

    async def get_response(self, path: str, scope):
        try:
            respuesta = await super().get_response(path, scope)
        except StarletteHTTPException as error:
            # Sólo una ruta de página («archivo», «revision/123») es la página
            # única. Un archivo que no existe -- un .js de la versión anterior
            # que pide una pestaña abierta antes de reconstruir -- es un 404 de
            # verdad: servirle HTML hacía fallar el script y la pestaña se
            # recargaba una y otra vez.
            ultimo = path.rstrip("/").rsplit("/", 1)[-1]
            if error.status_code != 404 or path.startswith(("api", "_app")) or "." in ultimo:
                raise
            respuesta = await super().get_response("index.html", scope)
        # Lo que lleva la versión en el nombre («3.DhUHgjH6.js») no cambia nunca
        # y se guarda para siempre. Todo lo demás -- la página, que es la que
        # dice qué archivos pedir -- se pregunta cada vez: un navegador que
        # guardó la página de antes de reconstruir pedía archivos que ya no
        # existen («Failed to fetch dynamically imported module», 2026-10-20).
        # Starlette da la ruta con el separador del sistema: «\» en Windows.
        if path.replace("\\", "/").startswith("_app/immutable/"):
            respuesta.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            respuesta.headers["Cache-Control"] = "no-cache"
        return respuesta


frontend_root = _frontend_root()
if (frontend_root / "index.html").exists():
    app.mount("/", _Pantalla(directory=str(frontend_root), html=True), name="frontend")


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
