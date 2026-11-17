"""La Revisión de los nombres de las historias académicas: ver el renglón y corregirlo con un clic.

El operador (2026-11-17), con los nombres de Enfermería delante: «la idea es
tener los nombres de manera correcta». La máquina vota las lecturas y la IA mira
el renglón, pero lo que no se confirma -- y lo que la IA cambió -- lo mira una
persona: la pantalla de Revisión enseña la imagen del renglón, lo que leyó cada
lectura y el nombre que quedó, y el operador lo confirma o lo corrige.

Corregir mueve todo junto: el nombre en la fila y en el FUID del trabajo, el
PDF del estudiante -- en el trabajo y en el destino --, la constancia de la
entrega, el FUID de la subcarpeta y el general (``FolderRunner.corregir_nombre``).
Y lo que el operador dice va al padrón de la Universidad (``domain/padron.py``):
la próxima vez que esa cédula aparezca, su nombre ya está escrito.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ...adapters.renglon_del_nombre import recorte_del_nombre
from ...domain.historia_academica import HISTORIA_ACADEMICA, Ficha
from ...domain.padron import (
    CONFIRMADO_POR_EL_OPERADOR,
    CORREGIDO_POR_EL_OPERADOR,
    Persona,
    cedula_de_persona,
    nombre_de_persona,
)
from ..contexto import Ctx
from ..errores import explicar_fallo
from ..identidad import Quien, exigir_identificado

logger = logging.getLogger(__name__)

router = APIRouter()

#: Lo que la Revisión de nombres le quita a la cola al confirmarlo o corregirlo.
DUDA_DEL_NOMBRE = "el nombre se leyó distinto"


def _trabajo_y_fila(ctx, job_id: str, pagina: int):
    job = ctx.registry.get(job_id)
    if job is None or not job.report:
        raise HTTPException(status_code=404, detail="Ese trabajo ya no está en la pantalla.")
    fila = next(
        (
            fila
            for fila in job.report.get("inventario_actas") or []
            if isinstance(fila, dict) and fila.get("tipo") == HISTORIA_ACADEMICA and fila.get("pagina_inicial") == pagina
        ),
        None,
    )
    if fila is None:
        raise HTTPException(status_code=404, detail=f"El trabajo no tiene un estudiante que empiece en la página {pagina}.")
    return job, fila


def _salida_de(report: dict, archivo: str | None) -> str | None:
    """La ruta del PDF del estudiante dentro del trabajo, por su nombre."""
    if not archivo:
        return None
    return next(
        (str(salida) for salida in report.get("outputs") or [] if Path(str(salida)).name == archivo),
        None,
    )


def _dentro_del_trabajo(ctx, job_id: str, relativa: str) -> Path:
    """La ruta dentro de la carpeta del trabajo, sin salirse de ella."""
    raiz = (Path(ctx.settings.output_dir) / job_id).resolve()
    ruta = (raiz / relativa).resolve()
    if raiz not in ruta.parents:
        raise HTTPException(status_code=400, detail="Esa ruta no es de este trabajo.")
    return ruta


@router.get("/api/jobs/{job_id}/nombres/{pagina}/renglon.jpg")
async def renglon_del_nombre(ctx: Ctx, job_id: str, pagina: int) -> Response:
    """La parte de arriba de la ficha del estudiante y el pie de sus notas, para mirar su nombre."""
    job, fila = _trabajo_y_fila(ctx, job_id, pagina)
    salida = _salida_de(job.report, fila.get("archivo_generado"))
    pdf: Path | None = None
    if salida and (ruta := _dentro_del_trabajo(ctx, job_id, salida)).is_file():
        # El PDF del estudiante empieza por su ficha, y la hoja que sigue son sus notas.
        pdf, ficha = ruta, 1
        notas = 2 if int(fila.get("folios") or 1) >= 2 else None
    elif job.source and Path(job.source).is_file():
        # Sólo se inventarió: la ficha en el original, mientras siga ahí.
        pdf = Path(job.source)
        ficha = int((fila.get("revision_del_nombre") or {}).get("pagina_de_la_ficha") or pagina)
        notas = ficha + 1 if ficha < int(fila.get("pagina_final") or ficha) else None
    if pdf is None:
        raise HTTPException(status_code=404, detail="El PDF de este estudiante ya no está en el servicio.")
    imagen = await asyncio.to_thread(recorte_del_nombre, pdf, ficha, notas)
    if imagen is None:
        raise HTTPException(status_code=404, detail="No se pudo recortar el nombre de este PDF.")
    return Response(content=imagen, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.put("/api/jobs/{job_id}/nombres/{pagina}")
async def corregir_nombre(ctx: Ctx, job_id: str, pagina: int, payload: dict, quien: Quien) -> dict[str, object]:
    """Confirma o corrige el nombre de un estudiante; todo lo que lo lleva se mueve junto.

    El mismo nombre que ya tenía es una confirmación: sale de la cola y va al
    padrón. Uno distinto es una corrección.
    """
    exigir_identificado(quien)
    job, fila = _trabajo_y_fila(ctx, job_id, pagina)
    nuevo = nombre_de_persona(str(payload.get("nombre") or ""))
    if nuevo is None:
        raise HTTPException(
            status_code=422,
            detail="Escriba el nombre completo, con los apellidos primero: al menos dos palabras de tres letras.",
        )
    report = job.report
    viejo_nombre = fila.get("nombre")
    viejo_archivo = fila.get("archivo_generado")
    viejo_salida = _salida_de(report, viejo_archivo)
    avisos: list[str] = []
    confirmacion = nuevo == viejo_nombre
    revision = {**(fila.get("revision_del_nombre") or {})}
    revision["estado"] = CONFIRMADO_POR_EL_OPERADOR if confirmacion else CORREGIDO_POR_EL_OPERADOR
    if not confirmacion:
        revision.setdefault("leido", viejo_nombre)

    nuevo_archivo, nuevo_salida = viejo_archivo, viejo_salida
    if not confirmacion and viejo_archivo:
        from ..worker.historias import _nombre_del_pdf

        prefijo = viejo_archivo.split("_", 1)[0]
        orden = int(prefijo) if prefijo.isdigit() else 0
        ficha = Ficha(nombre=nuevo, cedula=fila.get("cedula"), tarjeta=fila.get("tarjeta"), libreta=fila.get("libreta"))
        ruta_vieja = _dentro_del_trabajo(ctx, job_id, viejo_salida) if viejo_salida else None
        nuevo_archivo = _nombre_del_pdf(
            orden,
            ficha,
            carpeta=ruta_vieja.parent if ruta_vieja else None,
            paginas=(int(fila.get("pagina_inicial") or 0), int(fila.get("pagina_final") or 0)),
        )
        if viejo_salida:
            nuevo_salida = str(Path(viejo_salida).with_name(nuevo_archivo).as_posix())
            ruta_nueva = _dentro_del_trabajo(ctx, job_id, nuevo_salida)
            if ruta_nueva != ruta_vieja and ruta_nueva.exists():
                raise HTTPException(status_code=409, detail=f"Ya hay un PDF que se llama «{nuevo_archivo}».")
            if ruta_vieja is not None and ruta_vieja.exists() and ruta_nueva != ruta_vieja:
                try:
                    os.replace(ruta_vieja, ruta_nueva)
                except OSError as error:
                    raise HTTPException(
                        status_code=409, detail=f"No se pudo renombrar el PDF: {explicar_fallo(error)}"
                    ) from None

    # La fila y el informe que ve la pantalla.
    fila["nombre"] = nuevo
    fila["archivo_generado"] = nuevo_archivo
    fila["revision_del_nombre"] = revision
    if not confirmacion:
        nota = f"nombre corregido por el operador; se leyó «{viejo_nombre}»"
        fila["observaciones"] = "; ".join(parte for parte in (fila.get("observaciones"), nota) if parte)
        report["outputs"] = [nuevo_salida if salida == viejo_salida else salida for salida in report.get("outputs") or []]
        for grupo in report.get("groups") or []:
            if isinstance(grupo, dict) and grupo.get("code") == viejo_archivo:
                grupo["code"] = nuevo_archivo
    ficha_de_la_cola = revision.get("pagina_de_la_ficha") or pagina
    report["review_queue"] = [
        entrada
        for entrada in report.get("review_queue") or []
        if not (entrada.get("page") == ficha_de_la_cola and str(entrada.get("reason") or "").startswith(DUDA_DEL_NOMBRE))
    ]

    # El FUID del trabajo, junto a sus PDF.
    if not confirmacion and report.get("inventario"):
        try:
            from ...adapters.fuid_de_la_entrega import escribir_fuid

            destino = _dentro_del_trabajo(ctx, job_id, str(report["inventario"]))
            await asyncio.to_thread(escribir_fuid, report.get("inventario_actas") or [], destino, oficina=job.oficina)
        except Exception as error:  # noqa: BLE001 - el nombre ya está corregido; se dice qué faltó
            avisos.append(f"no se pudo reescribir el FUID del trabajo: {explicar_fallo(error)}")

    # El destino de la corrida: el PDF, la constancia y los FUID de la carpeta.
    if not confirmacion and ctx.folders is not None:
        avisos += await asyncio.to_thread(
            ctx.folders.corregir_nombre,
            job,
            pagina,
            {"nombre": viejo_nombre, "archivo_generado": viejo_archivo, "salida": viejo_salida},
            {"nombre": nuevo, "archivo_generado": nuevo_archivo, "salida": nuevo_salida, "revision_del_nombre": revision},
        )

    # Lo que dijo una persona, al padrón: la próxima vez esa cédula ya trae su nombre.
    if ctx.padron is not None:
        try:
            ctx.padron.anotar([
                Persona(
                    nuevo,
                    cedula_de_persona(fila.get("cedula")),
                    revision["estado"],
                    job.filename,
                    date.today().isoformat(),
                )
            ])
        except Exception:  # noqa: BLE001 - la corrección ya se hizo
            logger.warning("no se pudo anotar en el padrón el nombre de %s", job.filename, exc_info=True)

    ctx.registry.publish(job)
    logger.info(
        "%s: nombre de la página %s %s por %s: «%s» → «%s»",
        job.filename, pagina, "confirmado" if confirmacion else "corregido", quien.nombre if quien else "?",
        viejo_nombre, nuevo,
    )
    return {"nombre": nuevo, "archivo_generado": nuevo_archivo, "estado": revision["estado"], "avisos": avisos}
