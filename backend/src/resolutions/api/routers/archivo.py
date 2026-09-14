"""El archivo: todo lo que salió del separador, buscable y descargable.

Un solo filtro para las cuatro salidas -- la lista de resoluciones, la de
documentos, el Excel y el CSV -- para que lo que se ve en pantalla sea
exactamente lo que se descarga.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from ...domain.anchor import strip_accents
from ..contexto import Contexto, Ctx
from .salidas import XLSX_MEDIA
from .trabajos import _discard_outputs

logger = logging.getLogger(__name__)

router = APIRouter()


#: Cuánto puede medir lo que se escribe en el buscador del archivo y cuántas
#: filas admite una página. Son topes del gesto, no de la máquina: nadie
#: teclea doscientas letras en un buscador ni lee cinco mil filas de una vez,
#: y una petición que los pase casi siempre es un error de quien la construyó.
MAX_BUSQUEDA = 200

MAX_LIMITE = 5_000

@router.get("/api/inventory")
async def inventory(
    ctx: Ctx,
    q: str | None = Query(None, max_length=MAX_BUSQUEDA),
    limit: int = Query(500, ge=1, le=MAX_LIMITE),
    offset: int = Query(0, ge=0),
) -> dict[str, object]:
    """Every resolution PDF ever produced, newest first.

    The ctx.ledger outlives the job ctx.registry, so this still answers "which document
    did 00086 come from" long after the screen was cleared.

    Los topes van en la firma y no en el cuerpo: un `offset` negativo recortaba
    la lista por el final sin decir nada, y un `limit` fuera de rango se
    corregía en silencio. Ahora los dos contestan 422 con el motivo.
    """
    rows = _filtrar(ctx.ledger.rows(), q)
    window = rows[offset : offset + limit]
    return {
        "rows": window,
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "summary": ctx.ledger.summary(),
    }

@router.get("/api/documents")
async def documents(
    ctx: Ctx,
    q: str | None = Query(None, max_length=MAX_BUSQUEDA),
    limit: int = Query(500, ge=1, le=MAX_LIMITE),
    offset: int = Query(0, ge=0),
) -> dict[str, object]:
    """Every source document ever processed, newest first.

    Read from the ctx.ledger rather than from the ctx.registry, so the history survives
    clearing the screen and restarting the service -- which is the whole point
    of a record.
    """
    rows = ctx.ledger.documents()
    if q and q.strip():
        # Un documento lleva sólo una muestra de sus códigos, así que se busca
        # en sus filas -- todas, con todo lo que las describe -- y se conservan
        # los documentos que tengan alguna que responda. Es el mismo filtro que
        # aplica la pestaña de resoluciones; eran dos distintos, y en ésta no
        # se encontraba ni por tipo documental ni por NIC ni sin tildes.
        encontrados = {row.get("job_id") for row in _filtrar(ctx.ledger.rows(), q)}
        rows = [row for row in rows if row.get("job_id") in encontrados]

    return {
        "documents": rows[offset : offset + limit],
        "total": len(rows),
        "offset": offset,
        "limit": limit,
    }

@router.get("/api/documents/{job_id}")
async def document_detail(ctx: Ctx, job_id: str) -> dict[str, object]:
    """Un documento ya procesado, tal como lo recuerda el inventario.

    La pantalla de detalle se dibujaba sólo desde el trabajo en memoria, así que
    en cuanto el área de trabajo se limpiaba el documento quedaba en un callejón
    sin salida: la ficha decía "archivado" y no llevaba a ninguna parte. El
    inventario sí lo recuerda -- es lo que lo hace un inventario -- y esto es
    esa memoria, servida para que la ficha vuelva a poder abrirse.

    No devuelve lo mismo que el trabajo en memoria, y no debe fingir que sí: el
    reparto por peldaños, la cinta de páginas y las correcciones de OCR viven en
    el informe del proceso y no se guardan. Lo que queda es lo que se produjo,
    que es justamente lo que un archivo tiene que poder responder meses después.
    """
    entrada = next(
        (item for item in ctx.ledger.documents() if item.get("job_id") == job_id), None
    )
    filas = [row for row in ctx.ledger.rows() if row.get("job_id") == job_id]
    if entrada is None and not filas:
        raise HTTPException(status_code=404, detail="El documento no está en el inventario")

    return {
        **(entrada or {"job_id": job_id}),
        "rows": filas,
        # Si además sigue en pantalla, la pantalla tiene más que contar y es ella
        # la que manda. Se dice aquí para que el cliente no tenga que adivinarlo.
        "on_screen": ctx.registry.get(job_id) is not None,
    }

@router.patch("/api/documents/{job_id}")
async def rename_document(ctx: Ctx, job_id: str, payload: dict) -> dict[str, object]:
    """Rename a processed document wherever it is remembered.

    The name is on every inventory row of the document and, while the job is
    still on screen, on the job as well. Both are corrected in the same request:
    a rename that landed in only one of them would show the document twice in
    the archive, once under each name.

    The generated PDFs keep their own names, which come from the resolution
    number and not from the document that carried it.
    """
    name = str(payload.get("source_document") or payload.get("filename") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="El nombre no puede quedar vacío")
    if len(name) > 255:
        raise HTTPException(
            status_code=422, detail="El nombre no puede pasar de 255 caracteres"
        )
    # Es un nombre que se dibuja en la pantalla, no una ruta: una barra
    # convertiría un renombre en un salto a otra carpeta.
    if "/" in name or "\\" in name or not name.isprintable():
        raise HTTPException(
            status_code=422, detail="El nombre no puede contener barras"
        )

    rows = ctx.ledger.rename_document(job_id, name)
    job = ctx.registry.get(job_id)
    if job is not None:
        job.filename = name
        ctx.registry.publish(job)
    if rows == 0 and job is None:
        raise HTTPException(status_code=404, detail="El documento no existe")
    return {"job_id": job_id, "source_document": name, "rows": rows}

#: Cuántos documentos admite un borrado en lote. El tope no es una limitación
#: de la máquina sino del gesto: quinientos son más de los que nadie marca a
#: mano, y una petición mayor casi siempre es un error de quien la construyó.
MAX_BULK_DELETE = 500

def _erase_document(ctx: Contexto, job_id: str) -> dict[str, object]:
    """Borrar un documento entero: sus PDF, sus filas y su ficha.

    Devuelve lo que se borró, y levanta ``HTTPException`` cuando no se puede.
    El borrado de uno solo la deja pasar para responder con el código correcto;
    el borrado en lote la captura y la convierte en el motivo de esa fila.
    """
    job = ctx.registry.get(job_id)
    directory = ctx.settings.output_dir / job_id
    recorded = job_id in ctx.ledger.job_ids()
    if job is None and not recorded and not directory.is_dir():
        raise HTTPException(status_code=404, detail="El documento no existe")

    # Se comprueba antes de borrar nada: un documento a medio procesar todavía
    # está escribiendo en esa carpeta.
    if job is not None and ctx.registry.remove(job_id) is None:
        raise HTTPException(
            status_code=409, detail="El documento todavía se está procesando"
        )

    rows = ctx.ledger.remove_document(job_id)
    _discard_outputs(ctx, job_id)
    return {"job_id": job_id, "rows": rows, "from_screen": job is not None}

@router.delete("/api/documents/{job_id}")
async def delete_document(ctx: Ctx, job_id: str) -> dict[str, object]:
    """Erase a processed document: its PDFs, its inventory rows and its card.

    This is the one deletion that leaves nothing behind, which is why it is a
    separate route from clearing the screen: clearing forgets a job and keeps
    the work, this discards the work itself.
    """
    return _erase_document(ctx, job_id)

@router.delete("/api/documents")
async def delete_documents(ctx: Ctx, payload: dict) -> dict[str, object]:
    """Borrar varios documentos de una vez, diciendo qué pasó con cada uno.

    Va uno por uno y sigue adelante cuando alguno falla. No es una transacción y
    no debe parecerlo: borrar un documento son varias operaciones sobre disco y
    sobre el inventario, y fingir que veinte ocurren a la vez sólo serviría para
    que un fallo a la mitad dejara al operador sin saber qué se borró. Cada fila
    del resultado dice lo suyo, y la pantalla las enseña.

    El caso que de verdad importa es el documento que todavía se está
    procesando: se rechaza ése y se borran los demás, en vez de negar el lote
    entero por culpa de uno.
    """
    crudos = payload.get("job_ids")
    if not isinstance(crudos, list) or not crudos:
        raise HTTPException(
            status_code=422, detail="Hay que indicar qué documentos borrar"
        )
    if len(crudos) > MAX_BULK_DELETE:
        raise HTTPException(
            status_code=422,
            detail=f"Demasiados documentos de una vez: el máximo es {MAX_BULK_DELETE}",
        )

    borrados: list[dict[str, object]] = []
    fallidos: list[dict[str, object]] = []

    # Los repetidos se descartan conservando el orden de llegada: la pantalla
    # enseña el resultado en el mismo orden en que se marcaron las casillas.
    vistos: set[str] = set()
    for crudo in crudos:
        job_id = str(crudo or "").strip()
        if not job_id or job_id in vistos:
            continue
        vistos.add(job_id)
        try:
            borrados.append(_erase_document(ctx, job_id))
        except HTTPException as error:
            fallidos.append({"job_id": job_id, "reason": str(error.detail)})
        except Exception:  # noqa: BLE001 - uno que falla no para el lote
            # El motivo completo va al registro; a la pantalla, sólo que falló.
            # El texto de una excepción lleva rutas del disco y nombres internos
            # que no le sirven al operador y que no tienen por qué salir de aquí.
            logger.warning("no se pudo borrar el documento %s", job_id, exc_info=True)
            fallidos.append(
                {
                    "job_id": job_id,
                    "reason": "El servicio falló al borrarlo; revise el registro del backend",
                }
            )

    return {
        "deleted": borrados,
        "failed": fallidos,
        "rows": sum(int(item["rows"] or 0) for item in borrados),
    }

@router.get("/api/inventory.xlsx")
async def inventory_xlsx(ctx: Ctx, q: str | None = Query(None, max_length=MAX_BUSQUEDA)) -> Response:
    """Todo el inventario en un libro con formato, no en un CSV pelado.

    Un CSV se abre en Excel como texto crudo: sin anchos, sin bordes, sin
    encabezado, y con los números de resolución convertidos en números -- que es
    como 00072 se vuelve 72 y deja de servir. El libro llega ya formateado y
    listo para imprimir.
    """
    rows = _filtrar(ctx.ledger.rows(), q)

    try:
        from ...adapters.excel_inventory import ExcelRunInventory
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="El inventario en Excel necesita openpyxl instalado en el servicio",
        ) from None

    # El adaptador escribe en disco; se le da una carpeta que se borra sola.
    with tempfile.TemporaryDirectory() as folder:
        written = ExcelRunInventory().write(
            rows,
            Path(folder),
            source=f"Inventario completo{f' — filtro: {q}' if q else ''}",
            delivered_to="cada resolución en la carpeta de su documento",
        )
        content = written.read_bytes()

    return Response(
        content=content,
        media_type=XLSX_MEDIA,
        headers={"Content-Disposition": 'attachment; filename="inventario.xlsx"'},
    )

@router.get("/api/inventory.csv")
async def inventory_csv(ctx: Ctx, q: str | None = Query(None, max_length=MAX_BUSQUEDA)) -> Response:
    rows = _filtrar(ctx.ledger.rows(), q)
    return Response(
        # The BOM is what makes Excel open a UTF-8 CSV without mangling accents,
        # and a spreadsheet is where this file is actually read.
        content="﻿" + ctx.ledger.as_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="inventario.csv"'},
    )

#: Los campos por los que se busca una unidad en el archivo. Todos los que
#: describen el papel o de dónde salió, y ninguno de los internos: el id de un
#: trabajo es un hexadecimal de 32 letras que nadie teclea y que hace que
#: cualquier búsqueda de tres cifras devuelva media base.
CAMPOS_BUSCABLES = (
    "code",
    "title",
    "type",
    "fecha",
    "nic",
    "pages",
    "source_document",
    "file_name",
    "operator",
    "recorded_at",
)

def _matches(row: dict, needle: str) -> bool:
    """Si una fila del inventario responde a lo que se escribió en el buscador.

    Por cualquier dato que la describa -- su número, su tipo documental, su
    fecha, el NIC del expediente, el PDF del que salió, quién lo procesó -- y
    no sólo por su nombre de archivo. Es lo que pidió el operador: "buscar
    documento por cualquier parámetro relacionado".

    Varias palabras se exigen **todas**, y en cualquier campo: "factura 2022"
    encuentra las facturas del año pasado sin que ninguno de los dos términos
    tenga que estar en el mismo dato. Es como se busca en cualquier sitio, y
    con una sola caja de texto es lo que permite acotar de verdad.

    Sin tildes a los dos lados, porque el OCR las pone y las quita a su antojo
    y quien busca no va a escribirlas dos veces.
    """
    heno = strip_accents(
        " ".join(str(row.get(campo) or "") for campo in CAMPOS_BUSCABLES)
    ).lower()
    return all(termino in heno for termino in strip_accents(needle).lower().split())

def _filtrar(rows: list[dict], q: str | None) -> list[dict]:
    """Las filas que responden al buscador, o todas si no se escribió nada.

    Es el único filtro del archivo y lo usan las cuatro salidas que lo tienen
    -- la lista de resoluciones, la de documentos, el Excel y el CSV -- para
    que lo que se ve en pantalla sea exactamente lo que se descarga. Eran
    cuatro copias del mismo bucle, y una de ellas era distinta.
    """
    needle = (q or "").strip()
    if not needle:
        return rows
    return [row for row in rows if _matches(row, needle)]
