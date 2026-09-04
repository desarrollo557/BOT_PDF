"""La fila del Formato Único de Inventario Documental, sin Excel de por medio.

El FUID es un formato, no un archivo: las mismas dieciséis columnas valen para
la planilla que se firma, para una consulta a la base y para lo que se muestre
en pantalla. Por eso la fila vive aquí, en la aplicación, y el adaptador que
sabe de openpyxl la recibe ya decidida.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Lo que el instructivo del formato manda escribir donde no hay dato. Nunca se
#: deja en blanco -- una celda vacía no dice "no aplica", dice "se olvidó" -- y
#: nunca se rellena con algo verosímil.
NO_APLICA = "N/A"


@dataclass(frozen=True, slots=True)
class FuidRow:
    """Una fila del inventario, en el orden de las columnas del formato.

    Los nombres son los del FUID y no los del documento de origen, para que
    quien lea esto con la plantilla delante siga la correspondencia sin traducir.
    """

    orden: int
    asunto: str
    codigo_trd: str = NO_APLICA
    consecutivo_inicial: str = NO_APLICA
    consecutivo_final: str = NO_APLICA
    fecha_inicial: str = NO_APLICA
    fecha_final: str = NO_APLICA
    caja: str = NO_APLICA
    carpeta: str = NO_APLICA
    tomo: str = NO_APLICA
    otro: str = NO_APLICA
    folios: int = 1
    folios_siar: int = 1
    soporte: str = NO_APLICA
    frecuencia: str = NO_APLICA
    notas: str = ""

    def as_cells(self) -> list[object]:
        """Los valores en el orden de las columnas A a P de la plantilla."""
        return [
            self.orden,
            self.codigo_trd,
            self.asunto,
            self.consecutivo_inicial,
            self.consecutivo_final,
            self.fecha_inicial,
            self.fecha_final,
            self.caja,
            self.carpeta,
            self.tomo,
            self.otro,
            self.folios,
            self.folios_siar,
            self.soporte,
            self.frecuencia,
            self.notas,
        ]


@dataclass(frozen=True, slots=True)
class Cabecera:
    """Lo que cambia de una entrega a otra en la parte alta del formato."""

    oficina_productora: str | None = None
    objeto: str | None = None


#: El número de la unidad documental que la Universidad estampa en el empaste o
#: en la carpeta. Va en el nombre del archivo digitalizado -- "4. 3858082
#: REGISTRO DE DIPLOMAS..." -- porque dentro del PDF no consta en ninguna parte.
#: Se escribe pelado, sin anteponerle "UPD": la columna ya se llama así.
_UPD_EN_EL_NOMBRE = re.compile(r"\b(\d{7})\b")


def upd_del_archivo(nombre: str) -> str:
    """El UPD que anuncia el nombre del archivo, o N/A si no lo anuncia."""
    encontrado = _UPD_EN_EL_NOMBRE.search(nombre)
    return encontrado.group(1) if encontrado else NO_APLICA


@dataclass(frozen=True, slots=True)
class Ubicacion:
    """Dónde está físicamente lo que se inventaría.

    Es lo que el PDF no puede saber. La caja lleva un sticker que sólo existe en
    el depósito, así que su valor por defecto es N/A y no un número plausible: el
    operador lo indica, o queda declarado como ausente.
    """

    caja: str = NO_APLICA
    otro: str = NO_APLICA
    codigo_trd: str = NO_APLICA
    #: Cuando se indica, manda sobre el número que traiga el nombre del archivo.
    carpeta: str | None = None

    def carpeta_de(self, nombre_del_archivo: str) -> str:
        return self.carpeta or upd_del_archivo(nombre_del_archivo)
