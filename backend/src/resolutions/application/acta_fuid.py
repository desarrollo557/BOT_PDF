"""Filas FUID para actas de grado.

Una fila por acta, con:
- asunto: "ACTA DE GRADO N° {numero}"
- fecha: fecha de la ceremonia (ISO)
- consecutivo_inicial / consecutivo_final: folio manuscrito
- notas: resumen generado por Mistral
- folios: 1 (cada acta = 1 página típicamente)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .fuid import NO_APLICA, FuidRow, Ubicacion


@dataclass(slots=True)
class ActaParaFuid:
    """Datos de una acta listos para convertirse en fila FUID."""
    numero: str
    fecha: str  # ISO YYYY-MM-DD
    folio: str
    resumen: str
    paginas: list[int]


def filas_de_actas(
    actas: Sequence[ActaParaFuid],
    nombre_del_archivo: str,
    ubicacion: Ubicacion | None = None,
    desde: int = 1,
) -> list[FuidRow]:
    """Convierte las actas procesadas en filas del FUID (FO-GD-008)."""
    filas: list[FuidRow] = []
    for i, acta in enumerate(actas, start=desde):
        folio = acta.folio if acta.folio and acta.folio != "SIN FOLIO" else NO_APLICA
        filas.append(FuidRow(
            orden=i,
            asunto=f"ACTA DE GRADO N° {acta.numero}",
            codigo_trd=NO_APLICA,
            consecutivo_inicial=folio,
            consecutivo_final=folio,
            fecha_inicial=acta.fecha if acta.fecha and acta.fecha != "SIN FECHA" else NO_APLICA,
            fecha_final=acta.fecha if acta.fecha and acta.fecha != "SIN FECHA" else NO_APLICA,
            caja=ubicacion.caja if ubicacion else NO_APLICA,
            carpeta=ubicacion.carpeta_de(nombre_del_archivo) if ubicacion else NO_APLICA,
            tomo=NO_APLICA,
            otro=ubicacion.otro if ubicacion else NO_APLICA,
            folios=len(acta.paginas) if acta.paginas else 1,
            folios_siar=len(acta.paginas) if acta.paginas else 1,
            soporte=NO_APLICA,
            frecuencia=NO_APLICA,
            notas=acta.resumen or "",
            pagina_inicial=acta.paginas[0] if acta.paginas else None,
        ))
    return filas