"""La Revisión del RE: el operador confirma un candidato o escribe el RE que la máquina no leyó con certeza.

Lo decidió el operador el 2026-11-18 («NUNCA INVENTAR INFORMACIÓN»): un RE va
al nombre sólo si sus hojas lo traen tal cual (``domain.evidencia``). Lo que
la máquina sólo sugiere -- un solo lector, una corrección, el RE de su
trámite -- queda como candidato, y el documento en Revisión. Aquí se cierra:
la pantalla enseña la hoja y los candidatos, y el operador confirma uno o
escribe el que ve en el papel.

Corregir mueve todo junto: el PDF y el informe del trabajo, su índice y, con
la corrida abierta, el PDF entregado en la carpeta del NIC, su constancia, el
índice del NIC y los generales (``FolderRunner.corregir_re``).
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

from ...domain.evidencia import Estado, Hallazgo
from ...domain.nombre_oficial import con_su_re, con_su_re_en_la_ruta, es_re
from ...domain.sello import OFICINAS_QUE_RADICAN
from ..contexto import Ctx
from ..identidad import Quien, exigir_identificado

router = APIRouter()
logger = logging.getLogger(__name__)
#: Un cerrojo por trabajo para el «Confirmar» del RE.
_cerrojos_de_los_trabajos: dict[str, asyncio.Lock] = {}


def _cerrojo_del_trabajo(job_id: str) -> asyncio.Lock:
    return _cerrojos_de_los_trabajos.setdefault(job_id, asyncio.Lock())

#: Lo que el operador escribe: «RE» y trece cifras, con los blancos que quiera.
_LO_ESCRITO = re.compile(r"[\s.\-]")
_RE = re.compile(r"RE\d{13}")
#: A cuántos puntos por pulgada se enseña la hoja: se lee el sello sin pesar mucho.
PPP_DE_LA_HOJA = 110
#: El número delante del título de un PDF: «03_RECLAMO.pdf».
_NUMERO = re.compile(r"^(\d+)_")


#: Lo del informe que se guarda para corregir el RE sin el trabajo en memoria.
CLAVES_GUARDADAS = (
    "inventory",
    "groups",
    "outputs",
    "review_queue",
    "evidencia",
    "decisiones_del_agente",
    "re_en_el_nombre",
    "donde_se_entrega_el_re",
    "page_count",
)
#: Lo que deja una decisión del agente cuando la cambia o la confirma el operador.
CONFIRMADO = "confirmado por el operador"


def guardar_los_re_decididos(ctx, job) -> None:
    """El trabajo con RE decididos por el agente, en disco; sin ninguno, se quita (2026-11-23).

    Al terminar el trabajo y tras cada corrección: el operador audita los de
    confianza baja y los cambia aunque el bot se haya reiniciado. Con dónde se
    entregó, para corregir lo entregado sin la corrida. Que falle no toca el
    trabajo.
    """
    almacen = getattr(ctx, "re_por_revisar", None)
    report = getattr(job, "report", None)
    if almacen is None or not isinstance(report, dict):
        return
    try:
        if not report.get("decisiones_del_agente"):
            almacen.quitar(job.id)
            return
        informe = {clave: report[clave] for clave in CLAVES_GUARDADAS if clave in report}
        donde = report.get("donde_se_entrega_el_re")
        if not donde and getattr(ctx, "folders", None) is not None:
            donde = ctx.folders.donde_se_entrega(job)
        if not donde and (anterior := almacen.leer(job.id)):
            donde = (anterior.get("informe") or {}).get("donde_se_entrega_el_re")
        if donde:
            informe["donde_se_entrega_el_re"] = donde
        almacen.guardar(
            job.id,
            {
                "job_id": job.id,
                "documento": job.filename,
                "guardado": datetime.now(UTC).isoformat(),
                "origen": getattr(job, "origen", None) or {},
                "informe": informe,
            },
        )
    except Exception:  # noqa: BLE001 - la Revisión en memoria sigue valiendo
        logger.warning("no se pudieron guardar los RE decididos de %s", getattr(job, "filename", ""), exc_info=True)


def _trabajo_guardado(ctx, job_id: str):
    """El trabajo como se guardó para la Revisión del RE; ``None`` si no está."""
    almacen = getattr(ctx, "re_por_revisar", None)
    entrada = almacen.leer(job_id) if almacen is not None else None
    if not entrada or not isinstance(entrada.get("informe"), dict):
        return None
    return SimpleNamespace(
        id=job_id,
        filename=str(entrada.get("documento") or job_id),
        report=entrada["informe"],
        origen=entrada.get("origen") or {},
        source=None,
        guardado=True,
    )


def _trabajo(ctx, job_id: str):
    job = ctx.registry.get(job_id)
    if job is not None and job.report:
        return job
    # Tras un reinicio, o cuando la corrida sacó al trabajo de la memoria: lo
    # que se guardó de él (2026-11-23).
    guardado = _trabajo_guardado(ctx, job_id)
    if guardado is None:
        raise HTTPException(status_code=404, detail="Ese trabajo ya no está en el servicio.")
    return guardado


def _items(report: dict) -> list[dict]:
    return [i for i in (report.get("inventory") or {}).get("items") or [] if isinstance(i, dict)]


def _documento(report: dict, pagina: int) -> dict:
    """El documento que contiene la hoja ``pagina``."""
    for item in _items(report):
        if pagina in (item.get("page_numbers") or []):
            return item
    raise HTTPException(status_code=404, detail="Ninguno de los documentos de este trabajo trae esa hoja.")


def _numero(nombre: str) -> int:
    hallado = _NUMERO.match(Path(nombre).name)
    return int(hallado.group(1)) if hallado else 0


def _posicion_en_su_carpeta(report: dict, item: dict) -> int:
    """El puesto del documento entre los PDF de su UPD, por su número: el de su constancia y su índice."""
    carpeta = Path(str(item.get("file_name") or "")).parent
    suyos = sorted(
        (i for i in _items(report) if Path(str(i.get("file_name") or "")).parent == carpeta),
        key=lambda i: _numero(str(i.get("file_name") or "")),
    )
    return next(n for n, i in enumerate(suyos) if i is item)


def _dentro_del_trabajo(ctx, job_id: str, relativa: str) -> Path:
    raiz = (Path(ctx.settings.output_dir) / job_id).resolve()
    ruta = (raiz / relativa).resolve()
    if raiz not in ruta.parents:
        raise HTTPException(status_code=400, detail="Esa ruta no es de este trabajo.")
    return ruta


def _la_hoja(pdf: Path, numero: int) -> bytes | None:
    import pymupdf

    with pymupdf.open(pdf) as documento:
        if not 1 <= numero <= documento.page_count:
            return None
        return documento[numero - 1].get_pixmap(dpi=PPP_DE_LA_HOJA).tobytes("jpeg")


@router.get("/api/jobs/{job_id}/re/{pagina}/hoja.jpg")
async def hoja_del_re(ctx: Ctx, job_id: str, pagina: int) -> Response:
    """La hoja donde está la evidencia del RE, para leer el sello sin abrir el PDF.

    Del original mientras siga en el servicio; si no, del PDF del documento
    dentro del trabajo, en su puesto.
    """
    job = _trabajo(ctx, job_id)
    pdf, numero = None, pagina
    if job.source and Path(job.source).is_file():
        pdf = Path(job.source)
    else:
        item = _documento(job.report, pagina)
        hojas = list(item.get("orden") or item.get("page_numbers") or [])
        salida = _dentro_del_trabajo(ctx, job_id, str(item.get("file_name") or ""))
        if salida.is_file() and pagina in hojas:
            pdf, numero = salida, hojas.index(pagina) + 1
    if pdf is None:
        raise HTTPException(status_code=404, detail="El PDF de esta hoja ya no está en el servicio.")
    imagen = await asyncio.to_thread(_la_hoja, pdf, numero)
    if imagen is None:
        raise HTTPException(status_code=404, detail="No se pudo dibujar esa hoja.")
    return Response(content=imagen, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


def _avisos_del_re(radicado: str) -> list[str]:
    """Lo raro de un RE bien formado: no lo bloquea, porque el operador tiene el papel delante."""
    avisos = []
    if radicado[2:6] not in OFICINAS_QUE_RADICAN:
        avisos.append(f"la oficina {radicado[2:6]} no es una de las que radican en la caja; se dejó como lo escribió")
    if not 2000 <= int(radicado[6:10]) <= date.today().year:
        avisos.append(f"el año {radicado[6:10]} no parece el de un radicado; se dejó como lo escribió")
    return avisos


def _el_de_la_fila(nombre: str) -> str:
    """El nombre de la fila del índice, sin RE y sin separadores, para buscarla: «RECLAMO», «RECURSO DE REPOSICION…»."""
    sin_re = re.sub(r"-RE\d{13}$", "", (nombre or "").strip(), flags=re.IGNORECASE)
    return re.sub(r"[\s_-]+", " ", sin_re).strip().upper()


def _corregir_el_indice_del_trabajo(ctx, job, item: dict, radicado: str, posicion: int) -> list[str]:
    """La fila del documento en el índice que el trabajo dejó junto a sus PDF, con su RE."""
    from ...adapters.indice_electronico import (
        NOMBRE_DEL_INDICE,
        cambiar_el_nombre,
        leer_indice,
    )

    carpeta = Path(str(item.get("file_name") or "")).parent
    ruta = _dentro_del_trabajo(ctx, job.id, str(carpeta / NOMBRE_DEL_INDICE))
    if not ruta.is_file():
        return []
    titulo = _el_de_la_fila(_NUMERO.sub("", Path(str(item.get("file_name") or "")).stem))
    try:
        filas = leer_indice(ruta).filas
        iguales = [f.nombre for f in filas if _el_de_la_fila(f.nombre) == titulo]
        # Las de su mismo título van en el orden de sus PDF.
        hermanos = sorted(
            (i for i in _items(job.report) if Path(str(i.get("file_name") or "")).parent == carpeta),
            key=lambda i: _numero(str(i.get("file_name") or "")),
        )
        ocurrencia = sum(
            1
            for i in hermanos[:posicion]
            if _el_de_la_fila(_NUMERO.sub("", Path(str(i.get("file_name") or "")).stem)) == titulo
        )
        if ocurrencia >= len(iguales):
            return ["la fila de este documento no está en el índice del trabajo"]
        viejo = iguales[ocurrencia]
        cambiar_el_nombre(ruta, viejo, con_su_re(viejo, radicado), ocurrencia=iguales[:ocurrencia].count(viejo))
    except Exception:  # noqa: BLE001 - el PDF ya se corrigió; se dice qué faltó
        return ["no se pudo corregir el índice del trabajo"]
    return []


@router.put("/api/jobs/{job_id}/re/{pagina}")
async def corregir_re(ctx: Ctx, job_id: str, pagina: int, payload: dict, quien: Quien) -> dict[str, object]:
    """El RE del documento que contiene la hoja ``pagina``, confirmado o escrito por el operador.

    Exige «RE» y trece cifras. Renombra el PDF en el trabajo y, con la corrida
    abierta, en el destino; corrige el informe, el índice y la evidencia, que
    pasa a «verificado» por el operador. La oficina o el año raros dan un
    aviso, no lo bloquean.
    """
    usuario = exigir_identificado(quien)
    radicado = _LO_ESCRITO.sub("", str(payload.get("re") or "")).upper()
    if not _RE.fullmatch(radicado):
        raise HTTPException(status_code=422, detail="Un RE es «RE» y trece cifras: «RE2310202402908».")
    # De uno en uno por trabajo: dos «Confirmar» seguidos sobre un trabajo
    # guardado se pisaban (la verificación del 2026-11-23).
    async with _cerrojo_del_trabajo(job_id):
        return await _corregir_re(ctx, job_id, pagina, radicado, usuario)


async def _corregir_re(ctx, job_id: str, pagina: int, radicado: str, usuario) -> dict[str, object]:
    job = _trabajo(ctx, job_id)
    report = job.report
    item = _documento(report, pagina)
    posicion = _posicion_en_su_carpeta(report, item)
    viejo = str(item.get("file_name") or "")
    nuevo = con_su_re_en_la_ruta(viejo, radicado)
    avisos = _avisos_del_re(radicado)

    if nuevo != viejo:
        antes, despues = _dentro_del_trabajo(ctx, job_id, viejo), _dentro_del_trabajo(ctx, job_id, nuevo)
        if despues.exists():
            raise HTTPException(status_code=409, detail=f"Ya hay un «{despues.name}» en este trabajo.")
        if antes.exists():
            os.replace(antes, despues)
        avisos += _corregir_el_indice_del_trabajo(ctx, job, item, radicado, posicion)

    # El informe: el documento, su salida, su grupo, su evidencia y su Revisión.
    item["file_name"] = nuevo
    report["outputs"] = [
        con_su_re_en_la_ruta(str(s), radicado) if Path(str(s)).name == Path(viejo).name else s
        for s in report.get("outputs") or []
    ]
    hojas = set(item.get("page_numbers") or [])
    primera = min(hojas) if hojas else pagina
    for grupo in report.get("groups") or []:
        if isinstance(grupo, dict) and hojas & set(grupo.get("pages") or []):
            numero, _, resto = str(grupo.get("code") or "").partition(" ")
            grupo["code"] = " ".join([numero, *(p for p in resto.split() if not es_re(p)), radicado]).strip()
    report.setdefault("re_en_el_nombre", {})[str(primera)] = f"{radicado}: confirmado por el operador"
    antes_del_operador = ((report.get("evidencia") or {}).get("re") or {}).get(str(primera)) or {}
    report.setdefault("evidencia", {}).setdefault("re", {})[str(primera)] = {
        **Hallazgo(
            parametro="re",
            estado=Estado.VERIFICADO,
            valor=radicado,
            valor_original=radicado,
            pagina=pagina,
            metodo="confirmado por el operador",
            lectores=("operador",),
            confianza="alta",
            motivo=f"antes: {antes_del_operador.get('estado') or 'sin evidencia'}",
        ).as_dict(),
        "quien": getattr(usuario, "nombre", None) or getattr(usuario, "cedula", None),
    }
    from ..correccion_del_re import es_aviso_del_re

    report["review_queue"] = [
        r
        for r in report.get("review_queue") or []
        if not (isinstance(r, dict) and r.get("page") in hojas and es_aviso_del_re(str(r.get("reason") or "")))
    ]

    # El destino: con la corrida abierta, por ella; si ya no está, por las
    # rutas que la entrega guardó en el informe (2026-11-23).
    folders = getattr(ctx, "folders", None)
    nombre_de_quien = getattr(usuario, "nombre", None) or getattr(usuario, "cedula", None)
    if folders is not None and folders.tiene_la_corrida(job):
        avisos += await asyncio.to_thread(folders.corregir_re, job, posicion, radicado, nombre_de_quien)
    elif report.get("donde_se_entrega_el_re"):
        from ..correccion_del_re import corregir_re_en_el_destino

        avisos += await asyncio.to_thread(
            corregir_re_en_el_destino,
            report["donde_se_entrega_el_re"],
            posicion,
            radicado,
            nombre_de_quien,
            job_id=job.id,
        )
    elif (getattr(job, "origen", None) or {}).get("tipo") == "carpeta":
        avisos.append(
            "la corrida de esta carpeta ya no está en memoria: el PDF entregado y el índice del NIC no cambiaron"
        )
    # Y la decisión del agente de ese documento, en el informe: la confirmó o la cambió el operador.
    for decision in report.get("decisiones_del_agente") or []:
        if isinstance(decision, dict) and set(decision.get("paginas") or [decision.get("page")]) & hojas:
            decision.update({"valor": radicado, "auditor": CONFIRMADO})
    if getattr(job, "guardado", False):
        # El trabajo guardado: su informe corregido vuelve al disco.
        almacen = getattr(ctx, "re_por_revisar", None)
        if almacen is not None and (entrada := almacen.leer(job.id)):
            await asyncio.to_thread(almacen.guardar, job.id, {**entrada, "informe": report})
    else:
        if hasattr(ctx.registry, "publish"):
            ctx.registry.publish(job)
        await asyncio.to_thread(guardar_los_re_decididos, ctx, job)
    return {"re": radicado, "archivo": nuevo, "avisos": avisos}


def por_auditar(decision: object) -> bool:
    """Si una decisión del agente se enseña para auditar: confianza baja o revertida, y no tocada por el operador."""
    if not isinstance(decision, dict) or decision.get("auditor") == CONFIRMADO:
        return False
    return not decision.get("valor") or decision.get("confianza") == "baja"


@router.get("/api/re-decididos")
async def re_decididos(ctx: Ctx) -> list[dict[str, object]]:
    """Los RE que el agente decidió con confianza baja -- o que su auditor revirtió -- en los trabajos que ya no están en memoria (2026-11-23).

    Los de los trabajos en memoria los enseña la pantalla desde el trabajo en
    vivo. Cada uno con su hoja, lo que se leyó y el archivo donde quedó, para
    auditarlo y cambiarlo con el mismo «Confirmar».
    """
    almacen = getattr(ctx, "re_por_revisar", None)
    if almacen is None:
        return []
    salida: list[dict[str, object]] = []
    for entrada in await asyncio.to_thread(almacen.todas):
        job_id = str(entrada.get("job_id") or "")
        vivo = ctx.registry.get(job_id)
        if not job_id or (vivo is not None and vivo.report):
            continue
        informe = entrada.get("informe") or {}
        for decision in informe.get("decisiones_del_agente") or []:
            if not por_auditar(decision):
                continue
            pagina = int(decision.get("page") or 0)
            archivo = next(
                (
                    str(item.get("file_name") or "")
                    for item in _items(informe)
                    if pagina in (item.get("page_numbers") or [])
                ),
                None,
            )
            regla, confianza = decision.get("regla") or "", decision.get("confianza") or ""
            salida.append(
                {
                    "job_id": job_id,
                    "documento": entrada.get("documento") or job_id,
                    "pagina": pagina,
                    "motivo": f"{regla} ({confianza}): {decision.get('por_que') or ''}",
                    "candidatos": [
                        {"valor": v, "motivo": "leído", "pagina": pagina} for v in decision.get("opciones") or []
                    ],
                    "valor": decision.get("valor"),
                    "archivo": archivo,
                }
            )
    return salida
