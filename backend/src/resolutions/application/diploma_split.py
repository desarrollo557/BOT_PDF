"""Partir un libro de diplomas: un archivo por registro.

Un documento de resoluciones se parte por herencia -- un número manda hasta que
aparece otro -- y por eso una resolución puede ocupar cuarenta páginas. Un libro
de folios no funciona así: cada cara es un registro terminado, con su folio y su
graduando, y la división es uno a uno.

De modo que aquí no hay nada que agrupar. Lo único que hace falta decidir es
cómo se llama cada archivo y qué hacer cuando dos páginas dicen el mismo folio,
que en estos libros pasa: una hoja fotografiada dos veces produce dos registros
idénticos, y si los dos archivos se llamaran igual, el segundo borraría al
primero y nadie volvería a saber que la duplicación existió.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.diploma import DiplomaRecord
from ..domain.grouping import GroupingResult, PageGroup
from ..domain.resolution_code import ResolutionCode


def _identity(record: DiplomaRecord, taken: set[str]) -> ResolutionCode:
    """Cómo se llama el archivo de este registro, sin pisar a ninguno.

    Cuando la cédula está presente, es la identidad estable del graduado y por
    eso funciona mejor como base del nombre del archivo que el folio, que puede
    repetirse en el mismo libro.
    """
    identity = (record.identity_number or "").strip()
    folio = (record.folio or "").strip() or (record.trusted_folio or "").strip()
    base = identity or folio or f"pagina-{record.page_number}"
    candidate = base if base not in taken else f"{base}-p{record.page_number}"
    taken.add(candidate)
    return ResolutionCode.try_parse(candidate) or ResolutionCode(
        value=f"PAGINA-{record.page_number}", raw=candidate
    )


def _subject(record: DiplomaRecord) -> str | None:
    """Lo que va en el nombre del archivo después del folio."""
    partes = [part for part in (record.name, record.degree) if part]
    return " ".join(partes) if partes else None


def _same_person(record: DiplomaRecord, prior: DiplomaRecord | None) -> bool:
    """Si dos registros son la misma persona y el mismo folio.

    La excepción sólo aplica cuando el folio vuelve a repetirse y además la
    cédula coincide. Si la cédula cambia, o si el folio cambia, no hay
    agrupación: son dos registros distintos y cada uno sale por su identidad.
    """
    if prior is None:
        return False

    current_id = (record.identity_number or "").strip()
    prior_id = (prior.identity_number or "").strip()
    current_folio = (record.folio or "").strip()
    prior_folio = (prior.folio or "").strip()

    if not current_folio or not prior_folio:
        return False
    if current_folio != prior_folio:
        return False
    if not current_id or not prior_id:
        return False
    return current_id == prior_id


def group_by_record(records: Sequence[DiplomaRecord]) -> GroupingResult:
    """Un archivo por registro, con las páginas que ese registro se lleve.

    Casi siempre es una página y una sola: en un libro de folios cada cara es un
    registro terminado. La excepción es la página que no trae **ningún**
    identificador, y ésa no es un registro: es la vuelta de la hoja anterior, o
    algo que alguien anexó -- la fotografía de una cédula, un formato --. El
    archivo de la Universidad escanea las hojas por las dos caras cuando llevan
    algo detrás y lo anota poniendo una "v" junto al folio escrito a mano en la
    esquina superior derecha; la cara de atrás llega sin folio y sin nada más.

    Cuando dos páginas repiten el mismo folio, sólo se agrupan si pertenecen a la
    misma cédula. Si el folio repite pero el graduando es distinto, no hay
    excepción: son dos registros diferentes y cada uno sale por su identidad.
    """
    taken: set[str] = set()
    abiertos: list[tuple[ResolutionCode, list[int], str | None, DiplomaRecord]] = []
    for record in records:
        if record.carries_no_identifier and abiertos:
            abiertos[-1][1].append(record.page_number)
            continue

        previous = abiertos[-1][3] if abiertos else None
        if previous is not None and _same_person(record, previous):
            abiertos[-1][1].append(record.page_number)
            continue

        identity = _identity(record, taken)
        abiertos.append((identity, [record.page_number], _subject(record), record))
    return GroupingResult(
        groups=[
            PageGroup(code=code, page_numbers=paginas, title=titulo)
            for code, paginas, titulo, _record in abiertos
        ]
    )
