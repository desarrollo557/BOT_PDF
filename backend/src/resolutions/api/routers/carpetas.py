"""Las carpetas locales: procesar una entera, explorarlas y elegirlas."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse

from ...adapters import red_smb
from ...adapters.excel_inventory import NOMBRE_DEL_INVENTARIO_DE_PROCESOS
from ...adapters.indice_electronico import NOMBRE_DEL_INDICE
from ...application.task import TaskKind
from .. import native_picker
from ..contexto import Ctx
from ..folders import FolderError, SourceDisposition, clean_path
from ..indices import carpeta_del_lote, libro_de_indices
from ..rutas_del_equipo import al_operador, al_servicio, es_una_raiz, raices, red_abierta
from .salidas import XLSX_MEDIA
from .trabajos import (
    _agrupar_choice,
    _corte_choice,
    _lectura_choice,
    _operator,
    _oracle_choice,
    _territorial,
    _tipo_choice,
    _tipo_documento_choice,
)

router = APIRouter()


@router.post("/api/folder-runs", status_code=201)
async def start_folder_run(
    ctx: Ctx,
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

    # Se valida antes de tocar las carpetas: una elección imposible no tiene por
    # qué esperar a que se descubra que el destino era el mismo que el origen.
    choice = _oracle_choice(ctx, payload.get("oracle"))
    lectura_choice = _lectura_choice(ctx, payload.get("lectura"))
    tipo_choice = _tipo_choice(payload.get("tipo"))
    from .trabajos import _require_identity_reader

    _require_identity_reader(tipo_choice, lectura_choice)
    corte_choice = _corte_choice(payload.get("corte"))
    agrupar_choice = _agrupar_choice(payload.get("agrupar"))
    # La plantilla de la caja de correspondencia: índice electrónico, Kingspan
    # o mixto. Viaja igual que en una subida, para que elegir Kingspan en una
    # carpeta no se quede en nada.
    tipo_documento_choice = _tipo_documento_choice(payload.get("tipo_documento"))
    from .trabajos import _paralelo

    a_la_vez = _paralelo(ctx, payload.get("paralelo"))

    try:
        run = ctx.folders.start(
            str(payload.get("source") or ""),
            str(payload.get("destination") or ""),
            disposition=disposition,
            watch=bool(payload.get("watch")),
            operator=_operator(x_operator),
            task=str(kind),
            oracle=str(choice),
            lectura=str(lectura_choice),
            corte=str(corte_choice),
            agrupar=str(agrupar_choice),
            territorial=_territorial(payload.get("territorial")),
            tipo=str(tipo_choice),
            tipo_documento=tipo_documento_choice,
            # Retomar una entrega anterior: procesar sólo lo que falta en el
            # destino, o sólo revisarlo. Sólo para libros de diplomas.
            retomar=str(payload.get("retomar") or "no"),
            # Cuántos PDF de la carpeta a la vez; sin él, los del planificador.
            paralelo=a_la_vez,
        )
    except FolderError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return run.as_dict()

@router.get("/api/folder-runs")
async def list_folder_runs(ctx: Ctx) -> dict[str, object]:
    return {"runs": [run.as_dict() for run in ctx.folders.list()]}

@router.get("/api/folder-runs/{run_id}")
async def get_folder_run(ctx: Ctx, run_id: str) -> dict[str, object]:
    run = ctx.folders.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="El proceso de carpeta no existe")
    return run.as_dict()

@router.get("/api/folder-runs/{run_id}/inventario.xlsx")
async def folder_run_inventario(ctx: Ctx, run_id: str) -> FileResponse:
    """El inventario de actas de la carpeta entera: una fila por PDF.

    Lo escribe la corrida en la carpeta de destino y se sirve ese mismo
    archivo, para que lo que se descarga y lo que quedó entregado no puedan
    discrepar. No es el FUID, así que no lleva su restricción: como la planilla
    de un documento, la bajan los tres perfiles.
    """
    run = ctx.folders.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="El proceso de carpeta no existe")
    hoja = Path(run.inventario) if run.inventario else None
    if hoja is None or not hoja.is_file():
        detalle = (
            f"No se pudo escribir el inventario de esta carpeta: {run.inventario_error}"
            if run.inventario_error
            else "Esta carpeta todavía no tiene inventario: se escribe con la primera acta."
        )
        raise HTTPException(status_code=404, detail=detalle)
    return FileResponse(hoja, media_type=XLSX_MEDIA, filename=hoja.name)


def _carpeta_de_los_generales(ctx, origen_id: str) -> Path | None:
    """Dónde están los inventarios generales de un lote o una carpeta."""
    if re.fullmatch(r"[0-9a-f]{32}", origen_id) and carpeta_del_lote(
        ctx.settings.output_dir, origen_id
    ).is_dir():
        return carpeta_del_lote(ctx.settings.output_dir, origen_id)
    run = ctx.folders.get(origen_id)
    if run is not None:
        return Path(run.destination)
    ruta = next(
        (
            row.get("origen_procesos")
            for row in ctx.ledger.rows()
            if row.get("origen_id") == origen_id and row.get("origen_procesos")
        ),
        None,
    )
    return Path(ruta).parent if ruta else None


@router.get("/api/origenes/{origen_id}/procesos.xlsx")
async def origen_procesos(ctx: Ctx, origen_id: str) -> FileResponse:
    """El inventario general del bot de un lote o una carpeta: una fila por PDF procesado."""
    carpeta = _carpeta_de_los_generales(ctx, origen_id)
    hoja = carpeta / NOMBRE_DEL_INVENTARIO_DE_PROCESOS if carpeta else None
    if hoja is None or not hoja.is_file():
        raise HTTPException(
            status_code=404,
            detail="Este lote o carpeta todavía no tiene inventario de procesos: se escribe al terminar cada PDF.",
        )
    return FileResponse(hoja, media_type=XLSX_MEDIA, filename=hoja.name)


@router.get("/api/origenes/{origen_id}/inventario.xlsx")
async def origen_inventario(ctx: Ctx, origen_id: str) -> FileResponse:
    """El inventario general de una carpeta, también cuando ya no está en pantalla.

    La corrida vive en memoria y se pierde al limpiar la pantalla o reiniciar
    el servicio; el inventario no. Cada trabajo de la carpeta apuntó al
    crearse dónde iba a quedar su Excel general, y es esa ruta la que se sirve
    cuando la corrida ya no está. Si alguien lo movió o lo borró del destino,
    se dice dónde se le esperaba.
    """
    # Un lote de cajas de correspondencia: su inventario general es el libro
    # con el Índice Electrónico de cada caja, una hoja por PDF procesado. Se
    # escribe al terminar cada caja; si el lote es de antes, se arma ahora con
    # las cajas que el libro mayor recuerda.
    lote = carpeta_del_lote(ctx.settings.output_dir, origen_id)
    libro = lote / NOMBRE_DEL_INDICE
    es_un_lote = re.fullmatch(r"[0-9a-f]{32}", origen_id) is not None
    if es_un_lote and not libro.is_file():
        trabajos = [
            str(row.get("job_id"))
            for row in ctx.ledger.rows()
            if row.get("origen_id") == origen_id and row.get("origen_tipo") == "lote"
        ]
        if trabajos:
            await asyncio.to_thread(libro_de_indices, ctx.settings.output_dir, trabajos, lote)
    if es_un_lote and libro.is_file():
        return FileResponse(libro, media_type=XLSX_MEDIA, filename=NOMBRE_DEL_INDICE)
    # Una carpeta de cajas de correspondencia: su Índice Electrónico general,
    # una hoja por PDF, en la raíz del destino.
    # El identificador de una corrida de carpeta tiene la misma forma que el de
    # un lote: lo que decide es dónde están sus generales.
    if carpeta := _carpeta_de_los_generales(ctx, origen_id):
        indice = carpeta / NOMBRE_DEL_INDICE
        if indice.is_file():
            return FileResponse(indice, media_type=XLSX_MEDIA, filename=NOMBRE_DEL_INDICE)

    run = ctx.folders.get(origen_id)
    if run is not None and run.inventario and Path(run.inventario).is_file():
        hoja = Path(run.inventario)
        return FileResponse(hoja, media_type=XLSX_MEDIA, filename=hoja.name)

    ruta = next(
        (
            row.get("origen_inventario")
            for row in ctx.ledger.rows()
            if row.get("origen_id") == origen_id and row.get("origen_inventario")
        ),
        None,
    )
    if not ruta:
        raise HTTPException(status_code=404, detail="Esta carpeta no dejó inventario general.")
    hoja = Path(ruta)
    if not hoja.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"El inventario general ya no está en {hoja}. Se movió o se borró del destino.",
        )
    return FileResponse(hoja, media_type=XLSX_MEDIA, filename=hoja.name)


@router.post("/api/folder-runs/{run_id}/stop")
async def stop_folder_run(ctx: Ctx, run_id: str) -> dict[str, object]:
    if ctx.folders.get(run_id) is None:
        raise HTTPException(status_code=404, detail="El proceso de carpeta no existe")
    run = ctx.folders.stop(run_id)
    if run is None:
        raise HTTPException(status_code=409, detail="Ese proceso ya habia terminado")
    return run.as_dict()

@router.delete("/api/folder-runs")
async def clear_folder_runs(ctx: Ctx) -> dict[str, object]:
    """Vaciar la pantalla de carpetas ya terminadas.

    Sólo se van las que terminaron, pararon o fallaron, así que hacer esto con
    una carpeta en marcha nunca cuesta trabajo empezado. Lo entregado sigue en
    la carpeta de destino y el archivo conserva sus filas: esto vacía una
    pantalla, no deshace nada.
    """
    removed = ctx.folders.forget_finished()
    return {"removed": len(removed), "ids": [run.id for run in removed]}

@router.delete("/api/folder-runs/{run_id}")
async def forget_folder_run(ctx: Ctx, run_id: str) -> dict[str, object]:
    """Quitar de la pantalla una carpeta concreta que ya terminó."""
    if ctx.folders.get(run_id) is None:
        raise HTTPException(status_code=404, detail="El proceso de carpeta no existe")
    run = ctx.folders.forget(run_id)
    if run is None:
        raise HTTPException(
            status_code=409,
            detail="Ese proceso sigue en marcha; hay que detenerlo antes de quitarlo",
        )
    return {"removed": 1, "ids": [run.id]}

@router.get("/api/folders")
async def browse(ctx: Ctx, path: str | None = None) -> dict[str, object]:
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

    ruta = clean_path(path)
    if red_smb.es_de_red(ruta):
        # Si el servidor pide usuario y clave, `CredencialesDeRed` sube hasta el
        # manejador de la aplicación, que contesta 401 y la pantalla los pide.
        await asyncio.to_thread(red_smb.asegurar, ruta)
        if red_smb.por_smb(ruta):
            return await asyncio.to_thread(_explorar_la_red, ruta)

    try:
        current = Path(al_servicio(ruta)).expanduser().resolve(strict=True)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail=f"La carpeta no existe: {path}") from None
    if not current.is_dir():
        raise HTTPException(status_code=422, detail="Eso no es una carpeta")

    def listar() -> list[str]:
        # Con `scandir`: si es carpeta viene en el mismo listado. Con
        # `iterdir` + `is_dir` era una pregunta al disco por entrada, y en una
        # unidad de red con cincuenta mil entradas eso eran minutos.
        with os.scandir(current) as entradas:
            nombres = []
            for entrada in entradas:
                # Las ocultas y las del sistema sólo estorban en un selector.
                if entrada.name.startswith((".", "$")):
                    continue
                try:
                    if entrada.is_dir():
                        nombres.append(entrada.name)
                except OSError:
                    continue
            return sorted(nombres, key=str.lower)

    try:
        nombres = await asyncio.to_thread(listar)
    except PermissionError:
        raise HTTPException(
            status_code=403, detail="Sin permiso para leer esa carpeta"
        ) from None
    except OSError as error:
        raise HTTPException(status_code=422, detail=f"No se pudo leer: {error}") from None

    parent = al_operador(current.parent) if current.parent != current else None
    if es_una_raiz(al_operador(current)):
        # La raíz de una unidad o de un recurso de red montado: arriba de ella
        # sólo está el contenedor.
        parent = None
    return {
        "path": al_operador(current),
        "parent": parent,
        "drives": _drives(),
        **_por_lotes(nombres, lambda nombre: al_operador(current / nombre)),
    }

@router.post("/api/folders/pick")
async def pick_folder(ctx: Ctx, payload: dict | None = None) -> dict[str, object]:
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
    """Puntos de partida: las unidades en Windows, la raíz y el hogar fuera.

    En Docker, las unidades del equipo que el instalador montó: el hogar y la
    raíz del contenedor no le dicen nada al operador.
    """
    montadas = raices()
    if montadas:
        return montadas
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
    filtradas = [root for root in roots if _es_carpeta(root["path"])]
    # Y las carpetas de red a las que ya se entró: «\\200.100.20.97\afinia».
    return filtradas + red_abierta()


def _explorar_la_red(ruta: str) -> dict[str, object]:
    """Lo mismo que el explorador hace con un disco, para una carpeta de red."""
    partes = red_smb.partes(ruta)
    try:
        if not red_smb.es_carpeta(partes.unc):
            raise HTTPException(status_code=404, detail=f"La carpeta no existe: {partes.unc}")
        nombres = red_smb.carpetas(partes.unc)
    except red_smb.RedNoDisponible as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except OSError as error:
        raise HTTPException(status_code=422, detail=f"No se pudo leer: {error}") from None
    padre = None
    if partes.resto:
        arriba = partes.resto.rsplit("\\", 1)[0] if "\\" in partes.resto else ""
        padre = f"{partes.raiz}\\{arriba}" if arriba else f"{partes.raiz}\\"
    return {
        "path": partes.unc if partes.resto else f"{partes.raiz}\\",
        "parent": padre,
        "drives": _drives(),
        **_por_lotes(
            [nombre for nombre in nombres if not nombre.startswith((".", "$"))],
            lambda nombre: f"{partes.unc}\\{nombre}",
        ),
    }


#: Cuántas subcarpetas enseña el explorador de una vez. Una caja del
#: repositorio puede tener decenas de miles: mandarlas todas dejaba la pantalla
#: colgada pintándolas (2026-10-20, «hagámoslo por conteo por lotes»). Las
#: demás se cuentan y se llega a ellas escribiendo la ruta.
CARPETAS_EN_EL_EXPLORADOR = 500


def _por_lotes(nombres: list[str], ruta_de) -> dict[str, object]:
    """Las primeras subcarpetas, ya ordenadas, y cuántas quedaron fuera."""
    primeras = nombres[:CARPETAS_EN_EL_EXPLORADOR]
    return {
        "folders": [{"name": nombre, "path": ruta_de(nombre)} for nombre in primeras],
        "omitidas": len(nombres) - len(primeras),
    }


def _es_carpeta(ruta: str) -> bool:
    """Si existe; una carpeta de red que no contesta no tumba el explorador."""
    try:
        return Path(ruta).is_dir()
    except OSError:
        return False
