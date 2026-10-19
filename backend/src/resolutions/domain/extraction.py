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

#: Cuántas cifras lleva un número de rectoría: «00185». Es lo que permite
#: reconocer uno que el OCR partió en dos -- «RESOLUCIÓN No. 001 85 de 2025» --,
#: que se leía «001» y se llevaba las páginas de la 00185 y de la 00187 (libro
#: 00184-00210 de 2025) a un archivo que no era de nadie.
_CIFRAS_DE_RECTORIA = 5
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
    tokens = segment.split()
    for indice, token in enumerate(tokens):
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
        # «N°.», «Nº.», «No:»: la partícula con su punto o sus dos puntos
        # detrás. La 00191 de 2025 está impresa «RESOLUCIÓN N°. 00191», y sin
        # esto su página no daba ni un candidato: la resolución entera se
        # archivaba dentro de la 00190.
        if cleaned in _SEPARATOR_TOKENS or cleaned.rstrip(".:") in _SEPARATOR_TOKENS:
            numbered = True
            continue
        cleaned = _unido_si_el_ocr_lo_partio(cleaned, tokens[indice + 1 : indice + 2])
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


def _unido_si_el_ocr_lo_partio(numero: str, siguiente: list[str]) -> str:
    """«001» seguido de «85» es la 00185, si juntos dan las cifras de rectoría.

    Sólo cifras con cifras y sólo si la primera parte trae los ceros de la
    izquierda: así «No. 006 2025» -- un número y un año -- no se toca.
    """
    if not (numero.isdigit() and numero.startswith("0") and siguiente):
        return numero
    resto = siguiente[0].strip(",;()[]\"'_*?")
    if resto.isdigit() and len(numero) + len(resto) == _CIFRAS_DE_RECTORIA:
        return numero + resto
    return numero


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


# -- el número que sigue en la serie ----------------------------------------------

#: Cuántos renglones de arriba se miran: donde va un encabezado.
RENGLONES_DE_LA_CABECERA = 12
#: Qué parte de «RESOLUCION» tiene que conservar, en orden, la palabra que el
#: OCR destrozó: «RHSOIAJCIÓN» conserva R-S-O-C-I-O-N, «^oLVcióa» O-L-C-I-O.
PARECIDO_A_RESOLUCION = 0.5
_PALABRA = "RESOLUCION"


def _comun_en_orden(a: str, b: str) -> int:
    """Cuántas letras de ``a`` aparecen en ``b`` en el mismo orden (subsecuencia común)."""
    anterior = [0] * (len(b) + 1)
    for letra in a:
        actual = [0]
        for j, otra in enumerate(b, start=1):
            actual.append(anterior[j - 1] + 1 if letra == otra else max(anterior[j], actual[j - 1]))
        anterior = actual
    return anterior[-1]


def _parece_resolucion(renglon: str) -> bool:
    for palabra in re.findall(r"[A-ZÑ]{5,}", renglon):
        if _comun_en_orden(_PALABRA, palabra) / len(_PALABRA) >= PARECIDO_A_RESOLUCION:
            return True
    return False


def siguiente_en_la_cabecera(texto: str, abierta: ResolutionCode) -> ResolutionCode | None:
    """La resolución que sigue a ``abierta``, si su encabezado está en esta cabecera.

    Es el peldaño de la secuencia: un libro de rectoría va en orden -- 00591,
    00592, 00593 -- y la página que trae arriba exactamente el número siguiente,
    junto a algo que fue la palabra «resolución», es su encabezado aunque el
    OCR haya destrozado esa palabra. Las dos que faltaban en la muestra de la
    carpeta RESOLUCIONES DE RECTORIA 3220 - 3259 eran así: «RHSOIAJCIÓN No
    00676 DE 2025» y «^oLVcióa^í^ 00592 <u lois» (letra decorativa de una
    resolución de condolencias), cada una archivada dentro de la anterior.

    Exigir el número exacto y la palabra parecida es lo que lo hace seguro: un
    número cualquiera en la cabecera no abre nada.
    """
    if not (abierta.value.isdigit() and len(abierta.value) == 5):
        return None
    esperado = f"{int(abierta.value) + 1:05d}"
    numero = re.compile(rf"(?<!\d){esperado}(?!\d)")
    for renglon in normalized_lines(texto)[:RENGLONES_DE_LA_CABECERA]:
        if numero.search(renglon) and _parece_resolucion(renglon):
            return ResolutionCode.try_parse(esperado)
    return None
