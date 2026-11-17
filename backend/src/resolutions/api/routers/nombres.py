"""La Revisión de los nombres de cada persona, en todas las habilidades: ver el renglón y corregirlo con un clic.

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
from ...domain.revision_de_nombres import SE_LEYO_DISTINTO, con_el_nombre_cambiado
from ..contexto import Ctx
from ..errores import explicar_fallo
from ..identidad import Quien, exigir_identificado

logger = logging.getLogger(__name__)

router = APIRouter()

#: Lo que la Revisión de nombres le quita a la cola al confirmarlo o corregirlo:
#: la duda del nombre, la diga la habilidad o el revisor común.
DUDA_DEL_NOMBRE = SE_LEYO_DISTINTO
#: De qué habilidad es cada informe, para la regla de su nombre (``perfil.regla_del_nombre``).
HABILIDAD_DEL_INFORME = {
    "historia-academica": "historias",
    "nomina": "nominas",
    "certificado-tiempo": "certificados",
    "acta": "actas-de-grado",
}


def _trabajo_y_fila(ctx, job_id: str, numero: int):
    """El trabajo y la fila ``numero`` (de 1 en adelante) de su informe, si es de una persona.

    Por su número y no por su página: los graduados de un acta colectiva
    comparten la página y el PDF del acta.
    """
    job = ctx.registry.get(job_id)
    if job is None or not job.report:
        raise HTTPException(status_code=404, detail="Ese trabajo ya no está en la pantalla.")
    filas = job.report.get("inventario_actas") or []
    fila = filas[numero - 1] if 0 < numero <= len(filas) else None
    if not isinstance(fila, dict) or not (fila.get("nombre") or fila.get("revision_del_nombre")):
        raise HTTPException(status_code=404, detail=f"El trabajo no tiene una persona en la fila {numero}.")
    return job, fila


def _salida_de(report: dict, archivo: str | None) -> str | None:
    """La ruta del PDF de la persona dentro del trabajo, por su nombre."""
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


def _regla_del_trabajo(job):
    """La regla del nombre de la habilidad del trabajo, por el tipo de su informe."""
    from ..worker.nombres_asegurados import regla_del_nombre

    habilidad = HABILIDAD_DEL_INFORME.get(str((job.report or {}).get("tipo") or ""))
    return regla_del_nombre(habilidad) if habilidad else None


@router.get("/api/jobs/{job_id}/nombres/{numero}/renglon.jpg")
async def renglon_del_nombre(ctx: Ctx, job_id: str, numero: int) -> Response:
    """Donde está escrito el nombre de la persona de la fila ``numero``, recortado para mirarlo sin abrir el PDF.

    Las zonas son las de la regla del nombre de su habilidad. La historia
    académica, la parte de arriba de su ficha -- que va primera en su PDF -- y
    el pie de sus notas; el acta colectiva, la hoja entera donde está su lista.
    """
    job, fila = _trabajo_y_fila(ctx, job_id, numero)
    regla = _regla_del_trabajo(job)
    revision = fila.get("revision_del_nombre") or {}
    inicial = int(fila.get("pagina_inicial") or 1)
    donde = int(revision.get("pagina_de_la_ficha") or inicial)
    historia = fila.get("tipo") == HISTORIA_ACADEMICA
    zonas = {}
    if fila.get("acta_colectiva"):
        zonas = {"zonas": ((0.0, 1.0),), "zonas_de_la_siguiente": ()}
    elif regla is not None and not historia:
        zonas = {"zonas": regla.zonas, "zonas_de_la_siguiente": regla.zonas_de_la_siguiente}
    salida = _salida_de(job.report, fila.get("archivo_generado"))
    pdf: Path | None = None
    if salida and (ruta := _dentro_del_trabajo(ctx, job_id, salida)).is_file():
        pdf = ruta
        # La historia lleva su ficha primero; en las demás, la hoja va donde estaba.
        hoja = 1 if historia else max(1, donde - inicial + 1)
        siguiente = hoja + 1 if int(fila.get("folios") or 1) > hoja else None
    elif job.source and Path(job.source).is_file():
        # Sólo se inventarió: la hoja en el original, mientras siga ahí.
        pdf, hoja = Path(job.source), donde
        siguiente = hoja + 1 if hoja < int(fila.get("pagina_final") or hoja) else None
    if pdf is None:
        raise HTTPException(status_code=404, detail="El PDF de esta persona ya no está en el servicio.")
    imagen = await asyncio.to_thread(recorte_del_nombre, pdf, hoja, siguiente, **zonas)
    if imagen is None:
        raise HTTPException(status_code=404, detail="No se pudo recortar el nombre de este PDF.")
    return Response(content=imagen, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


def _nombre_nuevo_del_pdf(ctx, job_id, fila, viejo_nombre, viejo_archivo, viejo_salida, nuevo) -> str | None:
    """Cómo se llama el PDF con el nombre corregido; ``None`` si su nombre no lleva el de la persona.

    La historia académica, con el nombre que le pondría el bot (``_nombre_del_pdf``).
    Las demás, cambiando el nombre dentro del de su PDF, en la forma en que lo
    traiga: el PDF del acta colectiva no lleva el de ningún graduado, y no cambia.
    """
    if fila.get("tipo") == HISTORIA_ACADEMICA:
        from ..worker.historias import _nombre_del_pdf

        prefijo = viejo_archivo.split("_", 1)[0]
        orden = int(prefijo) if prefijo.isdigit() else 0
        ficha = Ficha(nombre=nuevo, cedula=fila.get("cedula"), tarjeta=fila.get("tarjeta"), libreta=fila.get("libreta"))
        ruta_vieja = _dentro_del_trabajo(ctx, job_id, viejo_salida) if viejo_salida else None
        return _nombre_del_pdf(
            orden,
            ficha,
            carpeta=ruta_vieja.parent if ruta_vieja else None,
            paginas=(int(fila.get("pagina_inicial") or 0), int(fila.get("pagina_final") or 0)),
        )
    return con_el_nombre_cambiado(viejo_archivo, viejo_nombre, nuevo)


@router.put("/api/jobs/{job_id}/nombres/{numero}")
async def corregir_nombre(ctx: Ctx, job_id: str, numero: int, payload: dict, quien: Quien) -> dict[str, object]:
    """Confirma o corrige el nombre de la persona de la fila ``numero``; todo lo que lo lleva se mueve junto.

    El mismo nombre que ya tenía es una confirmación: sale de la cola y va al
    padrón. Uno distinto es una corrección.
    """
    exigir_identificado(quien)
    job, fila = _trabajo_y_fila(ctx, job_id, numero)
    nuevo = nombre_de_persona(str(payload.get("nombre") or ""))
    if nuevo is None:
        raise HTTPException(
            status_code=422,
            detail="Escriba el nombre completo: al menos dos palabras de tres letras.",
        )
    report = job.report
    viejo_nombre = fila.get("nombre")
    viejo_archivo = fila.get("archivo_generado")
    viejo_asunto = fila.get("asunto")
    viejo_salida = _salida_de(report, viejo_archivo)
    avisos: list[str] = []
    confirmacion = nuevo == viejo_nombre
    revision = {**(fila.get("revision_del_nombre") or {})}
    revision["estado"] = CONFIRMADO_POR_EL_OPERADOR if confirmacion else CORREGIDO_POR_EL_OPERADOR
    if not confirmacion:
        revision.setdefault("leido", viejo_nombre)

    nuevo_archivo, nuevo_salida = viejo_archivo, viejo_salida
    if not confirmacion and viejo_archivo:
        nuevo_archivo = (
            _nombre_nuevo_del_pdf(ctx, job_id, fila, viejo_nombre, viejo_archivo, viejo_salida, nuevo) or viejo_archivo
        )
        if viejo_salida and nuevo_archivo != viejo_archivo:
            ruta_vieja = _dentro_del_trabajo(ctx, job_id, viejo_salida)
            nuevo_salida = str(Path(viejo_salida).with_name(nuevo_archivo).as_posix())
            ruta_nueva = _dentro_del_trabajo(ctx, job_id, nuevo_salida)
            if ruta_nueva.exists():
                raise HTTPException(status_code=409, detail=f"Ya hay un PDF que se llama «{nuevo_archivo}».")
            if ruta_vieja.exists():
                try:
                    os.replace(ruta_vieja, ruta_nueva)
                except OSError as error:
                    raise HTTPException(
                        status_code=409, detail=f"No se pudo renombrar el PDF: {explicar_fallo(error)}"
                    ) from None
    nuevo_asunto = (con_el_nombre_cambiado(viejo_asunto, viejo_nombre, nuevo) or viejo_asunto) if viejo_asunto else None

    # La fila y el informe que ve la pantalla.
    fila["nombre"] = nuevo
    fila["archivo_generado"] = nuevo_archivo
    fila["revision_del_nombre"] = revision
    if nuevo_asunto is not None:
        fila["asunto"] = nuevo_asunto
    if not confirmacion:
        nota = f"nombre corregido por el operador; se leyó «{viejo_nombre}»"
        fila["observaciones"] = "; ".join(parte for parte in (fila.get("observaciones"), nota) if parte)
        if nuevo_salida != viejo_salida:
            report["outputs"] = [nuevo_salida if salida == viejo_salida else salida for salida in report.get("outputs") or []]
            for grupo in report.get("groups") or []:
                if isinstance(grupo, dict) and grupo.get("code") == viejo_archivo:
                    grupo["code"] = nuevo_archivo
    pagina_de_la_cola = revision.get("pagina_de_la_ficha") or fila.get("pagina_inicial")
    report["review_queue"] = [
        entrada
        for entrada in report.get("review_queue") or []
        if not (entrada.get("page") == pagina_de_la_cola and DUDA_DEL_NOMBRE in str(entrada.get("reason") or ""))
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
            int(fila.get("pagina_inicial") or 0),
            {"nombre": viejo_nombre, "archivo_generado": viejo_archivo, "salida": viejo_salida},
            {
                "nombre": nuevo,
                "archivo_generado": nuevo_archivo,
                "salida": nuevo_salida,
                "revision_del_nombre": revision,
                **({"asunto": nuevo_asunto} if nuevo_asunto is not None else {}),
            },
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
        "%s: nombre de la fila %s %s por %s: «%s» → «%s»",
        job.filename, numero, "confirmado" if confirmacion else "corregido", quien.nombre if quien else "?",
        viejo_nombre, nuevo,
    )
    return {"nombre": nuevo, "archivo_generado": nuevo_archivo, "estado": revision["estado"], "avisos": avisos}
