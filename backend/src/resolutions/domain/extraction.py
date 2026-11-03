from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .anchor import Anchor, find_anchors, normalized_lines
from .resolution_code import ResolutionCode

# Tokens that sit between the anchor and the number and carry no meaning.
_SEPARATOR_TOKENS = frozenset(
    {
        "N", "N°", "Nº", "N.", "NO", "NO.", "NE", "NRO", "NRO.", "NRO:",
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
    numbered = interna = False
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
        cleaned = token.strip(",;()[]\"'_*?“”")
        if not cleaned:
            continue
        if cleaned in _CALIFICATIVOS:
            interna = True
            continue
        # «N°.», «Nº.», «No:»: la partícula con su punto o sus dos puntos
        # detrás. La 00191 de 2025 está impresa «RESOLUCIÓN N°. 00191», y sin
        # esto su página no daba ni un candidato: la resolución entera se
        # archivaba dentro de la 00190.
        if cleaned in _SEPARATOR_TOKENS or cleaned.rstrip(".:") in _SEPARATOR_TOKENS:
            numbered = True
            continue
        cleaned = _unido_si_el_ocr_lo_partio(cleaned, tokens[indice + 1 : indice + 2])
        # "No.00086" glues the token to the number; the prefix is stripped
        # while parsing, so the announcement still counts.
        pegado = bool(_PARTICULA_PEGADA.match(cleaned))
        cleaned = _con_su_anio(cleaned, tokens[indice + 1 : indice + 3], interna=interna)
        if interna and re.fullmatch(r"(?:19|20)\d{2}", cleaned):
            # «Resolución Interna N“ — 2012»: el número en blanco y el año
            # solo. El año no es el número de nadie.
            return None
        if _looks_like_a_code(cleaned):
            code = ResolutionCode.try_parse(cleaned)
            if code is None:
                return None
            announced = numbered or pegado or len(cleaned) > len(code.value)
            return code, announced
        return None
    return None


#: Lo que una facultad escribe entre «RESOLUCIÓN» y el número y no es ni la
#: partícula ni el número: «RESOLUCIÓN INTERNA N°030- 2010» (Facultad de
#: Ciencias Sociales y Educación, caja 00C003303). Cortaba la lectura y ninguna
#: resolución interna abría documento: el PDF entero iba a cuarentena.
_CALIFICATIVOS = frozenset({"INTERNA", "INTERNAS"})
_PARTICULA_PEGADA = re.compile(r"^(?:NRO|NUM|N[º°O.]|#)\.?\d")
#: El consecutivo de una facultad, con su año pegado o sin él: «030-», «N°030»,
#: «020-2011», «011-14», «002--2023». Hasta tres cifras: rectoría escribe cinco
#: («00086») y esas no se tocan.
_DE_FACULTAD = re.compile(r"^(?:NRO|NUM|N[º°O.]*|#)?(\d{1,3})(?:[-–]{1,2}(\d{4}|\d{2}))?[-–]?$")
#: El año que va detrás, en el token siguiente: «- 2010», «-2011», «2011», «-14».
_ANIO_DETRAS = re.compile(r"^(?:[-–]{0,2}((?:19|20)\d{2})|[-–]{1,2}(\d{2}))$")


def _con_su_anio(numero: str, siguientes: list[str], *, interna: bool = False) -> str:
    """El consecutivo de una facultad en una sola forma, «NNN-AAAA».

    La misma resolución se escribe de varias maneras en la caja 00C003303, a
    veces en dos páginas seguidas: «Resolución Interna N°020 de 2011» y «N°
    020-2011», «N“ 009 2011», «N° 008 -2011», «No. 011-14», «No. 03-2022»,
    «No. 002--2023». Como códigos distintos, una resolución se partía en dos.
    Con la forma única -- el consecutivo en tres cifras y el año entero --, el
    año sigue siendo parte del número (así se distinguen de las de rectoría,
    ver ``_OFFICIAL_NUMBER``) y «03» y «003» son la misma. Sin año a la vista,
    el consecutivo sólo se rellena si ya tenía dos cifras: un «1» suelto no es
    un número de resolución.
    """
    hallado = _DE_FACULTAD.match(numero)
    if not hallado:
        return numero
    consecutivo, anio = hallado.groups()
    if anio is None:
        resto = [token.strip(",;.()") for token in siguientes]
        # El año suelto, sin «de» ni guion, sólo en una resolución interna: en
        # rectoría «No. 006 2025» es un número y un año que no se juntan.
        anunciado = interna or numero.endswith(("-", "–"))
        if resto and resto[0] == "DE":
            resto, anunciado = resto[1:], True
        if resto and (detras := _ANIO_DETRAS.match(resto[0])) and (anunciado or resto[0][0] in "-–"):
            anio = detras.group(1) or detras.group(2)
    if anio is None:
        return f"{int(consecutivo):03d}" if len(consecutivo) >= 2 else numero
    if len(anio) == 2:
        anio = f"20{anio}"
    return f"{int(consecutivo):03d}-{anio}"


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
