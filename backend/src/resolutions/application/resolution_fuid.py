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
import re
from collections.abc import Callable, Iterator, Sequence

from ..domain.fechas import fecha_de_expedicion
from ..domain.grouping import PageGroup
from ..domain.serie_del_legajo import es_de_las_previas
from ..domain.title import lo_que_resuelve
from ..domain.titulo_impreso import nombre_por_su_origen
from .fuid import NO_APLICA, FuidRow, Ubicacion

logger = logging.getLogger(__name__)


def asunto(group: PageGroup, resuelve: str | None = None, *, nombre_del_archivo: str = "") -> str:
    """«RESOLUCION 030-2010 - CONFORMAR EL COMITÉ DE INVESTIGACIÓN…».

    El número y lo que ordena su RESUELVE, en mayúsculas (el operador,
    2026-11-03: «Asunto: RESOLUCION + RESUELVE»). Si el RESUELVE no se dejó
    leer, el título del encabezado («POR MEDIO DE LA CUAL SE FIJA…»): una fila
    que dijera sólo el número no distingue la 00006 de la 00007.

    Las hojas de antes de la primera resolución (``es_de_las_previas``) no son
    una resolución: su asunto es el título que imprimen -- «SOLICITUD DE
    EXAMEN» -- y, si no imprimen ninguno, de dónde salieron y qué páginas
    son (``nombre_por_su_origen``). Nunca un nombre genérico (2026-11-27).
    """
    if es_de_las_previas(group.code.value):
        titulo = (group.title or group.code.raw or "").strip()
        return (titulo or nombre_por_su_origen(nombre_del_archivo, group.page_numbers)).upper()
    if resuelve:
        return f"RESOLUCION {group.code.value} - {resuelve}".upper()
    # Con el título, la misma forma que con lo que resuelve: «RESOLUCION NNN -
    # …», el estándar único de la UdeC (2026-11-27).
    titulo = (group.title or "").strip()
    return (f"RESOLUCION {group.code.value} - {titulo}" if titulo else f"RESOLUCION {group.code.value}").upper()


def asunto_del_grupo(
    group: PageGroup, texto_de: Callable[[int], str] | None, *, nombre_del_archivo: str = ""
) -> str:
    """El asunto de la fila de ``group``, leído de sus páginas: es también el nombre de su PDF.

    El PDF de cada resolución se llama como su fila del FUID, «NN_RESOLUCION
    007-1998 - FIJAR LA FECHA…» (el estándar único de la UdeC, 2026-11-27): el
    escritor y el FUID lo piden aquí, a la misma función, para que no puedan
    decir dos cosas distintas.
    """
    resuelve = (
        lo_que_resuelve(_textos(group, texto_de))
        if texto_de is not None and not es_de_las_previas(group.code.value)
        else None
    )
    return asunto(group, resuelve, nombre_del_archivo=nombre_del_archivo)


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


#: «Dada» y lo que el OCR hizo del «en Cartagena» hasta «a los»: «Dada^jBRDartagena
#: a los 14 días…», «Dada enjigrtagena a los…» (decanatura de Odontología,
#: 2026-11-27). Con la fórmula así no se leía la fecha y la fila tomaba la de
#: su vecina en la serie: el día equivocado.
_DADA_DANADA = re.compile(r"\b(Dad[ao])\b[^\n]{0,30}?(?=\ba\s*los\b)", re.IGNORECASE)


def _con_la_formula_de_su_papel(group: PageGroup, texto_de: Callable[[int], str]) -> str | None:
    """La fecha de la fórmula de cierre de la resolución con el «en Cartagena» destrozado, o ``None``.

    Sólo cuando la fórmula tal cual no se deja leer: entonces la fecha de la
    unidad vino de la serie (``completar_por_la_serie``) y la del papel, aunque
    dañada, es mejor.
    """
    textos = list(_textos(group, texto_de))
    numero = group.code.value[:3] if group.code.value[:3].isdigit() else None
    if fecha_de_expedicion(textos, numero=numero) is not None:
        return None
    reparados = [_DADA_DANADA.sub(lambda m: f"{m.group(1)} en Cartagena, ", texto) for texto in textos]
    fecha = fecha_de_expedicion(reparados, numero=numero)
    return fecha.strftime("%d-%m-%Y") if fecha else None


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

    def numero(group: PageGroup) -> str:
        # Las hojas previas no tienen número: no se inventa uno.
        return NO_APLICA if es_de_las_previas(group.code.value) else group.code.value

    def fecha(group: PageGroup) -> str:
        # La de su fórmula aunque el OCR la haya dañado, antes que la de la serie.
        if texto_de is not None and not es_de_las_previas(group.code.value):
            return _con_la_formula_de_su_papel(group, texto_de) or fecha_de_la_fila(group)
        return fecha_de_la_fila(group)

    return [
        FuidRow(
            orden=desde + desplazamiento,
            codigo_trd=donde.codigo_trd,
            asunto=asunto_del_grupo(group, texto_de, nombre_del_archivo=nombre_del_archivo),
            # El número de la resolución es el número de identificación de la
            # unidad documental, que es lo que el instructivo pide en esta
            # columna. En un legajo de facultad, con su año: «007-1998».
            consecutivo_inicial=numero(group),
            # Por dónde empieza esta resolución, que es la costura con la que la
            # fila se vuelve a encontrar con el archivo que se escribió de ella.
            pagina_inicial=group.page_numbers[0] if group.page_numbers else None,
            # La resolución es una sola unidad: empieza y termina en su número.
            consecutivo_final=numero(group),
            # Expedida un día concreto: la misma en las dos.
            fecha_inicial=fecha(group),
            fecha_final=fecha(group),
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
