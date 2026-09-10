"""Qué clase de papel es cada unidad documental, para todas las rutas.

Corre **después** del corte, nunca antes: preguntarle a una caja de cien hojas
de qué tipo es no tiene respuesta, y sobre un documento que ya tiene bordes casi
siempre está contestada en la propia hoja.

Vive aquí, en la aplicación, y no dentro del partidor de cajas, porque la
pregunta es la misma se haya cortado como se haya cortado. Una resolución, un
folio de diplomas, un expediente de matrícula y un documento de una caja
revuelta son cuatro unidades que se delimitan de cuatro maneras distintas, y las
cuatro son un papel del que el archivo quiere saber qué es. Tener la respuesta
sólo en una de las rutas era tenerla a medias: el inventario de las otras tres
salía sin la columna.

El orden de las fuentes lo fijó el operador, y es el de lo más directo primero:

1. **El asunto.** El documento diciendo de qué trata, en el renglón donde el
   papel oficial lo declara.
2. **El encabezado.** Cuando no hay asunto -- un acta no lo lleva, una
   constancia tampoco -- lo que queda es cómo se titula la hoja.
3. **Una mención en el cuerpo.** Sólo si las dos anteriores callan.
4. **El contexto.** Y si la hoja no dice absolutamente nada de sí misma, lo que
   venía antes: una hoja suelta con una firma es la última cara del escrito que
   la precede.

Las tres primeras las resuelve `domain.tipo_documental` sobre una unidad
aislada. La cuarta necesita ver la entrega entera, y por eso está aquí.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import replace

from ..domain.fechas import ultima_fecha
from ..domain.grouping import GroupingResult, PageGroup
from ..domain.tipo_documental import PAGINAS_MIRADAS, identificar_documento

logger = logging.getLogger(__name__)

#: Cuántas hojas puede tener una unidad para que se le crea un tipo heredado del
#: contexto. Una hoja suelta detrás de un acta -- la de las firmas, un sello, el
#: reverso de un folio -- pertenece a lo que venía antes. Cuatro hojas seguidas
#: que no dicen nada de sí mismas ya no son la cola de nada: son un documento del
#: que no se sabe qué es, y llamarlo como su vecino sería inventarlo.
MAX_HOJAS_HEREDADAS = 2


def tipo_de(
    page_numbers: Sequence[int], texto_de: Callable[[int], str] | None
) -> str | None:
    """El tipo que declara una unidad documental, o ``None`` si no declara ninguno.

    Se le pasan las primeras páginas al catálogo del archivo y se acepta lo que
    conteste. Un fallo leyendo una página no cuesta la unidad: cuesta su tipo, y
    sin tipo el archivo sale con nombre genérico, que es exactamente lo que le
    pasa al tercio de una caja que no lleva rótulo legible.
    """
    if texto_de is None:
        return None
    paginas: list[str] = []
    for page_number in list(page_numbers)[:PAGINAS_MIRADAS]:
        try:
            paginas.append(texto_de(page_number))
        except Exception:  # noqa: BLE001 - el tipo es un extra, no un requisito
            logger.debug("no se pudo leer la página %s para tipificar", page_number)
            return None
    encontrado = identificar_documento(paginas)
    return encontrado.nombre if encontrado is not None else None


def clasificar(
    result: GroupingResult,
    texto_de: Callable[[int], str] | None,
    *,
    heredar: bool = True,
) -> GroupingResult:
    """Pone el tipo documental en cada grupo que no lo traiga ya.

    Devuelve una agrupación nueva: ``PageGroup`` es inmutable, y serlo es lo que
    impide que una clasificación tardía cambie por debajo lo que el escritor ya
    usó para nombrar un archivo.

    ``heredar`` es la cuarta fuente, la del contexto, y se puede apagar. Está
    encendida por omisión porque es lo que el operador pidió para las hojas que
    no dicen nada, y apagarla tiene sentido en un legajo homogéneo -- un libro
    de folios -- donde heredar no aportaría nada que no se supiera ya.
    """
    if texto_de is None:
        return result

    grupos: list[PageGroup] = []
    contexto: str | None = None
    for group in result.groups:
        propio = group.kind or tipo_de(group.page_numbers, texto_de)
        if propio is not None:
            contexto = propio
        elif heredar and contexto is not None and group.size <= MAX_HOJAS_HEREDADAS:
            propio = contexto
        grupos.append(group if propio == group.kind else replace(group, kind=propio))

    return replace(result, groups=grupos)


def fechar(
    result: GroupingResult, texto_de: Callable[[int], str] | None
) -> GroupingResult:
    """Pone en cada unidad la fecha más reciente que lleva escrita.

    Se lee el documento **entero**, no sus primeras páginas, y ésa es la
    diferencia con la clasificación: el tipo se declara arriba y la fecha
    aparece donde caiga. Un acta puede llevar la fecha de la visita en su
    primera hoja y la del acuse de recibo en la última, y la que fecha la
    unidad es la segunda.

    Es la fecha extrema final del FUID. Se descartan las citadas -- "Ley 142 de
    1994", "Sentencia T-1204 de 2001" -- porque un escrito jurídico nombra
    docenas y ninguna dice cuándo se escribió el papel que las cita.
    """
    if texto_de is None:
        return result

    grupos: list[PageGroup] = []
    for group in result.groups:
        if group.fecha is not None:
            grupos.append(group)
            continue
        try:
            paginas = [texto_de(numero) for numero in group.page_numbers]
        except Exception:  # noqa: BLE001 - la fecha es un dato más, no un requisito
            logger.debug("no se pudo leer %s para fecharlo", group.code.value)
            grupos.append(group)
            continue
        fecha = ultima_fecha(paginas)
        grupos.append(group if fecha is None else replace(group, fecha=fecha.isoformat()))

    return replace(result, groups=grupos)


def describir(
    result: GroupingResult,
    texto_de: Callable[[int], str] | None,
    *,
    heredar: bool = True,
) -> GroupingResult:
    """Todo lo que se puede saber de cada unidad leyendo sus páginas.

    Las dos pasadas juntas, que es como las quieren las cuatro rutas: qué
    clase de papel es y de cuándo es.
    """
    return fechar(clasificar(result, texto_de, heredar=heredar), texto_de)
