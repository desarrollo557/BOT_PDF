"""Comprobar lo que se leyó, para cada tipo de documento.

Leer no es lo mismo que leer bien, y la diferencia no se ve en el resultado: un
folio "5" donde el papel dice "543" y un apellido "ALANCETE" donde dice
"ALANDETE" salen del OCR con el mismo aspecto que un dato correcto. Nadie los
descubre mirando la planilla.

Lo que sí se puede hacer es cruzar lo que el propio documento dice dos veces, y
comprobar que la lectura sea internamente coherente: que los folios de un libro
avancen de uno en uno, que todas las páginas de un empaste digan el mismo
número de libro, que una cédula tenga la forma de una cédula, que ninguna
página de resolución quede sin dueño. Cada una de esas comprobaciones es barata
y ninguna inventa nada: sólo señala dónde la lectura no se sostiene.

El resultado nunca corrige por su cuenta. Señala, y quien firma decide.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .diploma import DiplomaRecord
from .grouping import GroupingResult
from .matricula import StudentRecord
from .page import PageClassification, Provenance


class Severity(StrEnum):
    """Cuánto pesa lo que se encontró."""

    #: Falta algo que el inventario necesita, o la lectura se contradice a sí
    #: misma. La fila sale igual, con N/A donde no hay dato, pero alguien tiene
    #: que mirarla antes de firmar.
    ERROR = "error"

    #: La lectura es sospechosa pero puede ser correcta. Un folio repetido es
    #: casi siempre una hoja escaneada dos veces, y alguna vez es el libro.
    WARNING = "aviso"


@dataclass(frozen=True, slots=True)
class Issue:
    """Una cosa que no cuadra, con el sitio exacto donde no cuadra."""

    field: str
    reason: str
    severity: Severity = Severity.WARNING
    page_number: int | None = None
    observed: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "reason": self.reason,
            "severity": str(self.severity),
            "page": self.page_number,
            "observed": self.observed,
        }

    def describe(self) -> str:
        """Como lo lee el operador, con la página delante."""
        return f"pág. {self.page_number}: {self.reason}" if self.page_number else self.reason


# -----------------------------------------------------------------------------
#  Libros de registro de diplomas
# -----------------------------------------------------------------------------

#: Un número de identificación colombiano: cédula, cédula de extranjería o
#: tarjeta. Fuera de este rango no es un documento, es un error de lectura --
#: cuatro cifras suelen ser un folio que se coló, y trece, dos campos pegados.
_MIN_IDENTITY_DIGITS = 5
_MAX_IDENTITY_DIGITS = 11

_DIGITS = re.compile(r"\d")


def _folio_number(value: str | None) -> int | None:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    return int(digits) if digits else None


def validate_diplomas(records: Sequence[DiplomaRecord]) -> list[Issue]:
    """Todo lo que no se sostiene en la lectura de un libro de diplomas."""
    issues: list[Issue] = []
    issues.extend(_per_record(records))
    issues.extend(_across_the_book(records))
    return sorted(issues, key=lambda item: (item.page_number or 0, item.field))


def _per_record(records: Sequence[DiplomaRecord]) -> list[Issue]:
    issues: list[Issue] = []
    for record in records:
        # Los avisos que el propio lector levantó al leer la página: el folio
        # que no coincide consigo mismo, el nombre con un carácter imposible.
        issues.extend(
            Issue(
                field="lectura",
                reason=warning,
                severity=Severity.ERROR,
                page_number=record.page_number,
            )
            for warning in record.warnings
        )

        for field, value, label in (
            ("folio", record.trusted_folio, "el folio"),
            ("nombre", record.name, "el nombre del graduando"),
            ("titulo", record.degree, "el título recibido"),
            ("fecha", record.graduation_date, "la fecha de graduación"),
            ("libro", record.book, "el número de libro"),
        ):
            if not value:
                issues.append(
                    Issue(
                        field=field,
                        reason=f"no se pudo leer {label}",
                        severity=Severity.ERROR,
                        page_number=record.page_number,
                    )
                )

        if record.identity_number:
            digits = len(_DIGITS.findall(record.identity_number))
            if not (_MIN_IDENTITY_DIGITS <= digits <= _MAX_IDENTITY_DIGITS):
                issues.append(
                    Issue(
                        field="documento",
                        reason=(
                            f"el número de identificación tiene {digits} cifras, "
                            "que no es una cantidad posible"
                        ),
                        severity=Severity.ERROR,
                        page_number=record.page_number,
                        observed=record.identity_number,
                    )
                )
    return issues


def _across_the_book(records: Sequence[DiplomaRecord]) -> list[Issue]:
    """Lo que sólo se ve mirando el libro entero, no una página."""
    issues: list[Issue] = []

    # Un empaste es un libro. Si una página dice que es el 8 y otra que es el 1,
    # una de las dos se leyó mal, y sin este cruce nadie lo notaría.
    libros: dict[str, list[int]] = {}
    for record in records:
        if record.book:
            libros.setdefault(record.book, []).append(record.page_number)
    if len(libros) > 1:
        mayoritario = max(libros, key=lambda clave: len(libros[clave]))
        for libro, paginas in libros.items():
            if libro == mayoritario:
                continue
            issues.extend(
                Issue(
                    field="libro",
                    reason=(
                        f"esta página dice libro No. {libro} y el resto del "
                        f"documento dice {mayoritario}"
                    ),
                    severity=Severity.ERROR,
                    page_number=pagina,
                    observed=libro,
                )
                for pagina in paginas
            )

    vistos: dict[str, list[int]] = {}
    for record in records:
        folio = record.trusted_folio
        if folio:
            vistos.setdefault(folio, []).append(record.page_number)
    for folio, paginas in sorted(vistos.items()):
        if len(paginas) > 1:
            issues.append(
                Issue(
                    field="folio",
                    reason=f"el folio {folio} aparece en las páginas {paginas}",
                    severity=Severity.WARNING,
                    page_number=paginas[0],
                    observed=folio,
                )
            )

    numeros = sorted({n for record in records if (n := _folio_number(record.trusted_folio))})
    for anterior, siguiente in zip(numeros, numeros[1:], strict=False):
        if siguiente - anterior > 1:
            faltan = siguiente - anterior - 1
            issues.append(
                Issue(
                    field="folio",
                    reason=(
                        f"faltan {faltan} folio{'s' if faltan > 1 else ''} entre el "
                        f"{anterior} y el {siguiente}"
                    ),
                    severity=Severity.WARNING,
                )
            )

    issues.extend(
        Issue(
            field="anulado",
            reason="el folio lleva el sello ANULADO",
            severity=Severity.WARNING,
            page_number=record.page_number,
        )
        for record in records
        if record.annulled
    )
    return issues


# -----------------------------------------------------------------------------
#  Resoluciones
# -----------------------------------------------------------------------------


def validate_resolutions(
    classifications: Sequence[PageClassification],
    result: GroupingResult,
) -> list[Issue]:
    """Todo lo que no se sostiene en la lectura de un documento de resoluciones.

    Las comprobaciones son distintas de las de un libro porque el documento es
    distinto: aquí no hay un registro por página sino un número que manda hasta
    que aparece otro, y lo que puede salir mal es que una página se quede sin
    dueño, que dos números peleen por la misma, o que el número se leyera de una
    forma que no es la del encabezado oficial.
    """
    issues: list[Issue] = [
        Issue(
            field="pagina",
            reason="no hay ningún número de resolución antes de esta página",
            severity=Severity.ERROR,
            page_number=pagina,
        )
        for pagina in result.quarantine
    ]

    issues.extend(
        Issue(
            field="codigo",
            reason="hay números de resolución en conflicto en la página",
            severity=Severity.ERROR,
            page_number=page.page_number,
        )
        for page in classifications
        if page.ambiguous
    )

    issues.extend(
        Issue(
            field="pagina",
            reason="la página no se pudo leer por ninguna vía",
            severity=Severity.ERROR,
            page_number=page.page_number,
        )
        for page in classifications
        if page.provenance is Provenance.NONE and page.code is None
    )

    # Una corrección aplicada en silencio es indistinguible de un error, así que
    # se declara aunque el sistema esté seguro de ella.
    issues.extend(
        Issue(
            field="codigo",
            reason=(
                f"se leyó {repair.observed.value} y se aplicó {repair.applied.value} "
                f"porque las páginas vecinas coincidían"
            ),
            severity=Severity.WARNING,
            page_number=repair.page_number,
            observed=repair.observed.value,
        )
        for repair in result.repairs
    )

    issues.extend(
        Issue(
            field="titulo",
            reason=f"la resolución {group.code.value} quedó sin título",
            severity=Severity.WARNING,
            page_number=group.page_numbers[0],
            observed=group.code.value,
        )
        for group in result.groups
        if not group.title
    )

    # Un documento que agrupa por número reaparecido no está mal, pero sí es
    # raro: casi siempre significa que una página del medio se leyó con el
    # número de otra.
    issues.extend(
        Issue(
            field="codigo",
            reason=(
                f"las páginas de la resolución {group.code.value} no son "
                f"consecutivas: {group.page_numbers}"
            ),
            severity=Severity.WARNING,
            page_number=group.page_numbers[0],
            observed=group.code.value,
        )
        for group in result.groups
        if _has_gaps(group.page_numbers)
    )

    return sorted(issues, key=lambda item: (item.page_number or 0, item.field))


def _has_gaps(pages: Sequence[int]) -> bool:
    return any(b - a != 1 for a, b in zip(pages, pages[1:], strict=False))


# -----------------------------------------------------------------------------
#  Expedientes académicos
# -----------------------------------------------------------------------------


def validate_matriculas(records: Sequence[StudentRecord]) -> list[Issue]:
    """Todo lo que no se sostiene en la lectura de un legajo de expedientes.

    Las comprobaciones vuelven a ser distintas porque el documento es distinto.
    Aquí no hay folios que avancen de uno en uno ni un libro que todas las
    páginas repitan: hay expedientes que tienen que tener dueño, un código que
    no puede ser de dos personas, y unos años que no pueden ir al revés.
    """
    issues: list[Issue] = []

    for record in records:
        issues.extend(
            Issue(
                field="lectura",
                reason=warning,
                severity=Severity.ERROR,
                page_number=record.page_number,
            )
            for warning in record.warnings
        )

        # El expediente imprime sus años en el orden en que se cursaron --
        # "PRIMER AÑO 1.950" antes que "SEXTO AÑO 1.955" -- así que uno que
        # retrocede es una cifra mal leída. Las fechas extremas saldrían igual,
        # porque son el menor y el mayor, y nadie se enteraría: por eso se
        # comprueba el orden impreso y no el par que va a la planilla.
        for anterior, siguiente in zip(record.anios, record.anios[1:], strict=False):
            if int(siguiente) < int(anterior):
                issues.append(
                    Issue(
                        field="fecha",
                        reason=(
                            f"los años del expediente retroceden: {anterior} y "
                            f"después {siguiente}"
                        ),
                        severity=Severity.ERROR,
                        page_number=record.page_number,
                        observed=f"{anterior}, {siguiente}",
                    )
                )
                break

    # El código identifica al estudiante. Repetido en dos expedientes distintos
    # es casi siempre una carátula que se leyó con el código de la anterior, y
    # alguna vez son dos legajos de la misma persona que había que juntar.
    codigos: dict[str, list[int]] = {}
    for record in records:
        if record.codigo:
            codigos.setdefault(record.codigo, []).append(record.page_number)
    for codigo, paginas in sorted(codigos.items()):
        if len(paginas) > 1:
            issues.append(
                Issue(
                    field="codigo",
                    reason=(
                        f"el código {codigo} abre {len(paginas)} expedientes "
                        f"distintos, en las páginas {paginas}"
                    ),
                    severity=Severity.WARNING,
                    page_number=paginas[0],
                    observed=codigo,
                )
            )

    return sorted(issues, key=lambda item: (item.page_number or 0, item.field))


def summarise(issues: Sequence[Issue]) -> dict[str, object]:
    """El recuento que va al informe, para no tener que contar en la pantalla."""
    errores = sum(1 for issue in issues if issue.severity is Severity.ERROR)
    por_campo: dict[str, int] = {}
    for issue in issues:
        por_campo[issue.field] = por_campo.get(issue.field, 0) + 1
    return {
        "total": len(issues),
        "errores": errores,
        "avisos": len(issues) - errores,
        "por_campo": por_campo,
        "paginas": sorted({issue.page_number for issue in issues if issue.page_number}),
    }
