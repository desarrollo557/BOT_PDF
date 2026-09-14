"""Los archivos que produjo un trabajo: corregirlos, borrarlos y descargarlos."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ...domain.naming import output_filename
from ...domain.resolution_code import ResolutionCode
from ..contexto import Contexto, Ctx

router = APIRouter()


@router.patch("/api/jobs/{job_id}/outputs/{name:path}")
async def rename_output(ctx: Ctx, job_id: str, name: str, payload: dict) -> dict[str, object]:
    """Correct a resolution: its number, its title, or both.

    OCR gets a digit wrong often enough that an operator needs to fix it without
    running the document again. The file on disk, the report on screen and the
    inventory row all move together, because a correction that lands in only one
    of them is worse than no correction at all.
    """
    current = _output_path(ctx, job_id, name)

    row = next(
        (
            item
            for item in ctx.ledger.rows()
            if item.get("job_id") == job_id and item.get("file_name") == name
        ),
        None,
    )
    code = str(payload.get("code") or (row or {}).get("code") or "").strip()
    if not code:
        raise HTTPException(
            status_code=422, detail="El numero de resolucion no puede quedar vacio"
        )
    # Un título mandado en blanco se rechaza; no mandarlo, no.
    #
    # Son dos cosas distintas y conviene no confundirlas. **Ausente** es una
    # corrección parcial -- «cambia sólo el número» -- y el endpoint la admite
    # desde siempre. **Presente y vacío** es un formulario que se envió a medias,
    # y eso es lo que las pantallas ya no dejan hacer: la regla vive también
    # aquí porque una que sólo está en el formulario la esquiva cualquier
    # petición escrita a mano.
    raw_title = payload.get("title")
    if raw_title is not None and not str(raw_title).strip():
        raise HTTPException(
            status_code=422,
            detail=(
                "El título no puede ir en blanco. Escriba uno o no mande el "
                "campo si sólo quiere corregir el número."
            ),
        )
    title = None if raw_title is None else str(raw_title).strip() or None

    parsed = ResolutionCode.try_parse(code)
    if parsed is None:
        raise HTTPException(
            status_code=422, detail=f"{code} no es un numero de resolucion valido"
        )

    new_name = output_filename(parsed, title)
    target = current
    if new_name != current.name:
        # En la carpeta donde ya está, que desde que los documentos de una caja
        # se entregan bajo el nombre de su origen no tiene por qué ser la raíz
        # del trabajo. Renombrar no es mover.
        target = (current.parent / new_name).resolve()
        if target.exists():
            raise HTTPException(
                status_code=409, detail=f"Ya existe un archivo llamado {new_name}"
            )
        current.rename(target)

    # La ruta dentro del trabajo, no sólo el nombre del archivo.
    #
    # Desde que los documentos de una caja se entregan en una carpeta con el
    # nombre de su origen, `name` llega como "UPD2366126/01_FACTURA.pdf" y el
    # inventario lo guarda así, que es lo que la descarga necesita. Guardar
    # aquí `target.name` le quitaba la carpeta a la fila: el enlace pasaba a
    # contestar 404 y un segundo renombrado ya no encontraba la fila que había
    # que corregir, porque la busca justamente por este nombre.
    relativo = _relative_output(ctx, job_id, target)
    ctx.ledger.update(job_id, name, {"code": parsed.value, "title": title, "file_name": relativo})
    _amend_report(ctx, job_id, name, code=parsed.value, title=title, file_name=relativo)
    return {"file_name": relativo, "code": parsed.value, "title": title}

@router.delete("/api/jobs/{job_id}/outputs/{name:path}")
async def delete_output(ctx: Ctx, job_id: str, name: str) -> dict[str, object]:
    """Delete one generated resolution: the file and its inventory row."""
    target = _output_path(ctx, job_id, name)
    target.unlink(missing_ok=True)
    removed = ctx.ledger.remove(job_id, name)
    _amend_report(ctx, job_id, name, drop=True)
    return {"deleted": name, "was_recorded": removed is not None}

def _relative_output(ctx: Contexto, job_id: str, target: Path) -> str:
    """Cómo se llama un archivo generado visto desde la carpeta de su trabajo.

    Con barras normales siempre: es la forma en que viaja por la URL de
    descarga y la que el inventario guarda, y en Windows `Path` daría barras
    invertidas que no valen para ninguna de las dos cosas.
    """
    directory = (ctx.settings.output_dir / job_id).resolve()
    try:
        return target.relative_to(directory).as_posix()
    except ValueError:
        return target.name

def _output_path(ctx: Contexto, job_id: str, name: str) -> Path:
    directory = (ctx.settings.output_dir / job_id).resolve()
    target = (directory / name).resolve()
    # The job id and the file name both arrive from the client.
    if not target.is_file() or directory not in target.parents:
        raise HTTPException(status_code=404, detail="El archivo no existe")
    return target

def _amend_report(ctx: Contexto, 
    job_id: str,
    name: str,
    *,
    code: str | None = None,
    title: str | None = None,
    file_name: str | None = None,
    drop: bool = False,
) -> None:
    """Keep the on-screen report in step with the file that was just changed.

    The job may already have been cleared from the screen, in which case the
    ctx.ledger is the whole record and there is nothing here to update.
    """
    job = ctx.registry.get(job_id)
    report = job.report if job else None
    if not report:
        return

    inventory = report.get("inventory") or {}
    items = inventory.get("items") or []
    match = next((item for item in items if item.get("file_name") == name), None)
    if match is None:
        return

    previous_code = match.get("code")
    if drop:
        inventory["items"] = [item for item in items if item is not match]
        report["groups"] = [g for g in report.get("groups", []) if g.get("code") != previous_code]
        report["outputs"] = [output for output in report.get("outputs", []) if output != name]
    else:
        match.update({"code": code, "title": title, "file_name": file_name})
        for group in report.get("groups", []):
            if group.get("code") == previous_code:
                group["code"] = code
                group["title"] = title
        report["outputs"] = [
            file_name if output == name else output for output in report.get("outputs", [])
        ]

    inventory["generated_files"] = len(inventory.get("items") or [])
    ctx.registry.publish(job)

#: El tipo que hace que Windows abra el archivo con Excel en vez de preguntar.
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: Cómo se llama la hoja que el adaptador deja junto a los PDF generados. Vive
#: aquí duplicado porque abrir `excel_inventory` exige openpyxl, y el servicio
#: tiene que arrancar igual sin él; una prueba comprueba que los dos coincidan.
SHEET_SUFFIX = "__inventario.xlsx"

_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".json": "application/json",
    ".csv": "text/csv",
    ".xlsx": XLSX_MEDIA,
}

@router.get("/api/jobs/{job_id}/inventory.xlsx")
async def job_inventory(ctx: Ctx, job_id: str) -> FileResponse:
    """El inventario de un solo documento, tal como se dejó junto a sus PDF.

    Es la hoja que el adaptador ya escribió durante el proceso, no una copia
    armada aquí: lo que se descarga es exactamente el archivo que quedó en la
    carpeta de destino, así que nadie tiene que preguntarse cuál de los dos vale.
    """
    directory = (ctx.settings.output_dir / job_id).resolve()
    # Recursivo: la planilla viaja junto a los PDF que describe, y los de una
    # caja se entregan en una carpeta con el nombre de su origen. Buscándola
    # sólo en la raíz del trabajo, la descarga contestaba 404 justo en la ruta
    # que más la necesita, porque sus archivos se llaman por un número de orden
    # y sin el listado no dicen nada.
    sheets = sorted(directory.rglob(f"*{SHEET_SUFFIX}")) if directory.is_dir() else []
    if not sheets:
        raise HTTPException(
            status_code=404,
            detail="Ese documento no tiene inventario en Excel",
        )
    return FileResponse(sheets[0], media_type=XLSX_MEDIA, filename=sheets[0].name)

@router.get("/api/jobs/{job_id}/outputs/{name:path}")
async def download(ctx: Ctx, job_id: str, name: str) -> FileResponse:
    # Deliberately not gated on the job still being in the ctx.registry: the
    # inventory outlives the screen, and its rows link straight at these files.
    # Containment below is what makes serving by id alone safe.
    directory = (ctx.settings.output_dir / job_id).resolve()
    target = (directory / name).resolve()
    # Containment check: the job id and file name both arrive from the client.
    if not target.is_file() or directory not in target.parents:
        raise HTTPException(status_code=404, detail="El archivo no existe")

    media_type = _MEDIA_TYPES.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(target, media_type=media_type, filename=target.name)
