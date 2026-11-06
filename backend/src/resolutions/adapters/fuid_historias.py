"""El FUID de las historias académicas: una fila por estudiante, en el FO-GD-008.

El operador lo pidió «como las actas de grado» (2026-10-29), sobre la carpeta
«14. ENFERMERIA 3277-3283 P», y con la fila guía de su plantilla: «nombre -
título», «cédula», «código».

* **Nombre o asunto**: sólo el nombre, «AGUAS GARRIDO CLARENA LUCIA». El operador,
  2026-11-06, antes de procesar Enfermería otra vez: «en el FUID esté el nombre
  solamente, luego la cédula o tarjeta o libreta militar, y el código». Hasta
  entonces llevaba « - HISTORIA ACADEMICA» detrás (2026-10-30).
* **Consecutivo inicial**: la cédula del estudiante, sin puntos; sin cédula, la
  tarjeta de identidad que trae la ficha, sólo sus cifras: «65040901935»; sin
  ninguna de las dos, la libreta militar.
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

Las hojas sueltas de Medicina -- una matrícula, un certificado o un recibo por
estudiante (cajas 00C003267 y 00C003268) -- van por aquí también, con el tipo
de hoja en el asunto (``clase``) y, si la hoja trae su fecha entera, esa fecha
en los dos extremos (``fecha_exacta``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace

from ..application.fuid import FuidRow
from ..domain.historia_academica import HISTORIA_ACADEMICA
from .fuid_actas_de_grado import NO_LEIDO, ubicacion


def _fechas(fila: Mapping[str, object]) -> tuple[str, str]:
    if fecha := fila.get("fecha_exacta"):
        # Una hoja suelta de Medicina con su fecha entera: «26/03/1992» en los dos extremos.
        return str(fecha), str(fecha)
    inicial, final = fila.get("anio_inicial"), fila.get("anio_final")
    return (
        f"01/01/{inicial}" if isinstance(inicial, int) else NO_LEIDO,
        f"31/12/{final}" if isinstance(final, int) else NO_LEIDO,
    )


def _identificacion(fila: Mapping[str, object]) -> str:
    """La cédula; si no, la tarjeta de identidad; si no, la libreta militar: sólo sus cifras.

    Sin «T.I.», guiones ni puntos: lo dictó el operador el 2026-10-30; la
    libreta, el 2026-11-06. Es la misma que va al final del nombre del PDF.
    """
    for clave in ("cedula", "tarjeta", "libreta"):
        if cifras := re.sub(r"\D", "", str(fila.get(clave) or "")):
            return cifras
    return NO_LEIDO


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
        # Sólo el nombre (2026-11-06). Las hojas sueltas de Medicina dicen
        # además qué hoja son: «… - CERTIFICADO DE MATRICULA», «… - RECIBO DE
        # CAJA» (el operador, 2026-11-03): un estudiante tiene varias.
        asunto=f"{nombre} - {fila['clase']}" if fila.get("clase") else nombre,
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
