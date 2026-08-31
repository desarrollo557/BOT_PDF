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
_FURNITURE_PHRASES = ("POR ELLO", "POR TANTO", "EN USO DE")

_MONTHS = (
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "SETIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
)

_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_NUMERIC_DATE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
_MIN_TITLE_WORDS = 3
_TRAILING_NOISE = " ,;:.-–—"


def _looks_like_a_dateline(upper: str) -> bool:
    if _NUMERIC_DATE.search(upper):
        return True
    return bool(_YEAR.search(upper)) and any(month in upper for month in _MONTHS)


def _is_furniture(line: str) -> bool:
    upper = strip_accents(line).upper().strip()
    if upper.startswith(_FURNITURE_PHRASES):
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


def extract_title(
    page_text: str,
    *,
    max_scan_lines: int = DEFAULT_SCAN_LINES,
    max_length: int = DEFAULT_MAX_LENGTH,
) -> str | None:
    """Name the document that starts on this page.

    Two readings, in order of trust: an explicit subject marker, then the first
    substantive caption line under the heading. Anything else -- datelines, folio
    stamps, the opening of the recitals -- is furniture and gets skipped.
    """
    lines = page_text.splitlines()
    if not lines:
        return None

    anchors = find_anchors(page_text)
    start = anchors[0].line_index + 1 if anchors else 0

    for line in lines[start : start + max_scan_lines]:
        stripped = line.strip()
        if not stripped:
            continue

        subject = _SUBJECT_LINE.match(stripped)
        if subject:
            return _clean(subject.group(2), max_length) or None

        if _is_furniture(stripped) or len(stripped.split()) < _MIN_TITLE_WORDS:
            continue
        return _clean(stripped, max_length) or None

    return None


def slugify(value: str, max_length: int = DEFAULT_SLUG_LENGTH) -> str:
    """Reduce a title to a filename fragment that no filesystem will argue with."""
    ascii_only = strip_accents(value).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    if len(slug) <= max_length:
        return slug
    return slug[:max_length].rsplit("-", 1)[0].strip("-")
