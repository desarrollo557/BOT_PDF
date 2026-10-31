"""El FUID de las actas de grado: una fila por graduado, en la plantilla oficial.

Es el formato que el operador entregó como modelo («16. SECRETARIA
INVENTARIO_ACTAS DE GRADO.xlsx»), que es el FO-GD-008 de la Universidad
rellenado así:

* **Nombre o asunto**: «ACTA DE GRADO No. 01/05 - MARTHA LUCIA HERRERA
  VILLAMIZAR - ESPECIALISTA EN GESTION DE LA CALIDAD Y AUDITORIA EN SALUD».
* **Consecutivo inicial**: la cédula del graduado, sin puntos; **final**, N/A: el
  acta no trae otro número (lo pidió el operador el 2026-10-31: la cédula sólo
  en la columna D).
* **Fechas extremas**: la fecha del acta, la misma en las dos, «03/03/2005».
* **Caja** y **carpeta**: «00C003292» y «UPD3859821», de dónde está el PDF.
* **No. de folios**: cuántos folios -- hojas -- tiene el acta, «1»; **No. de
  folios SIAR**: cuántas páginas se escanearon. No el folio manuscrito de la
  esquina, que es el lugar del acta en el libro y no su tamaño (2026-10-31).
* Las demás columnas -- código TRD, tomo, otro, soporte, frecuencia -- en
  blanco, como en el modelo. **Notas** lleva lo que no se
  pudo leer, para quien revise.

Las hojas de la ceremonia que no son de ningún graduado -- listado,
resolución, portada -- no llevan fila: en el modelo no la tienen.

La cabecera -- entidad, unidad administrativa, oficina productora, objeto -- es
la de la plantilla y no se toca: el operador la dio por fija.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path

from ..application.fuid import FuidRow
from ..application.inventory_document import template_for
from ..domain.doctype import DocumentType
from .fuid_inventory import FuidInventory

#: Lo que se escribe donde no se pudo leer un dato que el FUID pide.
NO_LEIDO = "N/A"
#: Las filas que no van al FUID: las hojas de la ceremonia.
CEREMONIA = "CEREMONIA DE GRADO"
ACTA_DE_GRADO = "ACTA DE GRADO"

#: «00C003284», también con el rótulo pegado: Medicina nombra sus cajas
#: «CAJA00C003268», sin espacio, y con ``\b`` delante no se encontraba ninguna.
_CAJA = re.compile(r"(?<!\d)(\d{2}C\d{6})(?!\d)")
#: «UPD3859771», también con un espacio en medio: Medicina escribe «UPD
#: 3859597 HISTORIAS ACADEMICAS 1948-1960.pdf». Se devuelve siempre junta.
_UPD = re.compile(r"\bUPD\s?(\d{7})(?!\d)")


def ubicacion(carpeta: str, archivo: str) -> tuple[str, str]:
    """La caja y la carpeta (UPD) del PDF, de su ruta: «00C003290», «UPD3859819».

    La carpeta va en el nombre del PDF cuando la caja trae los PDF sueltos
    («UPD3859819-ACTA DE GRADO 2023.pdf») y en la subcarpeta cuando van dentro
    de una («00C003284\\UPD3859771\\…»). Lo que no aparece queda en blanco: no
    se inventa una caja.
    """
    texto = f"{carpeta} {archivo}"
    caja = _CAJA.search(texto)
    upd = _UPD.search(f"{archivo} {carpeta}")
    return (caja.group(1) if caja else "", f"UPD{upd.group(1)}" if upd else "")


def _como_dict(fila: object) -> Mapping[str, object]:
    if is_dataclass(fila) and not isinstance(fila, type):
        return asdict(fila)
    return fila  # type: ignore[return-value]


def _fecha_del_fuid(fecha: object) -> str:
    """«03-03-2005» del inventario a «03/03/2005», como la escribe el modelo."""
    texto = str(fecha or "")
    if re.fullmatch(r"\d{2}-\d{2}-\d{4}", texto):
        return texto.replace("-", "/")
    return NO_LEIDO


def _es_numero(valor: object) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _folio(inicial: object, final: object) -> int | str:
    """El folio de la fila: «140», o «140-141» si su acta ocupa dos hojas foliadas."""
    if not isinstance(inicial, int) or isinstance(inicial, bool):
        return NO_LEIDO
    if isinstance(final, int) and not isinstance(final, bool) and final != inicial:
        return f"{inicial}-{final}"
    return inicial


def fila_del_fuid(fila: Mapping[str, object]) -> FuidRow | None:
    """La fila del FUID de un graduado, o ``None`` para las hojas de su ceremonia.

    El número de orden lo pone quien junta las filas (``fuid_de_la_entrega``).
    """
    if fila.get("tipo") == CEREMONIA:
        return None
    caja, upd = ubicacion(str(fila.get("carpeta") or ""), str(fila.get("archivo") or ""))
    acta = str(fila.get("acta") or NO_LEIDO)
    if acta == NO_LEIDO:
        # Sin el número, el asunto conserva su forma: «ACTA DE GRADO No. N/A
        # - NOMBRE - TÍTULO», que es por donde se lee y se filtra.
        acta = f"{ACTA_DE_GRADO} No. {NO_LEIDO}"
    nombre = str(fila.get("nombre") or "") or NO_LEIDO
    titulo = str(fila.get("titulo") or "") or NO_LEIDO
    cedula = str(fila.get("cedula") or "") or NO_LEIDO
    fecha = _fecha_del_fuid(fila.get("fecha"))
    # Cuántos folios tiene el acta y cuántas páginas se escanearon: no el
    # folio manuscrito de la esquina, que es su lugar en el libro.
    # Un acta con su vuelto es un folio y dos páginas.
    desde, hasta = fila.get("pagina_inicial"), fila.get("pagina_final")
    paginas = hasta - desde + 1 if isinstance(desde, int) and isinstance(hasta, int) and hasta >= desde else 1
    inicial, final = fila.get("folio_inicial"), fila.get("folio_final")
    if _es_numero(inicial) and _es_numero(final) and final >= inicial:
        folios = final - inicial + 1
    else:
        folios = max(1, (paginas + 1) // 2)
    return FuidRow(
        orden=0,
        # Primero el nombre y luego el tipo, en todos los inventarios de la
        # Universidad (lo pidió el operador el 2026-10-30).
        asunto=f"{nombre} - {acta} - {titulo}",
        codigo_trd="",
        # La cédula sólo en la columna D: el acta no trae otro número.
        consecutivo_inicial=cedula,
        consecutivo_final=NO_LEIDO,
        fecha_inicial=fecha,
        fecha_final=fecha,
        caja=caja,
        carpeta=upd,
        tomo="",
        otro="",
        folios=folios,
        folios_siar=paginas,
        soporte="",
        frecuencia="",
        notas=str(fila.get("observaciones") or ""),
        pagina_inicial=fila.get("pagina_inicial"),  # type: ignore[arg-type]
    )


def filas_del_fuid(filas: Sequence[object]) -> list[FuidRow]:
    """Las filas del FUID, una por graduado y en el orden en que llegan."""
    resultado: list[FuidRow] = []
    for fila in map(_como_dict, filas):
        convertida = fila_del_fuid(fila)
        if convertida is not None:
            resultado.append(replace(convertida, orden=len(resultado) + 1))
    return resultado


def escribir_fuid_de_actas_de_grado(
    filas: Sequence[object], destino: Path, *, plantilla: Path | None = None
) -> Path:
    """Escribe el FUID de las actas de grado en ``destino`` y devuelve su ruta."""
    return FuidInventory(plantilla or template_for(DocumentType.ACTA)).write(
        filas_del_fuid(filas), destino
    )
