"""El FUID de las actas de consejo: una fila por acta, en el FO-GD-008.

Hasta el 2026-10-29 las actas de consejo iban en un Excel propio, con su
resumen. Ese día el operador pidió el mismo FUID para todas las habilidades
(«estandarízame todas esas habilidades»), y para las actas de consejo, una fila
por acta:

* **Nombre o asunto**: «ACTA DE CONSEJO DE FACULTAD - ORDINARIA», con el
  consejo que diga el papel: académico, superior o, si no dice, de facultad.
  Desde el 2026-11-09, seguido del resumen del acta, que nombra a las personas
  que menciona: «… - ORDINARIA - El Consejo de Facultad… sesionó…». Sin el
  número del acta desde el 2026-11-11: va sólo en el consecutivo.
* **Consecutivo inicial y final**: el número del acta, «022».
* **Fechas extremas**: la de la sesión en las dos, «17/12/2012».
* **Caja** y **carpeta**: «00C003284» y «UPD3859771», de dónde está el PDF.
* **No. de folios** y **No. de folios SIAR**: cuántos folios tiene el acta.
* **Notas**: el folio inicial y el final escritos a mano, si se leyeron, y lo
  que no se pudo leer.

Del 2026-10-31 al 2026-11-09 llevó además, a la derecha del formato, **ACTA #**,
**OBJETIVO / RESUMEN** y las **páginas del PDF**. El operador las quitó al
poner el resumen en el asunto: «un FUID limpio, manejando el original».
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

from ..application.fuid import FuidRow
from ..domain.acta_consejo import sin_cortes
from .fuid_actas_de_grado import NO_LEIDO, ubicacion

#: El consejo que dice el papel, por la palabra que lo nombra en la fila.
_CONSEJOS = (
    ("CONSEJO ACADEMICO", "ACTA DE CONSEJO ACADEMICO"),
    ("CONSEJO SUPERIOR", "ACTA DE CONSEJO SUPERIOR"),
    ("COMITE", "ACTA DE COMITE"),
)
_DE_FACULTAD = "ACTA DE CONSEJO DE FACULTAD"


def _plano(texto: object) -> str:
    sin_tildes = unicodedata.normalize("NFD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.upper().split())


def _fecha(fecha: object) -> str:
    """«17-12-2012» de la fila a «17/12/2012», como las demás fechas del FUID."""
    texto = str(fecha or "")
    if re.fullmatch(r"\d{2}-\d{2}-\d{4}", texto):
        return texto.replace("-", "/")
    return NO_LEIDO


def _entero(valor: object) -> int | None:
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def asunto_del_acta(fila: Mapping[str, object]) -> str:
    """«ACTA DE CONSEJO DE FACULTAD - ORDINARIA», sin el número del acta.

    El número va en el consecutivo inicial y final, que es su columna; en el
    asunto lo quitó el operador el 2026-11-11: «que quede sin el número de
    acta», «ACTA DE CONSEJO DE FACULTAD - EXTRAORDINARIA - El Consejo…».
    """
    acta = _plano(fila.get("acta"))
    serie = next((nombre for palabra, nombre in _CONSEJOS if palabra in acta), _DE_FACULTAD)
    sesion = "EXTRAORDINARIA" if "EXTRAORDINARI" in acta else "ORDINARIA" if "ORDINARI" in acta else ""
    return serie + (f" - {sesion}" if sesion else "")


def asunto_con_resumen(fila: Mapping[str, object], resumen: str | None = None) -> str:
    """«ACTA DE CONSEJO DE FACULTAD - ORDINARIA - El Consejo de Facultad… sesionó…».

    El operador, 2026-11-09: el asunto es el acta, su sesión y su resumen, con
    el nombre de las personas que menciona. Sin resumen -- «Solo OCR» -- el
    asunto queda sin él, no con un «- N/A» al final.
    """
    asunto = asunto_del_acta(fila)
    resumen = _resumen(fila.get("resumen")) if resumen is None else resumen
    return f"{asunto} - {resumen}" if resumen != NO_LEIDO else asunto


def fila_del_fuid(fila: Mapping[str, object]) -> FuidRow:
    """La fila del FUID de un acta. El número de orden lo pone quien junta las filas."""
    caja, upd = ubicacion(str(fila.get("carpeta") or ""), str(fila.get("archivo") or ""))
    numero = str(fila.get("numero") or "").strip() or NO_LEIDO
    fecha = _fecha(fila.get("fecha"))
    folios = _entero(fila.get("folios"))
    resumen = _resumen(fila.get("resumen"))
    notas = []
    inicial, final = _entero(fila.get("folio_inicial")), _entero(fila.get("folio_final"))
    if inicial is not None and final is not None:
        notas.append(f"folios {inicial} a {final}" if final != inicial else f"folio {inicial}")
    if fila.get("observaciones"):
        notas.append(str(fila["observaciones"]))
    return FuidRow(
        orden=0,
        asunto=asunto_con_resumen(fila, resumen),
        codigo_trd="",
        consecutivo_inicial=numero,
        consecutivo_final=numero,
        fecha_inicial=fecha,
        fecha_final=fecha,
        caja=caja,
        carpeta=upd,
        tomo="",
        otro="",
        folios=folios if folios else NO_LEIDO,  # type: ignore[arg-type]
        folios_siar=folios if folios else NO_LEIDO,  # type: ignore[arg-type]
        soporte="",
        frecuencia="",
        notas="; ".join(notas),
        pagina_inicial=fila.get("pagina_inicial"),  # type: ignore[arg-type]
    )


def _resumen(valor: object) -> str:
    """El resumen del acta, sin «…» al final (``sin_cortes``); N/A si no lo hay: con «Solo OCR» no se escribe.

    También los resúmenes ya guardados en una entrega de antes del 2026-11-09.
    """
    texto = sin_cortes(" ".join(str(valor or "").split()))
    return texto or NO_LEIDO
