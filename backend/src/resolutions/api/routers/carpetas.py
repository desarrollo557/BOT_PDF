"""Las carpetas locales: procesar una entera, explorarlas y elegirlas."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException

from ...application.task import TaskKind
from .. import native_picker
from ..contexto import Ctx
from ..folders import FolderError, SourceDisposition, clean_path
from .trabajos import _lectura_choice, _operator, _oracle_choice, _tipo_choice

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
            tipo=str(tipo_choice),
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

    try:
        current = Path(clean_path(path)).expanduser().resolve(strict=True)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail=f"La carpeta no existe: {path}") from None
    if not current.is_dir():
        raise HTTPException(status_code=422, detail="Eso no es una carpeta")

    subcarpetas: list[dict[str, object]] = []
    try:
        for entry in sorted(current.iterdir(), key=lambda item: item.name.lower()):
            # Las ocultas y las del sistema sólo estorban en un selector.
            if entry.name.startswith((".", "$")):
                continue
            try:
                if entry.is_dir():
                    subcarpetas.append({"name": entry.name, "path": str(entry)})
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
        "folders": subcarpetas,
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
