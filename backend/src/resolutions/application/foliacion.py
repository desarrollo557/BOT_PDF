"""El folio manda: cada escrito de la caja con las hojas que su numeración a mano dice.

Lo eligió el operador el 2026-11-12 sobre 7975593 («el folio manda»): la hoja
cuyo folio sigue al de la anterior es del mismo escrito, aunque un sello
«Recibido» de una copia anexa o la carta que se copia la hubieran hecho abrir; y
la hoja con el folio 1 detrás de un folio mayor abre uno nuevo. Ver
``domain/foliacion_del_escrito.py``.

Sin folios leídos -- «Solo OCR»: Tesseract no lee la letra a mano -- no cambia
nada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..domain.foliacion_del_escrito import Foliacion
from ..domain.grouping import GroupingResult, PageGroup
from ..domain.resolution_code import ResolutionCode


@dataclass(frozen=True, slots=True)
class PorElFolio:
    grupos: GroupingResult
    anexos: dict[str, list[int]]
    #: Las hojas que volvieron con el escrito de delante.
    unidas: tuple[int, ...] = ()
    #: Las hojas que abrieron su escrito.
    partidas: tuple[int, ...] = ()


def aplicar_la_foliacion(
    grupos: GroupingResult, anexos: dict[str, list[int]] | None, foliacion: Foliacion
) -> PorElFolio:
    """Parte en cada hoja que abre por su folio y une cada hoja que continúa con su escrito.

    Los documentos conservan su nombre y su tipo; el que nace de partir uno va
    sin ellos, y lo nombran los pasos de después. Los anexos siguen a sus hojas.
    """
    anexos = {codigo: list(paginas) for codigo, paginas in (anexos or {}).items()}
    if not foliacion.continua and not foliacion.abre:
        return PorElFolio(grupos, anexos)
    de_anexo = {p for paginas in anexos.values() for p in paginas}
    documentos: list[tuple[PageGroup | None, list[int]]] = [(g, list(g.page_numbers)) for g in grupos.groups]

    # Partir: lo que va desde la hoja con el folio 1 es otro escrito.
    partidas: list[int] = []
    for pagina in sorted(foliacion.abre):
        for indice, (grupo, paginas) in enumerate(documentos):
            if pagina in paginas and pagina != min(paginas):
                documentos[indice] = (grupo, [p for p in paginas if p < pagina])
                documentos.insert(indice + 1, (None, [p for p in paginas if p >= pagina]))
                partidas.append(pagina)
                break

    # Unir: la hoja que continúa va con la de delante, en el orden del papel.
    unidas: list[int] = []
    for pagina in sorted(foliacion.continua):
        dueno = {p: i for i, (_, paginas) in enumerate(documentos) for p in paginas}
        if pagina not in dueno or pagina - 1 not in dueno or dueno[pagina] == dueno[pagina - 1]:
            continue
        origen, destino = dueno[pagina], dueno[pagina - 1]
        # Sólo la hoja que el folio dice que sigue: lo que viene detrás en su
        # documento y el folio no ata -- la hoja 175, sola, detrás de la queja
        # de 149-174 -- se queda donde está (UPD2460819, 2026-11-12).
        documentos[origen] = (documentos[origen][0], [p for p in documentos[origen][1] if p != pagina])
        documentos[destino][1].append(pagina)
        documentos[destino][1].sort()
        unidas.append(pagina)
    if not unidas and not partidas:
        return PorElFolio(grupos, anexos)

    documentos = sorted(((g, p) for g, p in documentos if p), key=lambda d: min(d[1]))
    partes = [re.match(r"^(\d+)(.*)$", g.code.value) if g is not None else None for g, _ in documentos]
    ancho = max((len(m.group(1)) for m in partes if m), default=2)
    salida: list[PageGroup] = []
    nuevos_anexos: dict[str, list[int]] = {}
    for puesto, ((grupo, paginas), parte) in enumerate(zip(documentos, partes, strict=True), start=1):
        resto = parte.group(2) if parte else ""
        valor = f"{puesto:0{ancho}d}{resto}"
        codigo = ResolutionCode(value=valor, raw=grupo.code.raw if grupo is not None and resto.strip() else valor)
        if grupo is None:
            salida.append(PageGroup(code=codigo, page_numbers=paginas))
        else:
            salida.append(PageGroup(code=codigo, page_numbers=paginas, title=grupo.title, kind=grupo.kind, fecha=grupo.fecha))
        if suyos := [p for p in paginas if p in de_anexo]:
            nuevos_anexos[valor] = suyos
    return PorElFolio(
        GroupingResult(groups=salida, quarantine=list(grupos.quarantine), repairs=list(grupos.repairs)),
        nuevos_anexos,
        tuple(unidas),
        tuple(partidas),
    )
