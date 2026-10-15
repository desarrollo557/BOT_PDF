"""El FUID de las actas de grado: una fila por graduado, en la plantilla oficial.

Es el formato que el operador entregó como modelo («16. SECRETARIA
INVENTARIO_ACTAS DE GRADO.xlsx»), que es el FO-GD-008 de la Universidad
rellenado así:

* **Nombre o asunto**: «ACTA DE GRADO No. 01/05 - MARTHA LUCIA HERRERA
  VILLAMIZAR - ESPECIALISTA EN GESTION DE LA CALIDAD Y AUDITORIA EN SALUD».
* **Consecutivo inicial y final**: la cédula del graduado, sin puntos.
* **Fechas extremas**: la fecha del acta, la misma en las dos, «03/03/2005».
* **Caja** y **carpeta**: «00C003292» y «UPD3859821», de dónde está el PDF.
* **No. de folios** y **No. de folios SIAR**: el folio manuscrito de la
  esquina de su hoja, «140». La hoja que la sigue sin folio -- su vuelto,
  «140/V» -- va en el mismo PDF. Sin la IA el folio no se lee y queda N/A.
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
from dataclasses import asdict, is_dataclass
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

_CAJA = re.compile(r"\b\d{2}C\d{6}\b")
_UPD = re.compile(r"\bUPD\d{7}\b")


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
    return (caja.group(0) if caja else "", upd.group(0) if upd else "")


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


def _folio(inicial: object, final: object) -> int | str:
    """El folio de la fila: «140», o «140-141» si su acta ocupa dos hojas foliadas."""
    if not isinstance(inicial, int) or isinstance(inicial, bool):
        return NO_LEIDO
    if isinstance(final, int) and not isinstance(final, bool) and final != inicial:
        return f"{inicial}-{final}"
    return inicial


def filas_del_fuid(filas: Sequence[object]) -> list[FuidRow]:
    """Las filas del FUID, una por graduado y en el orden en que llegan."""
    resultado: list[FuidRow] = []
    for fila in map(_como_dict, filas):
        if fila.get("tipo") == CEREMONIA:
            continue
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
        # El folio manuscrito de la esquina de su hoja: «140». Sin la IA no
        # se lee, y queda N/A.
        folios = _folio(fila.get("folio_inicial"), fila.get("folio_final"))
        resultado.append(
            FuidRow(
                orden=len(resultado) + 1,
                asunto=f"{acta} - {nombre} - {titulo}",
                codigo_trd="",
                consecutivo_inicial=cedula,
                consecutivo_final=cedula,
                fecha_inicial=fecha,
                fecha_final=fecha,
                caja=caja,
                carpeta=upd,
                tomo="",
                otro="",
                folios=folios,  # type: ignore[arg-type] - el número o N/A
                # El operador pidió el mismo número en las dos columnas.
                folios_siar=folios,  # type: ignore[arg-type]
                soporte="",
                frecuencia="",
                notas=str(fila.get("observaciones") or ""),
                pagina_inicial=fila.get("pagina_inicial"),  # type: ignore[arg-type]
            )
        )
    return resultado


def escribir_fuid_de_actas_de_grado(
    filas: Sequence[object], destino: Path, *, plantilla: Path | None = None
) -> Path:
    """Escribe el FUID de las actas de grado en ``destino`` y devuelve su ruta."""
    return FuidInventory(plantilla or template_for(DocumentType.ACTA)).write(
        filas_del_fuid(filas), destino
    )
