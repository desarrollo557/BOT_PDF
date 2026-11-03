"""Convierte las resoluciones agrupadas en filas del FUID.

El equivalente de `diploma_fuid` para el otro tipo de documento, y con las
mismas reglas del instructivo del formato. De una resolución se lee su número,
su asunto y la fecha con que se expidió -- «Dada en Cartagena de Indias, a los
dieciséis (16) días del mes de enero del año 2025» --; sin esa fórmula legible
las fechas extremas salen como N/A. Escribir ahí el año que aparece dentro del
número sería una fecha que nadie puede rastrear hasta el papel, y eso es
exactamente lo que el instructivo prohíbe.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Sequence

from ..domain.grouping import PageGroup
from ..domain.title import lo_que_resuelve
from .fuid import NO_APLICA, FuidRow, Ubicacion

logger = logging.getLogger(__name__)


def asunto(group: PageGroup, resuelve: str | None = None) -> str:
    """«RESOLUCION 030-2010 - CONFORMAR EL COMITÉ DE INVESTIGACIÓN…».

    El número y lo que ordena su RESUELVE, en mayúsculas (el operador,
    2026-11-03: «Asunto: RESOLUCION + RESUELVE»). Si el RESUELVE no se dejó
    leer, el título del encabezado («POR MEDIO DE LA CUAL SE FIJA…»): una fila
    que dijera sólo el número no distingue la 00006 de la 00007.
    """
    if resuelve:
        return f"RESOLUCION {group.code.value} - {resuelve}".upper()
    titulo = (group.title or "").strip()
    return f"RESOLUCION {group.code.value} {titulo}".strip().upper()


def _textos(group: PageGroup, texto_de: Callable[[int], str]) -> Iterator[str]:
    """El texto de cada página de la resolución, uno a uno: se para en el primer RESUELVE."""
    for numero in group.page_numbers:
        try:
            yield texto_de(numero)
        except Exception:  # noqa: BLE001 - el asunto es un dato más, no un requisito
            logger.debug("no se pudo leer la página %s", numero, exc_info=True)


def fecha_de_la_fila(group: PageGroup) -> str:
    """La fecha de la unidad en DD-MM-AAAA, o N/A si no se leyó."""
    partes = (group.fecha or "").split("-")
    if len(partes) != 3 or not all(p.isdigit() for p in partes):
        return NO_APLICA
    anio, mes, dia = partes
    return f"{dia}-{mes}-{anio}"


def filas_de_resoluciones(
    groups: Sequence[PageGroup],
    *,
    nombre_del_archivo: str,
    ubicacion: Ubicacion | None = None,
    desde: int = 1,
    texto_de: Callable[[int], str] | None = None,
) -> list[FuidRow]:
    """Una fila por resolución, en el orden en que aparecen en el documento.

    ``texto_de`` da el texto de una página; con él, el asunto lleva lo que
    ordena el RESUELVE (``lo_que_resuelve``).
    """
    donde = ubicacion or Ubicacion()
    upd = donde.carpeta_de(nombre_del_archivo)

    return [
        FuidRow(
            orden=desde + desplazamiento,
            codigo_trd=donde.codigo_trd,
            asunto=asunto(group, lo_que_resuelve(_textos(group, texto_de)) if texto_de else None),
            # El número de la resolución es el número de identificación de la
            # unidad documental, que es lo que el instructivo pide en esta
            # columna.
            consecutivo_inicial=group.code.value,
            # Por dónde empieza esta resolución, que es la costura con la que la
            # fila se vuelve a encontrar con el archivo que se escribió de ella.
            pagina_inicial=group.page_numbers[0] if group.page_numbers else None,
            # La resolución es una sola unidad: empieza y termina en su número.
            consecutivo_final=group.code.value,
            # Expedida un día concreto: la misma en las dos.
            fecha_inicial=fecha_de_la_fila(group),
            fecha_final=fecha_de_la_fila(group),
            caja=donde.caja_de(nombre_del_archivo),
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
