"""El FUID de las nóminas: una fila por documento del libro, en el FO-GD-008 de la Universidad.

Como lo marcó el operador en «ESTRUCTURA LIBROS UNICARTAGENA.pdf» (2026-11-06):

* **Nombre o asunto**: «NOMINAS - NOMBRE» (la tarjeta), «LIBRO DE ANOTACIONES -
  NOMBRE» (la hoja manuscrita, con el nombre de su libro), «CERTIFICADO DE
  TIEMPO DE SERVICIO - NOMBRE», «NOMINA» (la relación de empleados o un mes de
  comprobantes), «LISTADO DE NOMINA PERSONAL» (lo que abre el hablador) o
  «INDICE».
* **Consecutivo inicial y final**: el número de documento de la persona, su
  cédula, sin puntos, en los dos («No. Documento Desde - Hasta»); N/A si la
  hoja no la trae o no se leyó, y en los paquetes.
* **Fechas extremas**: el año de acumulación o el de la hoja («01/01/1979» a
  «31/12/1979»), la fecha del listado en los dos extremos («03/07/1984»), la
  primera y la última fecha de pago de los comprobantes, la del certificado.
* **Caja** y **carpeta**: de dónde está el PDF; **folios**: sus hojas.
* **Notas**: lo que no se pudo leer, con sus páginas.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from ..application.fuid import FuidRow
from ..domain.nomina import NOMINA
from .fuid_actas_de_grado import NO_LEIDO, ubicacion


def fila_del_fuid(fila: Mapping[str, object]) -> FuidRow | None:
    """La fila del FUID de un documento del libro; ``None`` si la fila no es de nóminas."""
    if fila.get("tipo") != NOMINA:
        return None
    caja, upd = ubicacion(str(fila.get("carpeta") or ""), str(fila.get("archivo") or ""))
    cedula = re.sub(r"\D", "", str(fila.get("cedula") or "")) or NO_LEIDO
    folios = fila.get("folios")
    folios = folios if isinstance(folios, int) else NO_LEIDO
    return FuidRow(
        orden=0,
        asunto=str(fila.get("asunto") or "") or NO_LEIDO,
        codigo_trd="",
        consecutivo_inicial=cedula,
        consecutivo_final=cedula,
        fecha_inicial=str(fila.get("fecha_inicial") or "") or NO_LEIDO,
        fecha_final=str(fila.get("fecha_final") or "") or NO_LEIDO,
        caja=caja,
        carpeta=upd,
        tomo="",
        otro="",
        folios=folios,  # type: ignore[arg-type]
        folios_siar=folios,  # type: ignore[arg-type]
        soporte="",
        frecuencia="",
        notas=str(fila.get("observaciones") or ""),
        pagina_inicial=fila.get("pagina_inicial"),  # type: ignore[arg-type]
    )
