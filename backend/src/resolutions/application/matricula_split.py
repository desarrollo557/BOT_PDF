"""Partir un legajo de expedientes académicos: un archivo por estudiante.

Ni como las resoluciones ni como el libro de diplomas. Una resolución se agrupa
porque un número manda hasta que aparece otro; un libro de folios no se agrupa
en absoluto, porque cada cara es un registro terminado. Un expediente académico
se agrupa por **quién**: la carátula de matrícula dice de quién es, y las hojas
de asignaturas que la siguen son de esa misma persona hasta que aparece otra
carátula.

Esa decisión ya está tomada cuando esto se ejecuta -- la toma
``domain.matricula.group_students`` sobre lo que dicen las hojas -- así que aquí
sólo queda lo que el otro partidor también tiene que resolver: cómo se llama
cada archivo, y qué hacer cuando dos expedientes llevan el mismo código, que en
un legajo mal ordenado pasa.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.grouping import GroupingResult, PageGroup
from ..domain.matricula import StudentRecord
from ..domain.resolution_code import ResolutionCode


def _identity(registro: StudentRecord, tomados: set[str]) -> ResolutionCode:
    """Cómo se llama el archivo de este expediente, sin pisar a ninguno.

    El código del estudiante es lo natural: es con lo que la Universidad lo
    cita. Cuando no se pudo leer, se usa el número de la primera página, que
    siempre existe y nunca miente. Y cuando el código ya salió antes se le añade
    la página, porque un código repetido es un hecho del legajo que el nombre
    del archivo tiene que conservar en vez de borrar un expediente con otro.
    """
    base = (registro.codigo or "").strip() or f"pagina-{registro.page_number}"
    candidato = base if base not in tomados else f"{base}-p{registro.page_number}"
    tomados.add(candidato)
    return ResolutionCode.try_parse(candidato) or ResolutionCode(
        value=f"PAGINA-{registro.page_number}", raw=candidato
    )


def _subject(registro: StudentRecord) -> str | None:
    """Lo que va en el nombre del archivo después del código."""
    partes = [parte for parte in (registro.nombre, registro.carrera) if parte]
    return " ".join(partes) if partes else None


def group_by_student(registros: Sequence[StudentRecord]) -> GroupingResult:
    """Un grupo por expediente, con todas sus hojas y en el orden del PDF.

    Nada va a cuarentena. Las hojas que aparecen antes de la primera carátula
    forman su propio expediente sin nombre en vez de desaparecer en un montón
    común: alguien tiene que poder mirarlas, y para eso hacen falta como
    archivo.
    """
    tomados: set[str] = set()
    return GroupingResult(
        groups=[
            PageGroup(
                code=_identity(registro, tomados),
                page_numbers=list(registro.page_numbers),
                title=_subject(registro),
            )
            for registro in registros
        ]
    )
