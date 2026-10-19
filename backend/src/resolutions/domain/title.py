from __future__ import annotations

import re

from .anchor import find_anchors, strip_accents

DEFAULT_MAX_LENGTH = 120
DEFAULT_SLUG_LENGTH = 60

#: How far past the heading a title is allowed to hide. Beyond this the document
#: has moved on to its body and anything picked up would be a sentence, not a name.
DEFAULT_SCAN_LINES = 8

_SUBJECT_LINE = re.compile(
    r"^\s*(ASUNTO|REFERENCIA|REF|OBJETO|TEMA|MOTIVO)\s*[:\-–—]\s*(.+)$",
    re.IGNORECASE,
)

# Lines that sit where a title would but never are one. "QUE" opens every recital
# in Spanish administrative drafting, so a line starting with it is body text.
_FURNITURE_WORDS = frozenset(
    {
        "VISTO",
        "VISTOS",
        "CONSIDERANDO",
        "QUE",
        "PAGINA",
        "PAG",
        "FOLIO",
        "EXPTE",
        "EXPEDIENTE",
        "ANEXO",
        "FECHA",
    }
)
_FURNITURE_PHRASES = (
    "POR ELLO",
    "POR TANTO",
    "EN USO DE",
    # Quien firma, que en las resoluciones de rectoría va justo debajo del
    # asunto: «EL RECTOR DE LA UNIVERSIDAD DE CARTAGENA» no nombra nada.
    "EL RECTOR",
    "LA RECTORA",
    "EL SENOR RECTOR",
    "EL VICERRECTOR",
    "LA VICERRECTORA",
    "HOJA NO",
)

#: Cómo empieza el asunto de una resolución: «Por medio de la cual se designan
#: los docentes de cátedra», «Por la cual se fija…». Es el nombre del documento,
#: y manda sobre cualquier otro renglón: puede traer fechas -- «entre el 1° de
#: enero y el 31 de diciembre de 2024» -- sin ser por eso un fechado, y puede
#: ocupar tres renglones (las 00001 a 00011 de 2025 de rectoría) o cinco (la 00667).
_ASUNTO = re.compile(
    r"^\W*(POR\s+MEDIO\s+DE[L]?\s+(LA\s+|EL\s+)?[CE]UA[LI1]|POR\s+(LA|EL)\s+[CE]UA[LI1]"
    r"|MEDIANTE\s+(LA|EL)\s+[CE]UA[LI1])\b"
)
#: El OCR lee «cual» como «eual» o «cuai» justo en la fórmula, que es lo que se
#: ve en el nombre del archivo.
_CUAL_DANADO = re.compile(r"\b(la|el|del|La|El|Del|LA|EL|DEL)\s+(?:eual|cuai|cua1|eua1|euai)\b")
#: Cuántos renglones puede ocupar el asunto, y hasta cuánto se escribe entero.
_RENGLONES_DEL_ASUNTO = 6
MAX_LENGTH_DEL_ASUNTO = 300
_COMILLAS = "\"“”«»'‘’"

_MONTHS = (
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "SETIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
)

_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_NUMERIC_DATE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
_MIN_TITLE_WORDS = 3
_TRAILING_NOISE = " ,;:.-–—"


#: Quien firma con el «EL» mal leído: «K1 Rector de la Universidad de Cartagena»
#: (la 00678 de 2025) sigue siendo quien firma, no parte del asunto.
_QUIEN_FIRMA_MAL_LEIDO = re.compile(r"^[EK][L1I!|]\s+(SENOR\s+|SENORA\s+)?(VICE)?RECTORA?\b")
#: Donde empieza el cuerpo: lo que venga después es una frase, no un nombre.
_EMPIEZA_EL_CUERPO = ("CONSIDERANDO", "VISTO", "VISTOS", "RESUELVE")
#: La «l» que el OCR lee como «!» o «¡» en la letra de las copias: «¡a cual se
#: establece e! procedimiento … de! proceso … Comité Centra!» (la 00667 de 2025).
#: En el asunto de una resolución no hay exclamaciones que perder.
_L_COMO_EXCLAMACION = (
    (re.compile(r"(?<=\w)!"), "l"),
    (re.compile(r"(?<!\w)¡(?=\w)"), "l"),
    (re.compile(r"\bei\b"), "el"),
)
#: Lo que en un membrete encima del encabezado nombra a quien expide, no al
#: documento.
_MEMBRETE = ("UNIVERSIDAD", "FUNDADA", "REPUBLICA", "MINISTERIO", "NIT")
_RENGLONES_DEL_TITULO_IMPRESO = 4


def _sin_exclamaciones_del_ocr(texto: str) -> str:
    for patron, letra in _L_COMO_EXCLAMACION:
        texto = patron.sub(letra, texto)
    return texto


