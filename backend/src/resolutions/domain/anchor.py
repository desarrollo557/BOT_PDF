from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .text_distance import damerau_levenshtein

# Words the anchor may appear as. Long forms tolerate OCR damage; the short
# abbreviations must match exactly, because two edits away from "RES" is half
# the Spanish dictionary.
_FUZZY_TERMS = ("RESOLUCION", "RESOLUCIONES")
_EXACT_TERMS = frozenset({"RESOL", "RES", "RSLN"})

_MAX_ANCHOR_DISTANCE = 2
_MIN_FUZZY_LENGTH = 8

# Glyph pairs OCR engines confuse constantly. Folding happens only for anchor
# matching -- never for codes, where a digit turned into a letter is corruption.
_GLYPH_FOLD = str.maketrans({"0": "O", "1": "I", "5": "S", "6": "G", "8": "B", "|": "I"})
_LIGATURE_FOLD = (("RN", "M"),)

_TOKEN = re.compile(r"\S+")
_EDGE_PUNCTUATION = ".,;:()[]\"'¡!¿?°º-–—_"


@dataclass(frozen=True, slots=True)
class Anchor:
    """A word on the page that reads like "resolución"."""

    line_index: int
    start: int
    end: int
    matched_text: str
    term: str
    distance: int


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(text: str) -> str:
    """Uppercase, accent-free, single-spaced text.

    Every offset produced by :func:`find_anchors` refers to a normalized line, so
    callers must slice the output of :func:`normalized_lines`, never the raw text.
    """
    return re.sub(r"\s+", " ", strip_accents(text).upper()).strip()


def normalized_lines(text: str) -> list[str]:
    return [normalize(line) for line in text.splitlines()]


def fold_ocr_confusions(text: str) -> str:
    folded = text
    for pair, replacement in _LIGATURE_FOLD:
        folded = folded.replace(pair, replacement)
    return folded.translate(_GLYPH_FOLD)


def _match_term(token: str) -> tuple[str, int] | None:
    folded = fold_ocr_confusions(token)
    if folded in _EXACT_TERMS:
        return folded, 0
    if len(folded) < _MIN_FUZZY_LENGTH or not folded.startswith("R"):
        # Anchoring on the leading R keeps "SOLUCION" and friends out; they sit
        # inside the edit budget but are never the word we are looking for.
        return None

    best: tuple[str, int] | None = None
    for term in _FUZZY_TERMS:
        distance = damerau_levenshtein(folded, term, ceiling=_MAX_ANCHOR_DISTANCE)
        if distance <= _MAX_ANCHOR_DISTANCE and (best is None or distance < best[1]):
            best = (term, distance)
    return best


def find_anchors(text: str) -> list[Anchor]:
    """Locate every "resolución"-like word, tolerating OCR damage."""
    anchors: list[Anchor] = []
    for line_index, line in enumerate(normalized_lines(text)):
        for token in _TOKEN.finditer(line):
            core = token.group().strip(_EDGE_PUNCTUATION)
            if not core:
                continue
            matched = _match_term(core)
            if matched is None:
                continue
            term, distance = matched
            anchors.append(
                Anchor(
                    line_index=line_index,
                    start=token.start(),
                    end=token.end(),
                    matched_text=core,
                    term=term,
                    distance=distance,
                )
            )
    return anchors
