"""El FUID de las historias académicas: una fila por estudiante, en el FO-GD-008.

El operador lo pidió «como las actas de grado» (2026-10-29), sobre la carpeta
«14. ENFERMERIA 3277-3283 P», y con la fila guía de su plantilla: «nombre -
título», «cédula», «código».

* **Nombre o asunto**: «AGUAS GARRIDO CLARENA LUCIA - HISTORIA ACADEMICA»: primero el
  nombre y luego el tipo, en todos los inventarios de la Universidad (2026-10-30).
* **Consecutivo inicial**: la cédula del estudiante, sin puntos; sin cédula, la
  tarjeta de identidad que trae la ficha, «T.I. 650409-01935».
* **Consecutivo final**: su código de estudiante; N/A si la ficha no lo trae
  o no se leyó.
* **Fechas extremas**: el primer y el último año de sus notas, «01/01/1993» y
  «31/12/1996».
* **Caja** y **carpeta**: «00C003282» y «UPD3859753», de dónde está el PDF.
* **No. de folios** y **No. de folios SIAR**: las hojas de su expediente.
* Las demás columnas en blanco, como en el modelo de actas de grado. **Notas**
  lleva lo que no se pudo leer.

Lo que va antes de la primera ficha de un PDF no es de ningún estudiante y no
lleva fila, como las hojas de la ceremonia en las actas de grado.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from ..application.fuid import FuidRow
from ..domain.historia_academica import HISTORIA_ACADEMICA
from .fuid_actas_de_grado import NO_LEIDO, ubicacion


def _fechas(fila: Mapping[str, object]) -> tuple[str, str]:
    inicial, final = fila.get("anio_inicial"), fila.get("anio_final")
    return (
        f"01/01/{inicial}" if isinstance(inicial, int) else NO_LEIDO,
        f"31/12/{final}" if isinstance(final, int) else NO_LEIDO,
    )


def _identificacion(fila: Mapping[str, object]) -> str:
    """La cédula; si la ficha sólo trae la tarjeta de identidad, ésa, dicha como tal."""
    if cedula := str(fila.get("cedula") or ""):
        return cedula
    tarjeta = str(fila.get("tarjeta") or "")
    return f"T.I. {tarjeta}" if tarjeta else NO_LEIDO


def fila_del_fuid(fila: Mapping[str, object]) -> FuidRow | None:
    """La fila del FUID de un estudiante, o ``None`` si las páginas no son de nadie.

    El número de orden lo pone quien junta las filas (``fuid_de_la_entrega``).
    """
    if fila.get("tipo") != HISTORIA_ACADEMICA:
        return None
    caja, upd = ubicacion(str(fila.get("carpeta") or ""), str(fila.get("archivo") or ""))
    nombre = str(fila.get("nombre") or "") or NO_LEIDO
    inicial, final = _fechas(fila)
    folios = fila.get("folios")
    folios = folios if isinstance(folios, int) else NO_LEIDO
    return FuidRow(
        orden=0,
        asunto=f"{nombre} - {HISTORIA_ACADEMICA}",
        codigo_trd="",
        consecutivo_inicial=_identificacion(fila),
        consecutivo_final=str(fila.get("codigo") or "") or NO_LEIDO,
        fecha_inicial=inicial,
        fecha_final=final,
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


def filas_del_fuid(filas: Sequence[Mapping[str, object]]) -> list[FuidRow]:
    """Las filas del FUID, una por estudiante y en el orden en que llegan."""
    resultado: list[FuidRow] = []
    for fila in filas:
        convertida = fila_del_fuid(fila)
        if convertida is not None:
            resultado.append(replace(convertida, orden=len(resultado) + 1))
    return resultado