def _titulo_impreso_encima(lines: list[str], encabezado: int, max_length: int) -> str | None:
    """El título que el formato imprime encima del encabezado, si lo trae.

    Las resoluciones de viáticos van sobre un formato que abre con «COMISION Y
    OTORGAMIENTO DE VIATICOS / PARA TRABAJADORES Y DOCENTES DE / PLANTA» y no
    traen «Por medio de la cual»: ese es su nombre. Sólo cuenta un bloque en
    mayúsculas que no sea el membrete.
    """
    bloque: list[str] = []
    for linea in lines[:encabezado]:
        limpia = linea.strip()
        letras = [c for c in limpia if c.isalpha()]
        mayusculas = bool(letras) and all(c.isupper() for c in letras)
        membrete = strip_accents(limpia).upper().startswith(_MEMBRETE) or _YEAR.search(limpia)
        if mayusculas and not membrete:
            bloque.append(limpia)
            if len(bloque) == _RENGLONES_DEL_TITULO_IMPRESO:
                break
        elif bloque:
            break
    # Las motas del escáner que quedan en el renglón («VIATICOS ^3») no son
    # palabras.
    titulo = " ".join(w for w in " ".join(bloque).split() if any(c.isalpha() for c in w))
    if len(titulo.split()) < _MIN_TITLE_WORDS:
        return None
    return _clean(titulo, max_length) or None


def _looks_like_a_dateline(upper: str) -> bool:
    if _NUMERIC_DATE.search(upper):
        return True
    return bool(_YEAR.search(upper)) and any(month in upper for month in _MONTHS)


def _is_furniture(line: str) -> bool:
    upper = strip_accents(line).upper().strip()
    if upper.startswith(_FURNITURE_PHRASES) or _QUIEN_FIRMA_MAL_LEIDO.match(upper):
        return True
    words = upper.split()
    if words and words[0].strip(".,:;") in _FURNITURE_WORDS:
        return True
    return _looks_like_a_dateline(upper)


def _clean(value: str, max_length: int) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip(_TRAILING_NOISE)
    if len(collapsed) <= max_length:
        return collapsed
    cut = collapsed[:max_length]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.strip(_TRAILING_NOISE)


def _el_asunto(lines: list[str], desde: int, max_length: int) -> str | None:
    """El asunto que empieza en ``lines[desde]``, con los renglones que lo continúan.

    Termina donde cierran las comillas, o donde empieza otra cosa: quien
    firma, la fórmula de las facultades o el CONSIDERANDO.
    """
    partes: list[str] = []
    for linea in lines[desde : desde + _RENGLONES_DEL_ASUNTO]:
        limpia = linea.strip()
        if not limpia:
            if partes:
                break
            continue
        if partes and (_is_furniture(limpia) or limpia.strip(_COMILLAS).startswith(("CONSIDERANDO", "VISTO"))):
            break
        partes.append(limpia)
        cuerpo = " ".join(partes)
        if cuerpo.count("”") or (cuerpo[:1] in "\"“«" and cuerpo.rstrip()[-1:] in "\"”»" and len(cuerpo) > 1):
            break
    texto = _sin_exclamaciones_del_ocr(" ".join(partes)).strip(_COMILLAS + " " + _TRAILING_NOISE)
    texto = _CUAL_DANADO.sub(lambda m: f"{m.group(1)} cual", texto)
    return _clean(texto, max_length) or None


def extract_title(
    page_text: str,
    *,
    max_scan_lines: int = DEFAULT_SCAN_LINES,
    max_length: int = DEFAULT_MAX_LENGTH,
    titulo_encima: bool = False,
) -> str | None:
    """Name the document that starts on this page.

    Two readings, in order of trust: an explicit subject marker, then the first
    substantive caption line under the heading. Anything else -- datelines, folio
    stamps, the opening of the recitals -- is furniture and gets skipped, and
    nothing past the start of the body (CONSIDERANDO, VISTO) is a name.

    ``titulo_encima`` lets a form's printed title above the heading name the
    document when nothing below does; only the resolution cascade asks for it,
    because elsewhere what sits above the heading is a letterhead.
    """
    lines = page_text.splitlines()
    if not lines:
        return None

    anchors = find_anchors(page_text)
    start = anchors[0].line_index + 1 if anchors else 0

    # El asunto de una resolución, si lo hay en los renglones de debajo: es el
    # nombre del documento, y gana a cualquier otro renglón con forma de título.
    for indice in range(start, min(len(lines), start + max_scan_lines)):
        if _ASUNTO.match(_sin_exclamaciones_del_ocr(strip_accents(lines[indice])).upper().strip()):
            return _el_asunto(lines, indice, max(max_length, MAX_LENGTH_DEL_ASUNTO))

    for line in lines[start : start + max_scan_lines]:
        stripped = line.strip()
        if not stripped:
            continue

        subject = _SUBJECT_LINE.match(stripped)
        if subject:
            return _clean(subject.group(2), max_length) or None

        if strip_accents(stripped).upper().strip(_COMILLAS).startswith(_EMPIEZA_EL_CUERPO):
            break
        if _is_furniture(stripped) or len(stripped.split()) < _MIN_TITLE_WORDS:
            continue
        return _clean(stripped, max_length) or None

    if titulo_encima and anchors:
        return _titulo_impreso_encima(lines, anchors[0].line_index, max_length)
    return None


def slugify(value: str, max_length: int = DEFAULT_SLUG_LENGTH) -> str:
    """Reduce a title to a filename fragment that no filesystem will argue with."""
    ascii_only = strip_accents(value).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    if len(slug) <= max_length:
        return slug
    return slug[:max_length].rsplit("-", 1)[0].strip("-")
