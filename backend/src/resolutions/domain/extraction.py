from __future__ import annotations

import re
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


@dataclass(frozen=True, slots=True)
class RawCandidate:
    """A code found next to an anchor, before any judgement about who owns it."""

    code: ResolutionCode
    anchor: Anchor
    line_index: int
    total_lines: int
    line_text: str
    context_before: str


def _looks_like_a_code(token: str) -> bool:
    if not _CODE_SHAPE.match(token):
        return False
    return sum(ch.isdigit() for ch in token) >= _MIN_DIGITS


def _first_code(segment: str) -> ResolutionCode | None:
    """Read the first plausible code in ``segment``.

    The scan stops at the first token that is neither a separator nor a code.
    Walking past real words would let "RESOLUCION DE DIRECTORIO 2024" capture a
    year as if it were a resolution number.
    """
    for token in segment.split():
        cleaned = token.strip(",;()[]\"'")
        if not cleaned or cleaned in _SEPARATOR_TOKENS:
            continue
        if _looks_like_a_code(cleaned):
            return ResolutionCode.try_parse(cleaned)
        return None
    return None


def extract_candidates(page_text: str) -> list[RawCandidate]:
    """Every (anchor, code) pair on the page, in reading order."""
    lines = normalized_lines(page_text)
    original = page_text.splitlines()
    total = len(lines)

    candidates: list[RawCandidate] = []
    for anchor in find_anchors(page_text):
        line = lines[anchor.line_index]
        code = _first_code(line[anchor.end :])
        if code is None and anchor.line_index + 1 < total:
            # Centred headers wrap: the word ends the line and the number starts
            # the next one.
            code = _first_code(lines[anchor.line_index + 1])
        if code is None:
            continue

        candidates.append(
            RawCandidate(
                code=code,
                anchor=anchor,
                line_index=anchor.line_index,
                total_lines=total,
                line_text=original[anchor.line_index],
                context_before=line[: anchor.start],
            )
        )
    return candidates
