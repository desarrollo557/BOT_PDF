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

Sobrevive a un reinicio (2026-11-17): al terminar, el trabajo con personas por
mirar se guarda en disco (``guardar_los_por_revisar``) con dónde se entregó.
Sin el trabajo en memoria -- tras un reinicio, o porque la corrida sacó de ella
a los viejos -- la pantalla lo pide a ``GET /api/nombres-por-revisar``, y la
corrección va por la corrida si sigue abierta o, si no, por el disco
(``correccion_en_el_destino``).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ...adapters.renglon_del_nombre import recorte_del_nombre
from ...application.revisor_de_nombres import EN_LA_COLA
from ...domain.historia_academica import HISTORIA_ACADEMICA, Ficha
from ...domain.padron import (
    CONFIRMADO_POR_EL_OPERADOR,
    CORREGIDO_POR_EL_OPERADOR,
    Persona,
    cedula_de_persona,
    nombre_de_persona,
)
from ...domain.revision_de_nombres import (
    SE_LEYO_DISTINTO,
    con_el_nombre_cambiado,
    por_mirar,
)
from ..contexto import Ctx
from ..errores import explicar_fallo
from ..identidad import Quien, exigir_identificado

logger = logging.getLogger(__name__)

router = APIRouter()

#: Lo que la Revisión de nombres le quita a la cola al confirmarlo o corregirlo:
#: la duda del nombre, la diga la habilidad o el revisor común.
DUDAS_DEL_NOMBRE = (SE_LEYO_DISTINTO, EN_LA_COLA)
#: De qué habilidad es cada informe, para la regla de su nombre (``perfil.regla_del_nombre``).
HABILIDAD_DEL_INFORME = {
    "historia-academica": "historias",
    "nomina": "nominas",
    "certificado-tiempo": "certificados",
    "acta": "actas-de-grado",
}


def filas_de_personas(report: dict) -> list:
    """Las filas del informe en que puede haber una persona, en el orden en que se numeran.

    Primero las de ``inventario_actas`` (historias, nóminas, certificados,
    actas de grado) y después las del FUID ya hecho (``filas_del_fuid``:
    libros de diplomas y legajos de matrículas). La pantalla numera igual
    (``nombresPorMirar`` en ``web/src/lib/revision.ts``).
    """
    return [*(report.get("inventario_actas") or []), *(report.get("filas_del_fuid") or [])]


#: Lo del informe que se guarda para la Revisión de nombres: lo que lleva a las
#: personas y lo que hace falta para corregirlas sin el trabajo en memoria.
CLAVES_GUARDADAS = ("tipo", "document_type", "fuid", "inventario", "outputs", "inventario_actas", "filas_del_fuid")


def guardar_los_por_revisar(ctx, job) -> None:
    """El trabajo con personas por mirar, en disco; sin ninguna, se quita (2026-11-17).

    Al terminar el trabajo y tras cada confirmación o corrección. Guarda dónde
    se entrega lo suyo (``donde_se_entrega``) mientras la corrida está en
    memoria, y lo conserva después: es lo que deja corregir el destino tras un
    reinicio. Que falle no toca el trabajo.
    """
    almacen = getattr(ctx, "nombres_por_revisar", None)
    report = getattr(job, "report", None)
    if almacen is None or not isinstance(report, dict):
        return
    try:
        if not any(por_mirar(fila) for fila in filas_de_personas(report)):
            almacen.quitar(job.id)
            return
        informe = {clave: report[clave] for clave in CLAVES_GUARDADAS if clave in report}
        if (stats := report.get("stats")) and isinstance(stats, dict) and stats.get("document_type"):
            informe["stats"] = {"document_type": stats["document_type"]}
        donde = getattr(job, "en_el_destino", None)
        if donde is None and getattr(ctx, "folders", None) is not None:
            donde = ctx.folders.donde_se_entrega(job)
        if donde is None and (anterior := almacen.leer(job.id)):
            donde = anterior.get("en_el_destino")
        almacen.guardar(
            job.id,
            {
                "job_id": job.id,
                "documento": job.filename,
                "guardado": datetime.now(UTC).isoformat(),
                "oficina": getattr(job, "oficina", None),
                "origen": getattr(job, "origen", None) or {},
                "en_el_destino": donde,
                "informe": informe,
            },
        )
    except Exception:  # noqa: BLE001 - la Revisión en memoria sigue valiendo
        logger.warning("no se pudieron guardar los nombres por revisar de %s", job.filename, exc_info=True)


