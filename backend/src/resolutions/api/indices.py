"""Los Índices Electrónicos de varias cajas, juntos en un libro.

Toda caja de correspondencia deja su «00.INDICE ELECTRONICO.xlsx» junto a sus
PDF. Cuando se piden varias a la vez -- un lote, o el archivo filtrado -- no se
arma otra planilla: se leen los índices que se entregaron y cada uno va a su
propia hoja del libro, con la plantilla del cliente. Lo que se descarga y lo que
quedó en cada caja no pueden discrepar.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from ..adapters.indice_electronico import (
    NOMBRE_DEL_INDICE,
    escribir_indices_por_hoja,
    leer_indice,
)

logger = logging.getLogger(__name__)

#: Dónde queda el índice de un lote, dentro de la carpeta de salidas. El
#: prefijo lo separa de las carpetas de los trabajos, que son identificadores.
PREFIJO_DEL_LOTE = "lote-"


def indice_del_trabajo(output_dir: Path, job_id: str) -> Path | None:
    """El índice que dejó un trabajo, o ``None`` si no es una caja de correspondencia."""
    carpeta = output_dir / job_id
    if not carpeta.is_dir():
        return None
    return next(iter(sorted(carpeta.rglob(NOMBRE_DEL_INDICE))), None)


def carpeta_del_lote(output_dir: Path, batch_id: str) -> Path:
    return output_dir / f"{PREFIJO_DEL_LOTE}{batch_id}"


def libro_de_indices(
    output_dir: Path,
    job_ids: Iterable[str],
    destino: Path,
    nombre_del_archivo: str = NOMBRE_DEL_INDICE,
) -> Path | None:
    """Un libro con una hoja por caja, o ``None`` si ninguno de los trabajos dejó índice.

    La hoja se llama como la caja -- la carpeta en que se entregaron sus PDF,
    «UPD2320047» --, y si la misma caja se procesó dos veces la segunda lleva
    «(2)».
    """
    cajas = []
    for job_id in dict.fromkeys(job_ids):
        ruta = indice_del_trabajo(output_dir, job_id)
        if ruta is None:
            continue
        try:
            indice = leer_indice(ruta)
        except Exception:  # noqa: BLE001 - una caja ilegible no tumba el libro
            logger.warning("no se pudo leer el índice %s", ruta, exc_info=True)
            continue
        nombre = ruta.parent.name if ruta.parent.name != job_id else (indice.nombre_del_expediente or job_id)
        cajas.append((nombre, indice))
    if not cajas:
        return None
    cajas.sort(key=lambda caja: caja[0])
    return escribir_indices_por_hoja(destino, cajas, nombre_del_archivo=nombre_del_archivo)


# -- el inventario general de procesos -----------------------------------------

_LECTURAS = {"local": "Solo OCR", "mistral": "OCR + IA", "mistral-nombres": "OCR + IA (ahorro)"}
_ENTREGAS = {"tramite": "Por trámite", "documento": "Por documento", "mes": "Por mes"}
_ESTADOS = {"done": "Listo", "failed": "Falló", "cancelled": "Cancelado"}


def habilidad_del_proceso(job) -> str:
    """Qué habilidad atendió el PDF, por lo que de verdad hizo y no por lo que se pidió.

    Con «No estoy seguro» el despachador elige: el informe dice adónde fue.
    """
    informe = job.report or {}
    tipo = str((informe.get("stats") or {}).get("document_type") or "")
    if informe.get("indice_electronico") or informe.get("agrupar") or job.task == "segment":
        return "Caja de correspondencia"
    if informe.get("inventario_actas"):
        return "Actas de grado" if job.tipo == "acta" else "Actas de consejo"
    if tipo == "diploma" or job.tipo == "diploma":
        return "Libro de diplomas"
    if job.task == "inventory":
        return "Archivos ya separados"
    if tipo == "resolucion" or job.task in ("split", "both"):
        return "Legajo de resoluciones"
    return tipo or job.task or "—"


def _duracion(inicio: str | None, fin: str | None) -> str:
    from datetime import datetime

    try:
        segundos = int((datetime.fromisoformat(fin) - datetime.fromisoformat(inicio)).total_seconds())
    except (TypeError, ValueError):
        return "—"
    return f"{segundos // 60} min {segundos % 60:02d} s" if segundos >= 60 else f"{segundos} s"


def fila_de_proceso(job, destino: str | Path | None = None):
    """La fila de un trabajo en el inventario general de procesos."""
    from ..adapters.excel_inventory import FilaDeProceso

    informe = job.report or {}
    consumo = informe.get("consumo") or {}
    estado = _ESTADOS.get(str(job.state), "En curso")
    entrega = (
        _ENTREGAS.get(str(informe.get("agrupar") or job.agrupar), "—")
        if habilidad_del_proceso(job) == "Caja de correspondencia"
        else "—"
    )
    avisos = [] if estado == "Listo" else [job.error or estado]
    return FilaDeProceso(
        pdf=Path(job.filename).name,
        habilidad=habilidad_del_proceso(job),
        lectura=_LECTURAS.get(job.lectura, job.lectura or "—"),
        entrega=entrega,
        paginas=int(informe.get("page_count") or job.progress.page_count or 0),
        documentos=len(informe.get("groups") or []) or len(informe.get("inventario_actas") or []),
        en_revision=len(informe.get("review_queue") or []),
        estado=estado,
        inicio=job.started_at,
        duracion=_duracion(job.started_at, job.finished_at),
        paginas_pagadas=int(consumo.get("paginas_facturadas") or 0),
        operador=job.operator or "",
        destino=str(destino or job.destination or ""),
        observaciones="; ".join(str(a) for a in avisos if a),
    )


def inventario_de_procesos(
    jobs: Iterable,
    destino: Path,
    *,
    origen: str,
    clase_de_origen: str,
    operador: str | None = None,
    destino_de=None,
) -> Path | None:
    """El inventario general del bot de un lote o una carpeta, o ``None`` si no hay procesos.

    ``destino_de`` dice dónde quedó lo de cada trabajo; sin él, el de su trabajo.
    """
    from ..adapters.excel_inventory import ExcelInventarioDeProcesos

    terminados = [j for j in jobs if str(j.state) in _ESTADOS]
    if not terminados:
        return None
    terminados.sort(key=lambda j: Path(j.filename).name)
    filas = [fila_de_proceso(j, destino_de(j) if destino_de else None) for j in terminados]
    return ExcelInventarioDeProcesos().write(
        filas, destino, origen=origen, clase_de_origen=clase_de_origen, operador=operador
    )
