from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .anchor import Anchor, find_anchors, normalized_lines
from .resolution_code import ResolutionCode

# Tokens that sit between the anchor and the number and carry no meaning.
_SEPARATOR_TOKENS = frozenset(
    {
        "N", "N°", "Nº", "N.", "NO", "NO.", "NRO", "NRO.", "NRO:",
        "NUM", "NUM.", "NUMERO", "#", ":", "-", "–", "—", ".", "·",
    }
)

_CODE_SHAPE = re.compile(r"^[A-Z0-9º°#][A-Z0-9/\-.º°]*$")
_MIN_DIGITS = 2

# El número tal como lo escribe un encabezado de verdad.
#
# La forma de rectoría va sin separadores y con ceros a la izquierda:
# "RESOLUCION No. 00086", "Resolución No. 00072 de 2023".
#
# Las facultades numeran distinto. Una resolución de decanatura se escribe
# "RESOLUCIÓN No. 002-2023": el consecutivo del año y el año, unidos por un
# guion. Exigir sólo dígitos las dejaba fuera de la forma oficial, y con eso
# fuera de lo que puede abrir una unidad documental: la resolución 002-2023 de
# la Facultad de Ciencias Sociales y Educación, que ocupa los folios 118 a 122
# del libro 00072-00094 con su encabezado, su CONSIDERANDO y su RESUELVE, se
# archivaba entera dentro de la resolución de rectoría 00087.
_OFFICIAL_NUMBER = re.compile(r"^\d{3,6}(?:[-/]\d{4})?$")


@dataclass(frozen=True, slots=True)
class RawCandidate:
    """A code found next to an anchor, before any judgement about who owns it."""

    code: ResolutionCode
    anchor: Anchor
    line_index: int
    total_lines: int
    line_text: str
    context_before: str
    #: Lo que queda del renglón normalizado detrás del ancla, con el token de
    #: numeración y el número incluidos. Es lo que distingue un encabezado de
    #: una frase: detrás de un encabezado no sigue hablando nadie.
    context_after: str = ""
    #: Dónde está el renglón dentro de su página, en fracciones de 0 a 1: el
    #: centro horizontal y el borde superior. ``None`` cuando quien leyó la
    #: página no sabe decirlo -- el OCR entrega texto, no coordenadas -- y
    #: entonces se decide sin geometría, como se hacía antes.
    center_x: float | None = None
    top: float | None = None
    #: The anchor was followed by a numbering token and a padded number -- the
    #: exact shape the official header uses. Read by scoring, so a title-cased
    #: header is recognised on its structure rather than on its capitals.
    official_form: bool = False


def _looks_like_a_code(token: str) -> bool:
    if not _CODE_SHAPE.match(token):
        return False
    return sum(ch.isdigit() for ch in token) >= _MIN_DIGITS


def _first_code(segment: str) -> tuple[ResolutionCode, bool] | None:
    """Read the first plausible code in ``segment``, and how it was announced.

    The scan stops at the first token that is neither a separator nor a code.
    Walking past real words would let "RESOLUCION DE DIRECTORIO 2024" capture a
    year as if it were a resolution number.

    The flag says whether a numbering token ("No.", "N°", "NRO.") stood between
    the anchor and the number, which is half of what makes a header official.
    """
    numbered = False
    for token in segment.split():
        # Los filetes que el escáner pega al número cuentan como puntuación de
        # borde, igual que un paréntesis. La resolución 00966 del libro
        # 00960-00979 está impresa sobre una raya y su capa de texto sale como
        # "RESOLUCIÓN No. 00966_____________________________", con los guiones
        # bajos pegados: el número no llegaba a parecer un número, la página no
        # producía ni un candidato y la resolución entera desapareció del
        # entregable. En el folio 31 la misma raya salió separada por un
        # espacio, y por eso la 00964 sí se leía.
        #
        # El asterisco y la interrogación son lo que el OCR pone donde el papel
        # tiene el "°" del "N°", y por un solo carácter dejaba de reconocerse la
        # partícula de numeración. Las dos resoluciones que faltaban del libro
        # 00960-00979 se leen bien de la imagen y se perdían justo ahí:
        # "RESOLUCIÓN N* 00973" en el folio 208 y "RESOLUCIÓN N? 00974" en el
        # 209.
        cleaned = token.strip(",;()[]\"'_*?")
        if not cleaned:
            continue
        if cleaned in _SEPARATOR_TOKENS:
            numbered = True
            continue
        if _looks_like_a_code(cleaned):
            code = ResolutionCode.try_parse(cleaned)
            if code is None:
                return None
            # "No.00086" glues the token to the number; the prefix is stripped
            # while parsing, so the announcement still counts.
            announced = numbered or len(cleaned) > len(code.value)
            return code, announced
        return None
    return None


def extract_candidates(
    page_text: str, geometry: Sequence[tuple[float, float]] | None = None
) -> list[RawCandidate]:
    """Every (anchor, code) pair on the page, in reading order.

    ``geometry`` da, por renglón y en el mismo orden, el centro horizontal y el
    borde superior en fracciones de página. Es opcional porque el OCR entrega
    texto sin coordenadas; cuando llega, es lo que permite exigirle a un
    encabezado que esté donde va un encabezado.
    """
    lines = normalized_lines(page_text)
    original = page_text.splitlines()
    total = len(lines)

    candidates: list[RawCandidate] = []
    for anchor in find_anchors(page_text):
        line = lines[anchor.line_index]
        found = _first_code(line[anchor.end :])
        if found is None and anchor.line_index + 1 < total:
            # Centred headers wrap: the word ends the line and the number starts
            # the next one.
            found = _first_code(lines[anchor.line_index + 1])
        if found is None:
            continue

        code, announced = found
        sitio = (
            geometry[anchor.line_index]
            if geometry is not None and anchor.line_index < len(geometry)
            else None
        )
        candidates.append(
            RawCandidate(
                code=code,
                anchor=anchor,
                line_index=anchor.line_index,
                total_lines=total,
                line_text=original[anchor.line_index],
                context_before=line[: anchor.start],
                context_after=line[anchor.end :],
                official_form=announced and bool(_OFFICIAL_NUMBER.match(code.value)),
                center_x=sitio[0] if sitio else None,
                top=sitio[1] if sitio else None,
            )
        )
    return candidates
