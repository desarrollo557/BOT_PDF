"""Las métricas de la extracción de un destino, desde sus constancias (2026-11-18).

Las escribe la corrida al cerrar la carpeta (``FolderRunner._cerrar_generales``)
y las puede rehacer, con la comparación con una entrega anterior, el script
``scripts/metricas_de_la_extraccion.py``. Sólo lee las constancias: no abre
ningún PDF ni paga nada.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import replace
from pathlib import Path

from ..adapters.metricas_de_la_extraccion import (
    escribir_la_auditoria_de_la_corrida,
    escribir_metricas,
)
from ..application.metricas_de_la_extraccion import (
    LaCorrida,
    PdfEntregado,
    comparar,
    medir,
)
from . import constancia as constancias

logger = logging.getLogger(__name__)

#: Lo que se aparta al rehacer una entrega no cuenta.
_APARTADOS = "_reemplazados"


def entregados_en(destino: Path) -> Iterator[PdfEntregado]:
    """Lo que dicen las constancias de un destino, una por PDF de origen."""
    prefijo = f"{Path(constancias.NOMBRE).stem}-"
    for ruta in sorted(destino.rglob(f"{prefijo}*.json")):
        if _APARTADOS in ruta.parts:
            continue
        constancia = constancias.leer(ruta)
        if constancia is None:
            continue
        nic = ruta.parent.relative_to(destino).as_posix()
        upd = ruta.stem[len(prefijo) :] if ruta.stem.startswith(prefijo) else ruta.stem
        yield PdfEntregado(
            documento=f"{nic}/{upd}",
            estado=str(constancia.estado),
            archivos=[str(a.get("ruta") or "") for a in constancia.archivos if isinstance(a, dict)],
            evidencia=constancia.evidencia or {},
            revision=list(constancia.revision or []),
            proceso=constancia.proceso or {},
            filas=[f for f in (constancia.indice or {}).get("filas") or [] if isinstance(f, dict)],
            documentos=[d for d in constancia.documentos or [] if isinstance(d, dict)],
            job_id=constancia.job_id or "",
            decisiones=[d for d in constancia.decisiones_del_agente or [] if isinstance(d, dict)],
        )


def escribir_las_metricas(destino: Path, anterior: Path | None = None) -> list[Path]:
    """Mide la entrega de ``destino`` y escribe sus dos libros en él; con ``anterior``, la comparación."""
    metricas = medir(entregados_en(destino))
    comparacion = comparar(entregados_en(anterior), entregados_en(destino)) if anterior is not None else None
    return escribir_metricas(destino, metricas, comparacion)


def _la_mas_comun(valores: Iterable[object]) -> str:
    cuenta = Counter(str(v) for v in valores if v)
    return ", ".join(v for v, _ in cuenta.most_common()) if cuenta else ""


def escribir_la_auditoria(destino: Path, corrida: LaCorrida, trabajos: Iterable[str]) -> Path:
    """La auditoría de una corrida (2026-11-20): sólo los PDF que entregaron sus ``trabajos``."""
    suyos = set(trabajos)
    entregados = [pdf for pdf in entregados_en(destino) if pdf.job_id in suyos]
    procesos = [pdf.proceso or {} for pdf in entregados]
    corrida = replace(
        corrida,
        habilidad=corrida.habilidad or _la_mas_comun(p.get("habilidad") for p in procesos),
        lectura=corrida.lectura or _la_mas_comun(p.get("lectura") for p in procesos),
        entrega=corrida.entrega or _la_mas_comun(p.get("entrega") for p in procesos),
        operador=corrida.operador or _la_mas_comun(p.get("operador") for p in procesos),
    )
    return escribir_la_auditoria_de_la_corrida(destino, corrida, medir(entregados))
