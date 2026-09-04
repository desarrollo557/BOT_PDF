"""Convierte las resoluciones agrupadas en filas del FUID.

El equivalente de `diploma_fuid` para el otro tipo de documento, y con las
mismas reglas del instructivo del formato. Lo que cambia es qué se sabe: de una
resolución el sistema lee su número y su asunto, pero no su fecha, así que las
fechas extremas salen como N/A. Escribir ahí el año que aparece dentro del
número sería una fecha que nadie puede rastrear hasta el papel, y eso es
exactamente lo que el instructivo prohíbe.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.grouping import PageGroup
from .fuid import NO_APLICA, FuidRow, Ubicacion


def asunto(group: PageGroup) -> str:
    """El nombre de la unidad documental, que es su asunto cuando se leyó."""
    return group.title or f"Resolución {group.code.value}"


def filas_de_resoluciones(
    groups: Sequence[PageGroup],
    *,
    nombre_del_archivo: str,
    ubicacion: Ubicacion | None = None,
    desde: int = 1,
) -> list[FuidRow]:
    """Una fila por resolución, en el orden en que aparecen en el documento."""
    donde = ubicacion or Ubicacion()
    upd = donde.carpeta_de(nombre_del_archivo)

    return [
        FuidRow(
            orden=desde + desplazamiento,
            codigo_trd=donde.codigo_trd,
            asunto=asunto(group),
            # El número de la resolución es el número de identificación de la
            # unidad documental, que es lo que el instructivo pide en esta
            # columna.
            consecutivo_inicial=group.code.value,
            consecutivo_final=NO_APLICA,
            fecha_inicial=NO_APLICA,
            fecha_final=NO_APLICA,
            caja=donde.caja,
            carpeta=upd,
            tomo=NO_APLICA,
            otro=donde.otro,
            # Aquí sí es un recuento y no una constante: una resolución ocupa
            # las páginas que ocupe.
            folios=group.size,
            folios_siar=group.size,
            soporte=NO_APLICA,
            frecuencia=NO_APLICA,
            notas=(
                f"Páginas {group.page_numbers[0]} a {group.page_numbers[-1]} "
                "del documento de origen"
            ),
        )
        for desplazamiento, group in enumerate(groups)
    ]
