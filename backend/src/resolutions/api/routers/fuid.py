"""El FUID de un documento ya procesado: pedirlo, esperarlo y descargarlo."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ...application.control import Cancelled, RunState
from ...application.task import TaskKind
from ..contexto import Contexto, Ctx
from ..identidad import Quien, exigir_descarga_de_planillas
from ..worker import FUID_SUFFIX
from .salidas import XLSX_MEDIA

logger = logging.getLogger(__name__)

router = APIRouter()

#: Lo que se contesta cuando un documento no tiene planilla. Lo dicen los dos
#: endpoints que la sirven, y escribirlo dos veces es como acaban diciendo
#: cosas distintas de lo mismo.
SIN_FUID = (
    "Ese documento no tiene un FUID. Sólo lo tienen los que se procesaron "
    "con la acción «Solo inventariar»."
)


def _clave_de_control(job_id: str) -> str:
    """Bajo qué nombre se le dan órdenes al FUID que se levanta a petición.

    No es la del trabajo. Levantar un FUID vuelve a leer un documento que ya
    terminó, así que su clave está libre en el diccionario de control y el
    endpoint que detiene trabajos la rechaza -- pide que el trabajo esté en
    vuelo, y éste no lo está. Con una clave propia, abandonar la lectura del
    inventario no puede confundirse con abandonar la separación que ya ocurrió.
    """
    return f"fuid:{job_id}"


def _fuid_de(ctx: Contexto, job_id: str) -> Path | None:
    """La planilla FUID escrita para un documento, si la hay."""
    directorio = (ctx.settings.output_dir / job_id).resolve()
    if not directorio.is_dir():
        return None
    hojas = sorted(directorio.glob(f"*{FUID_SUFFIX}"))
    return hojas[0] if hojas else None

def _fuente_de(ctx: Contexto, job_id: str) -> Path | None:
    """El PDF del que salió el documento, si todavía está donde estaba.

    Una subida se borra al terminar su trabajo y un original de carpeta puede
    haberse apartado o borrado, según lo que el operador eligiera. Sin él no hay
    nada que leer, y decirlo es mejor que dejar el botón girando.
    """
    job = ctx.registry.get(job_id)
    if job is None:
        return None
    return job.source if job.source.is_file() else None

async def _levantar_fuid(ctx: Contexto, job_id: str) -> None:
    """Leer el documento otra vez, sólo para su inventario.

    Es exactamente lo que hace la acción «Solo inventariar» de la pantalla de
    carga -- el mismo worker, la misma plantilla elegida por el tipo de documento
    que se reconozca -- aplicado a un documento que ya se procesó. No crea un
    trabajo nuevo ni toca el informe del que ya existe: deja una planilla más
    junto a los PDF que ese documento produjo.
    """
    job = ctx.registry.get(job_id)
    if job is None:
        ctx.fuid_jobs[job_id] = "El documento ya no está en la pantalla"
        return
    clave = _clave_de_control(job_id)
    payload = {
        "job_id": job.id,
        "source": str(job.source),
        "filename": job.filename,
        "operator": job.operator,
        "task": str(TaskKind.INVENTORY),
        # A dónde fue la entrega, que es una columna de la planilla. Sin esto el
        # FUID que se pide después declaraba un destino vacío para un documento
        # que sí se había entregado en una carpeta.
        "destination": job.destination,
        "settings": ctx.settings.as_worker_payload(),
        "progress_queue": ctx.progress_queue,
        # Leer un libro de cuatrocientos folios son minutos, y hasta aquí no
        # había forma de abandonarlos: esta carga útil viajaba sin canal de
        # control, así que el worker caía en el control nulo y la única salida
        # era esperar. Bajo su propia clave, para no pisar la del trabajo.
        "controls": ctx.controls,
        "control_key": clave,
    }
    loop = asyncio.get_running_loop()
    try:
        ctx.controls[clave] = str(RunState.RUNNING)
        await loop.run_in_executor(ctx.pool, ctx.procesar, payload)
    except Cancelled:
        # No es un fallo: es lo que el operador pidió. Se dice con sus palabras
        # para que la pantalla no lo pinte como un error del documento.
        logger.info("el operador abandonó el FUID de %s", job_id)
        ctx.fuid_jobs[job_id] = "Se abandonó el inventario de este documento"
        return
    except Exception as error:  # noqa: BLE001 - se le dice al operador qué pasó
        logger.exception("no se pudo levantar el FUID de %s", job_id)
        ctx.fuid_jobs[job_id] = f"{type(error).__name__}: {error}"
        return
    finally:
        ctx.controls.pop(clave, None)

    # Terminar sin excepción no es lo mismo que haber escrito la planilla. Un
    # documento del que no se pudo leer ni una fila -- un escaneo sin capa de
    # texto y sin Tesseract, un libro que no se reconoce -- deja el trabajo
    # hecho y el FUID sin escribir, y antes eso se contaba como si todo hubiera
    # ido bien: el estado quedaba en "ni listo ni con error", y la pantalla se
    # quedaba diciendo "levantando…" para siempre, sin nada más que decir.
    if _fuid_de(ctx, job_id) is None:
        ctx.fuid_jobs[job_id] = (
            "El documento se leyó pero no se pudo sacar ni una fila de "
            "inventario. Suele ser un escaneo sin capa de texto: hace falta "
            "Tesseract instalado para leerlo."
        )
        return
    ctx.fuid_jobs.pop(job_id, None)

@router.post("/api/jobs/{job_id}/fuid", status_code=202)
async def make_job_fuid(ctx: Ctx, job_id: str) -> dict[str, object]:
    """Levantar el inventario de un documento que ya se procesó.

    El botón que lo llama no elige plantilla: la elige el tipo de documento que
    se reconoce al leerlo, igual que cuando se sube un archivo con la acción
    «Solo inventariar». Un libro de diplomas produce el FUID de diplomas y un
    legajo de resoluciones el genérico, sin que nadie tenga que acertar antes.

    Devuelve enseguida. Leer un libro de cuatrocientos folios son minutos, y
    dejar la petición HTTP abierta todo ese rato es cómo se pierde el resultado
    por un tiempo de espera de un intermediario.
    """
    existente = _fuid_de(ctx, job_id)
    if existente is not None:
        # Ya estaba: lo pidió con la acción de inventariar, o alguien pulsó el
        # botón antes. No se vuelve a leer el documento para producir lo mismo.
        return {"ready": True, "name": existente.name, "error": None}

    if job_id in ctx.fuid_jobs and ctx.fuid_jobs[job_id] is None:
        return {"ready": False, "name": None, "error": None}

    if _fuente_de(ctx, job_id) is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "El documento de origen ya no está disponible, así que no se "
                "puede volver a leer para inventariarlo. Vuelva a cargarlo con "
                "la acción «Solo inventariar»."
            ),
        )

    ctx.fuid_jobs[job_id] = None
    asyncio.create_task(_levantar_fuid(ctx, job_id))
    return {"ready": False, "name": None, "error": None}

@router.delete("/api/jobs/{job_id}/fuid")
async def cancel_job_fuid(ctx: Ctx, job_id: str) -> dict[str, object]:
    """Abandonar el inventario que se estaba levantando para este documento.

    Va aquí y no por el endpoint que detiene trabajos porque no es el mismo
    trabajo: aquél ya terminó -- por eso hay un botón de FUID -- y detenerlo
    contesta que no hay nada que detener. Lo que se abandona es la relectura.

    La orden tarda lo que tarde la página en curso, igual que en cualquier otro
    trabajo: el worker la consulta entre una hoja y la siguiente, que es el
    único punto donde parar no deja nada a medio escribir.
    """
    if job_id not in ctx.fuid_jobs or ctx.fuid_jobs[job_id] is not None:
        raise HTTPException(
            status_code=409,
            detail="No se está levantando ningún inventario para este documento",
        )
    ctx.controls[_clave_de_control(job_id)] = str(RunState.CANCELLED)
    return {"id": job_id, "cancelling": True}

@router.get("/api/jobs/{job_id}/fuid")
async def job_fuid_status(ctx: Ctx, job_id: str) -> dict[str, object]:
    """Si el inventario de un documento ya está escrito, y si algo falló."""
    error = ctx.fuid_jobs.get(job_id)
    hoja = _fuid_de(ctx, job_id)
    return {
        "ready": hoja is not None,
        "name": hoja.name if hoja else None,
        "error": error,
        "working": job_id in ctx.fuid_jobs and error is None and hoja is None,
    }

@router.get("/api/jobs/{job_id}/fuid.tabla")
async def job_fuid_tabla(ctx: Ctx, job_id: str, quien: Quien) -> dict[str, object]:
    """La planilla como tabla, para mirarla en pantalla sin descargarla.

    La ven los tres perfiles. Revisar un inventario sin verlo no es revisarlo, y
    esconderlo no protegería nada: son los mismos datos que la pantalla de
    Archivo ya enseña documento a documento.

    Se lee del archivo que hay en el disco y no se arma desde el informe del
    trabajo, aunque eso fuera más rápido. Es la misma razón por la que la
    descarga sirve el archivo escrito: lo que se mira y lo que se firma tienen
    que ser el mismo documento, y dos caminos distintos acaban discrepando.
    """
    # Dentro de la función y no arriba: leer Excel es openpyxl, y el proceso de
    # la API no tiene por qué cargarlo para aceptar una subida.
    from ...adapters.fuid_reader import leer_fuid

    hoja = _fuid_de(ctx, job_id)
    if hoja is None:
        raise HTTPException(status_code=404, detail=SIN_FUID)
    try:
        planilla = await asyncio.to_thread(leer_fuid, hoja)
    except Exception as error:  # noqa: BLE001 - se le dice al operador qué pasó
        logger.exception("no se pudo leer el FUID de %s", job_id)
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo leer la planilla de este documento: {error}",
        ) from error
    return {
        **planilla.as_dict(),
        # Para que la pantalla sepa si enseñar el botón de descarga sin tener
        # que deducirlo del perfil por su cuenta. La decisión vive en un solo
        # sitio -- el dominio -- y la pantalla la obedece.
        "descargable": bool(quien and quien.perfil.descarga_planillas),
    }


@router.get("/api/jobs/{job_id}/fuid.xlsx")
async def job_fuid(ctx: Ctx, job_id: str, quien: Quien) -> FileResponse:
    """El Formato Único de Inventario Documental de un documento inventariado.

    Es la planilla oficial que el worker rellenó al procesarlo, no una armada
    aquí: se descarga el archivo que quedó escrito, para que lo que se firma y
    lo que está en disco no puedan discrepar.

    El técnico y el de calidad no la descargan: la miran en `fuid.tabla`. La
    comprobación vive aquí y no sólo en la pantalla porque una restricción que
    únicamente esconde un botón la esquiva quien escriba la dirección a mano.
    """
    exigir_descarga_de_planillas(quien)
    directory = (ctx.settings.output_dir / job_id).resolve()
    hojas = sorted(directory.glob(f"*{FUID_SUFFIX}")) if directory.is_dir() else []
    if not hojas:
        raise HTTPException(status_code=404, detail=SIN_FUID)
    return FileResponse(hojas[0], media_type=XLSX_MEDIA, filename=hojas[0].name)
