"""Partir una caja revuelta: un archivo por documento.

Los otros partidores tienen un número que leer. Una resolución trae el suyo en
el encabezado, un folio de diplomas trae el suyo impreso, y un expediente
académico trae el código del estudiante. Una caja de correspondencia no trae
nada de eso: el número de reclamación que llevan todas sus hojas identifica el
expediente entero, no la factura ni el recurso que hay dentro.

Así que aquí el nombre no se lee, se cuenta. Un documento recién cortado se
llama por el puesto que ocupa en la caja, que es lo único que se sabe de él
antes de clasificarlo y que además es cierto.

Suena poco y es suficiente para lo que hace falta ahora: con esto la caja ya sale
como PDF separados y alguien puede abrirlos y ver si los cortes están donde
tenían que estar. El tipo de papel -- factura, pagaré, recurso de reposición --
llega después, sobre documentos que ya tienen bordes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from ..domain.grouping import GroupingResult, PageGroup
from ..domain.naming import DOCUMENT_PREFIX
from ..domain.resolution_code import ResolutionCode
from ..domain.segmentation import Segment
from .clasificacion import describir

#: Lo menos que puede ocupar el número de un documento. Una caja de seis piezas
#: sale igual de ordenada con un solo dígito, pero "01" se lee como un puesto en
#: una serie y "1" se lee como un archivo suelto.
MIN_ORDINAL_WIDTH = 2


def _identity(position: int, width: int) -> ResolutionCode:
    """El puesto del documento en la caja, rellenado para que ordene bien.

    El relleno sigue al total y no a una constante porque el listado de la
    carpeta ordena por texto: en una caja de cien documentos, "100" se pone
    delante de "99" y el operador ve la caja desordenada justo cuando más
    archivos tiene que revisar.
    """
    value = f"{position:0{width}d}"
    return ResolutionCode(value=value, raw=value)


def _subject(segment: Segment) -> str:
    """De qué páginas del origen salió este archivo.

    No es el asunto del documento -- eso no se sabe todavía -- sino su
    procedencia, que es lo que permite volver al PDF original a comprobar un
    corte sin abrir los cien archivos de al lado.
    """
    first, last = segment.page_numbers[0], segment.page_numbers[-1]
    if first == last:
        return f"página {first}"
    return f"páginas {first}-{last}"


def group_by_segment(
    segments: Sequence[Segment],
    texto_de: Callable[[int], str] | None = None,
) -> GroupingResult:
    """Un grupo por documento, en el orden en que venían en la caja.

    Nada va a cuarentena: la segmentación ya cubrió la caja entera -- su propio
    cuadre lo exige antes de llegar aquí -- así que no queda página sin dueño.

    Un segmento sin páginas no produce archivo ni gasta número. ``assemble`` no
    los genera, pero el escritor no tiene cómo defenderse de uno si aparece, y un
    PDF de cero hojas en la entrega se ve igual que una página perdida.
    """
    poblados = [segment for segment in segments if segment.page_numbers]
    width = max(MIN_ORDINAL_WIDTH, len(str(len(poblados))))

    crudos = GroupingResult(
        groups=[
            PageGroup(
                code=_identity(position, width),
                page_numbers=list(segment.page_numbers),
                title=_subject(segment),
            )
            for position, segment in enumerate(poblados, start=1)
        ]
    )
    # El tipo lo pone el clasificador, que es el mismo para todas las rutas: la
    # pregunta "qué papel es esto" no depende de cómo se haya cortado.
    tipificados = describir(crudos, texto_de)

    # Y siempre hay algo que escribir en el nombre. "DOCUMENTO" cuando ni el
    # papel ni el contexto dijeron nada: dejarlo vacío sacaría el archivo
    # llamado sólo por su número, y entonces la carpeta no distingue lo que
    # nadie reconoció de lo que nadie miró.
    return GroupingResult(
        groups=[
            group if group.kind else replace(group, kind=DOCUMENT_PREFIX)
            for group in tipificados.groups
        ]
    )