def _trabajo_guardado(ctx, job_id: str):
    """El trabajo como se guardó para la Revisión de nombres; ``None`` si no está.

    Tiene lo que la Revisión usa de un trabajo -- su nombre, su informe, su
    origen --, y ``guardado`` para no publicarlo en la pantalla en vivo.
    """
    almacen = getattr(ctx, "nombres_por_revisar", None)
    entrada = almacen.leer(job_id) if almacen is not None else None
    if not entrada or not isinstance(entrada.get("informe"), dict):
        return None
    return SimpleNamespace(
        id=job_id,
        filename=str(entrada.get("documento") or job_id),
        report=entrada["informe"],
        source=None,
        oficina=entrada.get("oficina"),
        origen=entrada.get("origen") or {},
        en_el_destino=entrada.get("en_el_destino"),
        guardado=True,
    )


def _trabajo_y_fila(ctx, job_id: str, numero: int):
    """El trabajo, la fila ``numero`` (de 1 en adelante) de su informe si es de una persona, y si es del FUID.

    Por su número y no por su página: los graduados de un acta colectiva
    comparten la página y el PDF del acta. Si el trabajo ya no está en
    memoria, el que se guardó para la Revisión.
    """
    job = ctx.registry.get(job_id)
    if job is None or not job.report:
        job = _trabajo_guardado(ctx, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ese trabajo ya no está en la pantalla.")
    filas = filas_de_personas(job.report)
    fila = filas[numero - 1] if 0 < numero <= len(filas) else None
    if not isinstance(fila, dict) or not (fila.get("nombre") or fila.get("revision_del_nombre")):
        raise HTTPException(status_code=404, detail=f"El trabajo no tiene una persona en la fila {numero}.")
    return job, fila, numero > len(job.report.get("inventario_actas") or [])


#: El archivo de una fila del FUID, en sus notas: «Archivo: 01_….pdf».
_ARCHIVO_EN_LAS_NOTAS = re.compile(r"Archivo: ([^;]+)")


def _archivo_de(fila: dict, del_fuid: bool) -> str | None:
    """Cómo se llama el PDF de la persona: el de su fila, o el que dicen sus notas en una del FUID."""
    if not del_fuid:
        return fila.get("archivo_generado")
    encontrado = _ARCHIVO_EN_LAS_NOTAS.search(str(fila.get("notas") or ""))
    return encontrado.group(1).strip() if encontrado else None


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
    """La regla del nombre de la habilidad del trabajo, por el tipo de su informe o el de su documento."""
    from ..retomar import tipo_del_informe
    from ..worker.nombres_asegurados import regla_del_nombre

    report = job.report or {}
    habilidad = HABILIDAD_DEL_INFORME.get(str(report.get("tipo") or "")) or tipo_del_informe(report)
    return regla_del_nombre(habilidad) if habilidad else None


@router.get("/api/jobs/{job_id}/nombres/{numero}/renglon.jpg")
async def renglon_del_nombre(ctx: Ctx, job_id: str, numero: int) -> Response:
    """Donde está escrito el nombre de la persona de la fila ``numero``, recortado para mirarlo sin abrir el PDF.

    Las zonas son las de la regla del nombre de su habilidad. La historia
    académica, la parte de arriba de su ficha -- que va primera en su PDF -- y
    el pie de sus notas; el acta colectiva, la hoja entera donde está su lista.
    """
    job, fila, del_fuid = _trabajo_y_fila(ctx, job_id, numero)
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
    salida = _salida_de(job.report, _archivo_de(fila, del_fuid))
    folios = int(fila.get("folios") or 1)
    pdf: Path | None = None
    if salida and (ruta := _dentro_del_trabajo(ctx, job_id, salida)).is_file():
        pdf = ruta
        # La historia lleva su ficha primero; en las demás, la hoja va donde estaba.
        hoja = 1 if historia else max(1, donde - inicial + 1)
        siguiente = hoja + 1 if folios > hoja else None
    elif job.source and Path(job.source).is_file():
        # Sólo se inventarió: la hoja en el original, mientras siga ahí.
        pdf, hoja = Path(job.source), donde
        final = int(fila.get("pagina_final") or inicial + folios - 1)
        siguiente = hoja + 1 if hoja < final else None
    elif (entregado := _en_el_destino(ctx, job, _archivo_de(fila, del_fuid), salida)) is not None:
        # Las salidas del servicio ya se limpiaron: el PDF que se entregó.
        pdf = entregado
        hoja = 1 if historia else max(1, donde - inicial + 1)
        siguiente = hoja + 1 if folios > hoja else None
    if pdf is None:
        raise HTTPException(status_code=404, detail="El PDF de esta persona ya no está en el servicio.")
    imagen = await asyncio.to_thread(recorte_del_nombre, pdf, hoja, siguiente, **zonas)
    if imagen is None:
        raise HTTPException(status_code=404, detail="No se pudo recortar el nombre de este PDF.")
    return Response(content=imagen, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


def _en_el_destino(ctx, job, archivo: str | None, salida: str | None) -> Path | None:
    """El PDF de la persona en el destino, por lo que se guardó de dónde se entrega; ``None`` si no está.

    El de las actas, en el espejo por su salida; el de las demás, en la
    carpeta de sus PDF. Una carpeta de red no se abre sin la corrida: no hay
    credenciales.
    """
    from ...adapters import red_smb

    donde = getattr(job, "en_el_destino", None)
    if donde is None and getattr(ctx, "folders", None) is not None:
        donde = ctx.folders.donde_se_entrega(job)
    if donde is None:
        donde = _guardado_en_el_destino(ctx, job.id)
    if not donde or not archivo:
        return None
    candidatos = []
    if salida and donde.get("espejo"):
        candidatos.append(Path(donde["espejo"]) / salida)
    if donde.get("carpeta"):
        candidatos.append(Path(donde["carpeta"]) / archivo)
    for candidato in candidatos:
        if red_smb.por_smb(str(candidato)):
            continue
        try:
            if candidato.is_file():
                return candidato
        except OSError:
            continue
    return None


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
    job, fila, del_fuid = _trabajo_y_fila(ctx, job_id, numero)
    fila_vieja = dict(fila)
    nuevo = nombre_de_persona(str(payload.get("nombre") or ""))
    if nuevo is None:
        raise HTTPException(
            status_code=422,
            detail="Escriba el nombre completo: al menos dos palabras de tres letras.",
        )
    report = job.report
    viejo_nombre = fila.get("nombre")
    viejo_archivo = _archivo_de(fila, del_fuid)
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
    fila["revision_del_nombre"] = revision
    if nuevo_asunto is not None:
        fila["asunto"] = nuevo_asunto
    if del_fuid:
        # Una fila del formato: su archivo va en sus notas, y nada de la
        # revisión se escribe en ellas -- el FUID va al cliente sin notas de
        # revisión --.
        if viejo_archivo and nuevo_archivo != viejo_archivo:
            fila["notas"] = str(fila.get("notas") or "").replace(f"Archivo: {viejo_archivo}", f"Archivo: {nuevo_archivo}")
    else:
        fila["archivo_generado"] = nuevo_archivo
    if not confirmacion and not del_fuid:
        nota = f"nombre corregido por el operador; se leyó «{viejo_nombre}»"
        fila["observaciones"] = "; ".join(parte for parte in (fila.get("observaciones"), nota) if parte)
    if not confirmacion and nuevo_salida != viejo_salida:
        report["outputs"] = [nuevo_salida if salida == viejo_salida else salida for salida in report.get("outputs") or []]
        for grupo in report.get("groups") or []:
            if isinstance(grupo, dict) and grupo.get("code") == viejo_archivo:
                grupo["code"] = nuevo_archivo
        for item in (report.get("inventory") or {}).get("items") or []:
            if isinstance(item, dict) and Path(str(item.get("file_name") or "")).name == viejo_archivo:
                item["file_name"] = str(Path(str(item["file_name"])).with_name(nuevo_archivo).as_posix())
    pagina_de_la_cola = revision.get("pagina_de_la_ficha") or fila.get("pagina_inicial")
    report["review_queue"] = [
        entrada
        for entrada in report.get("review_queue") or []
        if not (
            entrada.get("page") == pagina_de_la_cola
            and any(duda in str(entrada.get("reason") or "") for duda in DUDAS_DEL_NOMBRE)
        )
    ]

    # El FUID del trabajo, junto a sus PDF: el de un diploma o una matrícula,
    # con su plantilla y sólo la fila de la persona cambiada.
    if not confirmacion and del_fuid and report.get("fuid") and viejo_asunto and nuevo_asunto != viejo_asunto:
        try:
            from ..retomar import corregir_el_asunto

            ruta_del_fuid = _dentro_del_trabajo(ctx, job_id, str(report["fuid"]))
            if not await asyncio.to_thread(
                corregir_el_asunto,
                ruta_del_fuid,
                viejo_asunto,
                nuevo_asunto,
                orden=fila.get("orden"),
            ):
                avisos.append("el FUID del trabajo no trae la fila de esta persona: no se cambió")
        except Exception as error:  # noqa: BLE001 - el nombre ya está corregido; se dice qué faltó
            avisos.append(f"no se pudo reescribir el FUID del trabajo: {explicar_fallo(error)}")
    if not confirmacion and not del_fuid and report.get("inventario"):
        try:
            from ...adapters.fuid_de_la_entrega import escribir_fuid

            destino = _dentro_del_trabajo(ctx, job_id, str(report["inventario"]))
            await asyncio.to_thread(escribir_fuid, report.get("inventario_actas") or [], destino, oficina=job.oficina)
        except Exception as error:  # noqa: BLE001 - el nombre ya está corregido; se dice qué faltó
            avisos.append(f"no se pudo reescribir el FUID del trabajo: {explicar_fallo(error)}")

    # El destino de la corrida: el PDF, la constancia y los FUID de la carpeta.
    # Por la corrida si sigue en memoria; si no -- tras un reinicio --, por el
    # disco, con lo que se guardó de dónde se entrega.
    con_la_corrida = ctx.folders is not None and ctx.folders.tiene_la_corrida(job)
    de_una_corrida = (getattr(job, "origen", None) or {}).get("tipo") == "carpeta"
    if not confirmacion and not con_la_corrida and de_una_corrida:
        from ..correccion_en_el_destino import corregir_en_el_destino

        avisos += await asyncio.to_thread(
            corregir_en_el_destino,
            getattr(job, "en_el_destino", None) or _guardado_en_el_destino(ctx, job.id),
            int(fila.get("pagina_inicial") or 0),
            {
                "nombre": viejo_nombre,
                "archivo": viejo_archivo,
                "salida": viejo_salida,
                "asunto": viejo_asunto,
                "asunto_del_fuid": _asunto_en_el_fuid(fila_vieja, del_fuid),
            },
            {
                "nombre": nuevo,
                "archivo": nuevo_archivo,
                "salida": nuevo_salida,
                "asunto": nuevo_asunto,
                "asunto_del_fuid": _asunto_en_el_fuid(fila, del_fuid),
                "revision_del_nombre": revision,
            },
        )
    elif not confirmacion and con_la_corrida and del_fuid:
        avisos += await asyncio.to_thread(
            ctx.folders.corregir_nombre_del_fuid,
            job,
            int(fila.get("pagina_inicial") or 0),
            {"nombre": viejo_nombre, "asunto": viejo_asunto, "archivo": viejo_archivo},
            {
                "nombre": nuevo,
                "asunto": nuevo_asunto,
                "archivo": nuevo_archivo,
                "notas": fila.get("notas"),
                "revision_del_nombre": revision,
            },
        )
    elif not confirmacion and con_la_corrida:
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

    if not getattr(job, "guardado", False):
        ctx.registry.publish(job)
    # Lo que queda por mirar de este trabajo, en disco: sin nada, se quita.
    await asyncio.to_thread(guardar_los_por_revisar, ctx, job)
    logger.info(
        "%s: nombre de la fila %s %s por %s: «%s» → «%s»",
        job.filename, numero, "confirmado" if confirmacion else "corregido", quien.nombre if quien else "?",
        viejo_nombre, nuevo,
    )
    return {"nombre": nuevo, "archivo_generado": nuevo_archivo, "estado": revision["estado"], "avisos": avisos}


def _guardado_en_el_destino(ctx, job_id: str) -> dict | None:
    """Dónde se entrega lo del trabajo, según lo que se guardó para la Revisión."""
    almacen = getattr(ctx, "nombres_por_revisar", None)
    entrada = almacen.leer(job_id) if almacen is not None else None
    return (entrada or {}).get("en_el_destino")


def _asunto_en_el_fuid(fila: dict, del_fuid: bool) -> str | None:
    """El asunto de la fila como va escrito en el FUID entregado: con él se encuentra su celda.

    La fila del FUID lo trae tal cual; la de las demás habilidades, como la
    escribe el FUID de la entrega (``fila_del_fuid``): el de una historia es su
    nombre, el de un acta de grado «NOMBRE - ESPECIALIDAD».
    """
    if del_fuid:
        return fila.get("asunto")
    try:
        from ...adapters.fuid_de_la_entrega import fila_del_fuid

        hecha = fila_del_fuid(fila)
    except Exception:  # noqa: BLE001 - sin su asunto, el FUID no se toca
        return None
    return hecha.asunto if hecha is not None else None


@router.get("/api/nombres-por-revisar")
async def nombres_guardados(ctx: Ctx) -> list[dict[str, object]]:
    """Las personas por mirar de los trabajos que ya no están en memoria, como se guardaron (2026-11-17).

    Las de los trabajos en memoria las enseña la pantalla desde el trabajo en
    vivo; éstas son las que, sin esto, se perdían tras un reinicio o cuando la
    corrida sacaba de la memoria a los trabajos viejos. Cada una con su número
    de fila, el mismo con que se pide su renglón y se corrige.
    """
    almacen = getattr(ctx, "nombres_por_revisar", None)
    if almacen is None:
        return []
    salida: list[dict[str, object]] = []
    for entrada in await asyncio.to_thread(almacen.todas):
        job_id = str(entrada.get("job_id") or "")
        vivo = ctx.registry.get(job_id)
        if not job_id or (vivo is not None and vivo.report):
            continue
        for numero, fila in enumerate(filas_de_personas(entrada.get("informe") or {}), start=1):
            if por_mirar(fila):
                salida.append(
                    {"job_id": job_id, "documento": entrada.get("documento") or job_id, "numero": numero, "fila": fila}
                )
    return salida
